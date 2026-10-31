import base64
import hashlib
from io import BytesIO

import qrcode

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError


_INTERNAL_TRANSITION_TOKEN = object()


class EtatCivilActeOfficiel(models.AbstractModel):
    _name = "etat.civil.acte.officiel"
    _description = "Acte officiel d'état civil"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    numero_acte = fields.Char(
        string="Numéro d'acte",
        required=False,
        copy=False,
        tracking=True,
    )
    feuillet_numero = fields.Integer(string="N° de feuillet", required=True)
    registre_id = fields.Many2one(
        "etat.civil.registre",
        string="Registre",
        required=True,
        tracking=True,
    )
    date_dressage = fields.Datetime(
        string="Date et heure d'établissement",
        default=fields.Datetime.now,
        required=True,
        tracking=True,
    )
    texte_integral_acte = fields.Text(
        string="Texte intégral de l'acte",
        required=True,
    )
    statut = fields.Selection(
        [
            ("brouillon", "Brouillon"),
            ("en_attente", "En attente de validation"),
            ("a_corriger", "À corriger"),
            ("valide", "Validé / Signé"),
            ("rectifie", "Rectifié"),
            ("annule", "Annulé"),
            ("archive", "Archivé"),
        ],
        string="Statut",
        default="brouillon",
        required=True,
        tracking=True,
    )
    motif_annulation = fields.Text(string="Motif d'annulation")
    motif_correction = fields.Text(string="Motif de retour pour correction", copy=False, tracking=True)
    notes_transmission = fields.Text(string="Notes de transmission", copy=False)

    agent_transmetteur_id = fields.Many2one(
        "res.users",
        string="Agent transmetteur",
        readonly=True,
        copy=False,
        tracking=True,
    )
    date_transmission = fields.Datetime(
        string="Date d'envoi pour validation",
        readonly=True,
        copy=False,
        tracking=True,
    )
    officier_validateur_id = fields.Many2one(
        "res.users",
        string="Officier compétent / validateur",
        readonly=True,
        copy=False,
        tracking=True,
    )
    date_validation = fields.Datetime(
        string="Date de validation",
        readonly=True,
        copy=False,
        tracking=True,
    )

    hash_empreinte_num = fields.Char(
        string="Empreinte SHA-256",
        readonly=True,
        copy=False,
    )
    qr_code_signature = fields.Char(
        string="Données de vérification QR",
        readonly=True,
        copy=False,
    )
    qr_code_image = fields.Binary(
        string="QR de vérification",
        readonly=True,
        copy=False,
        attachment=False,
    )

    _sql_constraints = [
        (
            "numero_acte_registre_unique",
            "unique(numero_acte, registre_id)",
            "Le numéro d'acte doit être unique dans le registre.",
        ),
        (
            "feuillet_registre_unique",
            "unique(feuillet_numero, registre_id)",
            "Le numéro de feuillet doit être unique dans le registre.",
        ),
    ]

    @api.constrains("feuillet_numero", "registre_id")
    def _check_feuillet_numero(self):
        for record in self:
            if record.feuillet_numero < 1:
                raise ValidationError("Le numéro de feuillet doit être supérieur à zéro.")

    @api.constrains("statut", "motif_annulation")
    def _check_annulation(self):
        for record in self:
            if record.statut == "annule" and not (record.motif_annulation or "").strip():
                raise ValidationError("Le motif d'annulation est obligatoire.")

    def _ensure_officier(self):
        if not self.env.user.has_group("etat_civil.group_etat_civil_officier"):
            raise UserError("Seul un officier d'état civil peut effectuer cette opération.")

    def _ensure_competence_territoriale(self):
        self.ensure_one()
        user = self.env.user
        centre = self.registre_id.centre_id
        if not centre or centre not in user.etat_civil_centre_ids:
            raise AccessError(
                _("Vous n'êtes pas affecté au centre d'état civil de ce dossier (%s). Opération refusée.")
                % (centre.nom_centre if centre else _("non défini"))
            )

    def _compute_integrity_hash(self):
        self.ensure_one()
        payload = "|".join(
            [
                str(self._name),
                str(self.id),
                str(self.numero_acte or ""),
                str(self.date_dressage or ""),
                str(self.texte_integral_acte or ""),
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def verify_integrity_hash(self):
        """Vérifie si l'empreinte cryptographique stockée correspond au contenu actuel de l'acte."""
        self.ensure_one()
        if not self.hash_empreinte_num:
            return False, _("Aucune empreinte enregistrée sur cet acte.")
        expected = self._compute_integrity_hash()
        if self.hash_empreinte_num == expected:
            return True, _("Contrôle interne d'intégrité valide : l'acte est intègre.")
        return False, _("Alerte de discordance d'empreinte : le contenu actuel ne correspond plus au hash initialement calculé.")

    def _get_competent_officiers(self):
        self.ensure_one()
        centre = self.registre_id.centre_id
        officier_group = self.env.ref("etat_civil.group_etat_civil_officier")
        base_officiers = self.env["res.users"].sudo().search([
            ("groups_id", "in", officier_group.id),
            ("active", "=", True),
            ("share", "=", False),
        ])
        if not centre:
            return self.env["res.users"]
        return base_officiers.filtered(
            lambda user: centre in user.etat_civil_centre_ids
        )

    def _check_specific_transmission_requirements(self):
        """Hook pour les contrôles spécifiques à chaque type d'acte (surchargé dans les sous-classes)."""
        return []

    def _status_blocks_transmission(self):
        self.ensure_one()
        if self.statut == "en_attente":
            return _("Ce dossier est déjà en attente de validation.")
        if self.statut == "valide":
            return _("Ce dossier est déjà validé et ne peut plus être transmis.")
        if self.statut in ("annule", "archive", "rectifie"):
            return _("Ce dossier au statut '%s' ne peut pas être transmis.") % self.statut
        if self.statut not in ("brouillon", "a_corriger"):
            return _("Le dossier est déjà au statut '%s' et ne peut pas être transmis.") % self.statut
        return False

    def action_lister_officiers_competents(self):
        self.ensure_one()
        self.check_access_rights("read")
        self.check_access_rule("read")
        return [
            {"id": officier.id, "name": officier.name}
            for officier in self._get_competent_officiers()
        ]

    @api.model
    def _generate_numero_acte(self):
        """Generate the next act number from ir.sequence.

        This method MUST only be called from create() to avoid consuming
        sequence numbers when a form is merely opened or cancelled.
        """
        mapping = {
            "etat.civil.acte.naissance": {
                "code": "etat.civil.acte.naissance",
                "xmlid": "etat_civil.sequence_etat_civil_acte_naissance",
                "name": "Numéro d'acte de naissance",
                "prefix": "NAI/%(year)s/",
            },
            "etat.civil.acte.mariage": {
                "code": "etat.civil.acte.mariage",
                "xmlid": "etat_civil.sequence_etat_civil_acte_mariage",
                "name": "Numéro d'acte de mariage",
                "prefix": "MAR/%(year)s/",
            },
            "etat.civil.acte.deces": {
                "code": "etat.civil.acte.deces",
                "xmlid": "etat_civil.sequence_etat_civil_acte_deces",
                "name": "Numéro d'acte de décès",
                "prefix": "DEC/%(year)s/",
            },
        }
        cfg = mapping.get(self._name)
        if not cfg:
            if self._name == "etat.civil.acte.officiel":
                return False
            raise UserError(_("La séquence du numéro d'acte n'est pas configurée pour ce type d'acte."))

        seq_model = self.env["ir.sequence"]
        numero = seq_model.next_by_code(cfg["code"])
        if not numero:
            sequence = self.env.ref(cfg["xmlid"], raise_if_not_found=False)
            if sequence:
                numero = sequence.sudo().next_by_id()
        if not numero:
            seq = seq_model.sudo().search([("code", "=", cfg["code"])], limit=1)
            if seq:
                numero = seq.next_by_id()
            else:
                seq = seq_model.sudo().create({
                    "name": cfg["name"],
                    "code": cfg["code"],
                    "prefix": cfg["prefix"],
                    "padding": 5,
                    "number_increment": 1,
                    "implementation": "no_gap",
                    "company_id": False,
                })
                numero = seq.next_by_id()

        return numero

    @api.model
    def _get_next_feuillet_numero(self, registre_id):
        dernier_acte = self.search(
            [("registre_id", "=", registre_id)],
            order="feuillet_numero desc, id desc",
            limit=1,
        )
        return (dernier_acte.feuillet_numero or 0) + 1

    @api.onchange("registre_id")
    def _onchange_registre_id_feuillet_numero(self):
        for record in self:
            if record.registre_id:
                record.feuillet_numero = record._get_next_feuillet_numero(
                    record.registre_id.id
                )
            else:
                record.feuillet_numero = False

    def _check_pret_pour_transmission(self):
        self.ensure_one()
        errors = []
        status_error = self._status_blocks_transmission()
        if status_error:
            errors.append(status_error)
        if not (self.numero_acte or "").strip():
            errors.append(_("Le numéro d'acte est obligatoire."))
        if self.feuillet_numero is None or (self.feuillet_numero or 0) < 1:
            errors.append(_("Le numéro de feuillet doit être supérieur à zéro."))
        if not self.registre_id:
            errors.append(_("Le rattachement à un registre est obligatoire."))
        elif self.registre_id.est_cloture:
            errors.append(_("Le registre sélectionné est clôturé."))
        if not (self.texte_integral_acte or "").strip():
            errors.append(_("Le texte officiel/intégral de l'acte ne peut pas être vide."))

        specific_errors = self._check_specific_transmission_requirements()
        if specific_errors:
            errors.extend(specific_errors)

        self._sync_pieces_justificatives()
        missing_pieces = self.piece_ids.filtered(
            lambda p: p.obligatoire and p.etat == "a_fournir"
        )
        if missing_pieces:
            names = ", ".join(missing_pieces.mapped("display_name"))
            errors.append(_("Pièces justificatives obligatoires manquantes ou non reçues : %s.") % names)

        competent_officiers = self._get_competent_officiers()
        if not competent_officiers:
            errors.append(
                _("Aucun officier compétent n'a été trouvé pour ce dossier. Vérifiez l'affectation des utilisateurs ou contactez l'administrateur.")
            )

        centre = self.registre_id.centre_id
        if not centre or centre not in self.env.user.etat_civil_centre_ids:
            errors.append(
                _("Vous n'êtes pas affecté au centre de ce dossier (%s). Transmission interdite.")
                % (centre.nom_centre if centre else _("non défini"))
            )

        return errors

    def _resolve_competent_officier(self, officier, competent_officiers):
        if type(officier) is int:
            officier = self.env["res.users"].browse(officier).exists()
        if (
            not officier
            or getattr(officier, "_name", None) != "res.users"
            or len(officier) != 1
            or officier not in competent_officiers
        ):
            raise AccessError(_("L'officier sélectionné n'est pas compétent pour ce dossier."))
        return officier

    def action_envoyer_validation(self, officier=None, notes=None):
        if not self.env.user.has_group("etat_civil.group_etat_civil_agent"):
            raise AccessError(_("Seul un agent d'état civil peut transmettre un dossier pour validation."))
        if not self:
            raise UserError(_("Sélectionnez au moins un dossier à transmettre."))

        if len(self) > 1:
            transmitted = 0
            errors_summary = []
            for record in self:
                rec_errors = record._check_pret_pour_transmission()
                if rec_errors:
                    errors_summary.append(f"{record.numero_acte or record.id}: " + "; ".join(rec_errors))
                    continue
                competent = record._get_competent_officiers()
                if officier:
                    target_officier = record._resolve_competent_officier(officier, competent)
                elif len(competent) == 1:
                    target_officier = competent
                else:
                    errors_summary.append(
                        f"{record.numero_acte or record.id}: "
                        + _("Plusieurs officiers sont compétents; une sélection explicite est requise.")
                    )
                    continue
                record._execute_transmission(target_officier, notes)
                transmitted += 1

            if errors_summary and transmitted == 0:
                raise ValidationError(
                    _("Impossible d'envoyer les dossiers sélectionnés :\n")
                    + "\n".join(f"- {e}" for e in errors_summary)
                )

            msg = _("%d dossier(s) transmis avec succès pour validation.") % transmitted
            if errors_summary:
                msg += _("\nCertains dossiers n'ont pas pu être transmis :\n") + "\n".join(f"- {e}" for e in errors_summary)

            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Transmission pour validation"),
                    "message": msg,
                    "type": "success" if transmitted > 0 else "warning",
                    "sticky": bool(errors_summary),
                },
            }

        self.ensure_one()
        status_error = self._status_blocks_transmission()
        if status_error:
            raise UserError(status_error)
        errors = self._check_pret_pour_transmission()
        if errors:
            raise ValidationError(
                _("Impossible d'envoyer ce dossier pour validation. Les informations suivantes sont manquantes :\n")
                + "\n".join(f"- {e}" for e in errors)
            )

        competent = self._get_competent_officiers()
        if not officier:
            if len(competent) == 1:
                officier = competent
            else:
                action = self.env.ref("etat_civil.action_etat_civil_transmission_acte_wizard").read()[0]
                action["context"] = {
                    "default_acte_type": self._ec_acte_type(),
                    "default_acte_id": self.id,
                    "default_acte_display": f"{self.numero_acte} — {self.display_name}",
                    "default_centre_id": self.registre_id.centre_id.id if self.registre_id else False,
                }
                return action
        else:
            officier = self._resolve_competent_officier(officier, competent)

        self._execute_transmission(officier, notes)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Transmission réussie"),
                "message": _("Le dossier a été transmis à l'officier compétent."),
                "type": "success",
                "sticky": False,
            },
        }

    def _execute_transmission(self, officier, notes=None):
        self.ensure_one()
        vals = {
            "statut": "en_attente",
            "agent_transmetteur_id": self.env.user.id,
            "date_transmission": fields.Datetime.now(),
            "officier_validateur_id": officier.id,
            "motif_correction": False,
        }
        if notes:
            vals["notes_transmission"] = notes

        previous_officer = self.officier_validateur_id
        previous_date = self.date_transmission
        self.with_context(etat_civil_transition_token=_INTERNAL_TRANSITION_TOKEN).write(vals)

        if previous_date:
            self.message_post(
                body=_(
                    "Nouvelle transmission après un traitement précédent "
                    "(précédemment envoyé le %s à %s)."
                )
                % (
                    previous_date,
                    previous_officer.name if previous_officer else _("non assigné"),
                )
            )

        body = _("Le dossier a été transmis à l'officier compétent.") + " "
        body += _("Destinataire : <b>%s</b>. Agent : <b>%s</b>.") % (
            officier.name,
            self.env.user.name,
        )
        if notes:
            body += _("<br/><b>Note de l'agent :</b> %s") % notes
        self.message_post(body=body)

        todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        if not todo_type:
            raise UserError(_("Le type d'activité de validation n'est pas configuré dans Odoo."))
        self.activity_schedule(
            activity_type_id=todo_type.id,
            summary=_("Validation de l'acte %s") % self.numero_acte,
            note=_("L'agent %s a soumis ce dossier pour examen et signature.") % self.env.user.name,
            user_id=officier.id,
        )

    def action_demander_correction(self):
        self.ensure_one()
        self._ensure_officier()
        self._ensure_competence_territoriale()
        action = self.env.ref("etat_civil.action_etat_civil_retour_correction_wizard").read()[0]
        action["context"] = {
            "default_action_type": "correction",
            "default_acte_type": self._ec_acte_type(),
            "default_acte_id": self.id,
            "default_acte_display": f"{self.numero_acte} — {self.display_name}",
        }
        return action

    def action_retourner_correction(self, motif):
        self._ensure_officier()
        motif = (motif or "").strip()
        if not motif:
            raise ValidationError(_("Le motif de retour pour correction est obligatoire."))
        for record in self:
            record._ensure_competence_territoriale()
            if record.statut != "en_attente":
                raise UserError(_("Seul un dossier en attente de validation peut être retourné pour correction."))
            record.with_context(
                etat_civil_transition_token=_INTERNAL_TRANSITION_TOKEN
            ).write({
                "statut": "a_corriger",
                "motif_correction": motif,
            })
            record.message_post(
                body=_("Dossier retourné à l'agent pour correction par l'officier <b>%s</b>.<br/><b>Motif :</b> %s")
                % (self.env.user.name, motif)
            )
            # Notify transmitting agent via activity
            if record.agent_transmetteur_id:
                todo_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
                if not todo_type:
                    raise UserError(_("Le type d'activité de correction n'est pas configuré dans Odoo."))
                record.activity_schedule(
                    activity_type_id=todo_type.id,
                    summary=_("Corrections requises pour l'acte %s") % record.numero_acte,
                    note=motif,
                    user_id=record.agent_transmetteur_id.id,
                )
        return True

    def action_ouvrir_refus(self):
        self.ensure_one()
        self._ensure_officier()
        self._ensure_competence_territoriale()
        action = self.env.ref("etat_civil.action_etat_civil_retour_correction_wizard").read()[0]
        action["context"] = {
            "default_action_type": "refus",
            "default_acte_type": self._ec_acte_type(),
            "default_acte_id": self.id,
            "default_acte_display": f"{self.numero_acte} — {self.display_name}",
        }
        return action

    def action_refuser_acte(self, motif):
        self._ensure_officier()
        motif = (motif or "").strip()
        if not motif:
            raise ValidationError(_("Le motif de refus est obligatoire."))
        for record in self:
            record._ensure_competence_territoriale()
            if record.statut != "en_attente":
                raise UserError(_("Seul un dossier en attente de validation peut être refusé."))
            record.with_context(
                etat_civil_transition_token=_INTERNAL_TRANSITION_TOKEN
            ).write({"statut": "annule", "motif_annulation": motif})
            record.message_post(
                body=_("Dossier définitivement refusé par l'officier <b>%s</b>.<br/><b>Motif :</b> %s")
                % (self.env.user.name, motif)
            )
        return True

    def action_valider_acte(self):
        self._ensure_officier()
        for record in self:
            record._ensure_competence_territoriale()
            if record.statut not in ("en_attente", "brouillon"):
                raise UserError(_("Seul un dossier en attente de validation (ou en brouillon direct) peut être validé."))
            if record.registre_id.est_cloture:
                raise UserError(_("Impossible de valider un acte dans un registre clôturé."))
            if not (record.texte_integral_acte or "").strip():
                raise ValidationError(_("Le texte intégral de l'acte ne peut pas être vide."))
            record._sync_pieces_justificatives()
            record._check_pieces_justificatives()

            hash_value = record._compute_integrity_hash()
            qr_payload = f"etat-civil:{record._name}:{record.id}:{hash_value}"
            qr_image = qrcode.make(qr_payload)
            buffer = BytesIO()
            qr_image.save(buffer, format="PNG")

            record.with_context(
                etat_civil_transition_token=_INTERNAL_TRANSITION_TOKEN
            ).write(
                {
                    "hash_empreinte_num": hash_value,
                    "qr_code_signature": qr_payload,
                    "qr_code_image": base64.b64encode(buffer.getvalue()),
                    "statut": "valide",
                    "officier_validateur_id": self.env.user.id,
                    "date_validation": fields.Datetime.now(),
                    "motif_correction": False,
                }
            )

            record.message_post(
                body=(
                    _("Acte validé et signé par l'officier <b>%s</b>. Empreinte SHA-256 générée et QR de vérification créé.")
                    % self.env.user.name
                )
            )

            # Close any open validation activities on this record
            record.activity_feedback(["mail.mail_activity_data_todo"])
        return True

    def _required_piece_codes(self):
        return set()

    def _pieces_owner_field(self):
        return {
            "etat.civil.acte.naissance": "acte_naissance_id",
            "etat.civil.acte.mariage": "acte_mariage_id",
            "etat.civil.acte.deces": "acte_deces_id",
            "etat.civil.mention.marginale": "mention_id",
        }.get(self._name)

    def _sync_pieces_justificatives(self):
        owner_field = self._pieces_owner_field()
        if not owner_field or "piece_ids" not in self._fields:
            return
        for record in self:
            required = record._required_piece_codes()
            existing = {piece.name: piece for piece in record.piece_ids}
            for code, piece in existing.items():
                should_be_required = code in required
                if piece.obligatoire != should_be_required:
                    piece.with_context(etat_civil_sync_required=True).write(
                        {"obligatoire": should_be_required}
                    )
            missing = required - existing.keys()
            if missing:
                self.env["etat.civil.piece.justificative"].create(
                    [
                        {
                            "name": code,
                            "obligatoire": True,
                            owner_field: record.id,
                        }
                        for code in sorted(missing)
                    ]
                )

    def _check_pieces_justificatives(self):
        self.ensure_one()
        missing = self.piece_ids.filtered(
            lambda piece: piece.obligatoire and piece.etat != "verifie"
        )
        if missing:
            names = ", ".join(missing.mapped("display_name"))
            raise ValidationError(
                _("Les pièces obligatoires doivent être reçues et vérifiées par un officier : %s.")
                % names
            )

    def action_ouvrir_annulation(self):
        self.ensure_one()
        self._ensure_officier()
        self._ensure_competence_territoriale()
        if self.statut != "valide":
            raise UserError(_("Seul un acte validé peut être annulé."))
        action = self.env.ref("etat_civil.action_etat_civil_annulation_acte_wizard").read()[0]
        action["context"] = {
            "default_acte_type": self._ec_acte_type(),
            "default_acte_id": self.id,
            "default_acte_display": f"{self.numero_acte} — {self.display_name}",
        }
        return action

    def _ec_acte_type(self):
        return {
            "etat.civil.acte.naissance": "naissance",
            "etat.civil.acte.mariage": "mariage",
            "etat.civil.acte.deces": "deces",
        }.get(self._name, "naissance")

    def action_annuler_acte(self, motif):
        self._ensure_officier()
        motif = (motif or "").strip()
        if not motif:
            raise ValidationError(_("Le motif d'annulation est obligatoire."))
        for record in self:
            record._ensure_competence_territoriale()
            if record.statut != "valide":
                raise UserError(_("Seul un acte validé peut être annulé."))
            record.with_context(
                etat_civil_transition_token=_INTERNAL_TRANSITION_TOKEN
            ).write({"statut": "annule", "motif_annulation": motif})
            record.message_post(body=_("Acte annulé. Motif : %s") % motif)
        return True

    def action_rectifier_acte(self):
        self._ensure_officier()
        for record in self:
            record._ensure_competence_territoriale()
            if record.statut != "valide":
                raise UserError(_("Seul un acte validé peut être rectifié."))
            record.with_context(
                etat_civil_transition_token=_INTERNAL_TRANSITION_TOKEN
            ).write({"statut": "rectifie"})
            record.message_post(body=_("Acte marqué comme rectifié."))
        return True

    def action_archiver_acte(self):
        self._ensure_officier()
        for record in self:
            record._ensure_competence_territoriale()
            if record.statut != "annule":
                raise UserError(_("Seul un acte annulé peut être archivé."))
            record.with_context(
                etat_civil_transition_token=_INTERNAL_TRANSITION_TOKEN
            ).write({"statut": "archive"})
            record.message_post(body=_("Acte archivé."))
        return True

    @api.model_create_multi
    def create(self, vals_list):
        internal_transition = (
            self.env.context.get("etat_civil_transition_token") is _INTERNAL_TRANSITION_TOKEN
        )
        pending_feuillets = {}
        for vals in vals_list:
            if not internal_transition:
                vals["statut"] = "brouillon"
                vals.pop("hash_empreinte_num", None)
                vals.pop("qr_code_signature", None)
                vals.pop("qr_code_image", None)
                vals.pop("officier_validateur_id", None)
                vals.pop("date_validation", None)
            # Generate sequence number ONLY at actual record creation,
            # never during form open / default_get / onchange.
            if not (vals.get("numero_acte") or "").strip():
                vals["numero_acte"] = self._generate_numero_acte()
            if (
                vals.get("feuillet_numero") is False
                or vals.get("feuillet_numero") is None
            ) and vals.get("registre_id"):
                registre_id = vals["registre_id"]
                if registre_id not in pending_feuillets:
                    self.env.cr.execute(
                        "SELECT id FROM etat_civil_registre WHERE id = %s FOR UPDATE",
                        [registre_id],
                    )
                    pending_feuillets[registre_id] = self._get_next_feuillet_numero(
                        registre_id
                    ) - 1
                pending_feuillets[registre_id] += 1
                vals["feuillet_numero"] = pending_feuillets[registre_id]
        return super().create(vals_list)

    def write(self, vals):
        internal_transition = (
            self.env.context.get("etat_civil_transition_token") is _INTERNAL_TRANSITION_TOKEN
        )
        if "statut" in vals and not internal_transition:
            raise UserError(
                _("Le statut d'un acte doit être modifié par une action autorisée.")
            )
        if "hash_empreinte_num" in vals and not internal_transition:
            raise UserError(_("L'empreinte d'un acte est gérée automatiquement."))

        if not internal_transition:
            for record in self:
                if record.statut == "en_attente":
                    raise UserError(
                        _("Ce dossier est actuellement en attente de validation par l'officier compétent. "
                          "Il est verrouillé pour éviter les modifications concurrentes. "
                          "Si des modifications sont nécessaires, demandez à l'officier de le renvoyer pour correction.")
                    )
                if record.statut in {"valide", "rectifie", "annule", "archive"}:
                    if set(vals) == {"mention_ids"} and self.env.user.has_group(
                        "etat_civil.group_etat_civil_officier"
                    ):
                        continue
                    raise UserError(
                        _("Un acte au statut '%s' est verrouillé. "
                          "Seul un officier peut y ajouter une mention marginale.")
                        % record.statut
                    )
        return super().write(vals)

    def unlink(self):
        for record in self:
            if record.statut not in ("brouillon", "a_corriger"):
                raise UserError(
                    _("Impossible de supprimer l'acte %s : seuls les brouillons ou les dossiers à corriger peuvent être supprimés.")
                    % record.numero_acte
                )
        return super().unlink()
