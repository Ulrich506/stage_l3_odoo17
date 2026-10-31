import re

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


_STATUS_TRANSITION_TOKEN = object()


class EtatCivilDemandeGuichet(models.Model):
    _name = "etat.civil.demande.guichet"
    _description = "Demande au guichet d'état civil"
    _order = "priorite desc, create_date asc, id asc"

    ticket_numero = fields.Char(
        string="Numéro de ticket",
        required=True,
        readonly=True,
        copy=False,
        default="/",
    )
    citoyen_nom = fields.Char(string="Nom du citoyen", required=True)
    citoyen_cin = fields.Char(string="CIN")
    type_acte = fields.Selection(
        [
            ("naissance", "Naissance"),
            ("mariage", "Mariage"),
            ("deces", "Décès"),
        ],
        string="Type d'acte",
        required=True,
    )
    type_demande = fields.Selection(
        [
            ("copie_integrale", "Copie intégrale"),
            ("extrait", "Extrait d'acte"),
            ("declaration_immediate", "Déclaration immédiate"),
        ],
        string="Type de demande",
        required=True,
    )
    statut = fields.Selection(
        [
            ("en_attente", "En attente"),
            ("en_cours", "Au guichet"),
            ("traite", "Traité"),
            ("annule", "Annulé"),
        ],
        string="Statut",
        required=True,
        default="en_attente",
    )
    priorite = fields.Selection(
        [
            ("normale", "Normale"),
            ("prioritaire", "Prioritaire"),
            ("urgente", "Urgente"),
        ],
        string="Priorité",
        required=True,
        default="normale",
    )
    processed_at = fields.Datetime(string="Date de traitement", readonly=True)

    _sql_constraints = [
        (
            "ticket_numero_unique",
            "unique(ticket_numero)",
            "Le numéro de ticket doit être unique.",
        ),
    ]

    @api.constrains("citoyen_nom", "citoyen_cin")
    def _check_citizen_data(self):
        for record in self:
            if not (record.citoyen_nom or "").strip():
                raise ValidationError("Le nom du citoyen est obligatoire.")
            if record.citoyen_cin and not re.fullmatch(r"\d{12}", record.citoyen_cin):
                raise ValidationError("Le CIN doit comporter exactement 12 chiffres.")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            legacy_cin = vals.pop("citoyen_nin", None)
            if legacy_cin is not None:
                if vals.get("citoyen_cin") not in (None, legacy_cin):
                    raise ValidationError("Les valeurs CIN reçues ne correspondent pas.")
                vals["citoyen_cin"] = legacy_cin
        return self._create_tickets(vals_list)

    def _create_tickets(self, vals_list):
        sequence = self.env["ir.sequence"]
        for vals in vals_list:
            vals["statut"] = "en_attente"
            vals["processed_at"] = False
            if vals.get("ticket_numero", "/") == "/":
                vals["ticket_numero"] = (
                    sequence.next_by_code("etat.civil.demande.guichet") or "/"
                )
        return super().create(vals_list)

    def action_set_status(self, status):
        allowed = {"en_attente", "en_cours", "traite", "annule"}
        if status not in allowed:
            raise ValidationError("Le statut demandé est invalide.")
        for record in self:
            if record.statut == "traite" or record.statut == "annule":
                raise UserError("Un ticket clôturé ne peut plus être modifié.")
            if status == "en_attente" and record.statut != "en_attente":
                raise UserError("Un ticket appelé au guichet ne peut pas être remis en attente.")
            record.with_context(
                etat_civil_ticket_transition_token=_STATUS_TRANSITION_TOKEN
            ).write(
                {
                    "statut": status,
                    "processed_at": fields.Datetime.now() if status == "traite" else False,
                }
            )
        return True

    def action_appeler_au_guichet(self):
        return self.action_set_status("en_cours")

    def action_marquer_traite(self):
        return self.action_set_status("traite")

    def action_annuler_ticket(self):
        return self.action_set_status("annule")

    def write(self, vals):
        vals = dict(vals)
        legacy_cin = vals.pop("citoyen_nin", None)
        if legacy_cin is not None:
            if vals.get("citoyen_cin") not in (None, legacy_cin):
                raise ValidationError("Les valeurs CIN reçues ne correspondent pas.")
            vals["citoyen_cin"] = legacy_cin
        if "statut" in vals and self.env.context.get(
            "etat_civil_ticket_transition_token"
        ) is not _STATUS_TRANSITION_TOKEN:
            raise UserError("Le statut du ticket doit être modifié par une action.")
        if "processed_at" in vals and self.env.context.get(
            "etat_civil_ticket_transition_token"
        ) is not _STATUS_TRANSITION_TOKEN:
            raise UserError("La date de traitement est gérée automatiquement.")
        return super().write(vals)
