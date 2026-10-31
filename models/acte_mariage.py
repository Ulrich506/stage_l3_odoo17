from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EtatCivilActeMariage(models.Model):
    _name = "etat.civil.acte.mariage"
    _inherit = "etat.civil.acte.officiel"
    _description = "Acte de mariage"

    conjoint_1_id = fields.Many2one(
        "etat.civil.individu",
        string="Premier conjoint",
        required=True,
    )
    conjoint_2_id = fields.Many2one(
        "etat.civil.individu",
        string="Second conjoint",
        required=True,
    )
    conjoint_1_est_etranger = fields.Boolean(string="Premier conjoint étranger")
    conjoint_2_est_etranger = fields.Boolean(string="Second conjoint étranger")
    conjoint_1_capacite_requise = fields.Boolean(
        string="Capacité matrimoniale requise"
    )
    conjoint_2_capacite_requise = fields.Boolean(
        string="Capacité matrimoniale requise"
    )
    conjoint_1_residence_etranger_requise = fields.Boolean(
        string="Résidence requise"
    )
    conjoint_2_residence_etranger_requise = fields.Boolean(
        string="Résidence requise"
    )
    temoin_1_id = fields.Many2one(
        "etat.civil.individu", string="Premier témoin", required=False
    )
    temoin_2_id = fields.Many2one(
        "etat.civil.individu", string="Second témoin", required=False
    )
    donnees_historiques_incompletes = fields.Boolean(
        string="Données historiques incomplètes",
        default=False,
        help="Indique un acte importé d'un système historique avec des mentions manquantes à régulariser.",
    )
    motif_regularisation = fields.Text(
        string="Motif de régularisation",
        help="Traçabilité de la régularisation des données historiques par l'officier compétent.",
    )
    date_mariage = fields.Date(string="Date du mariage", required=True, default=fields.Date.context_today)
    lieu_mariage = fields.Char(string="Lieu du mariage", required=True)
    regime_matrimonial = fields.Selection(
        [
            ("communaute_biens", "Communauté de biens"),
            ("separation_biens", "Séparation de biens"),
            ("autre", "Autre"),
        ],
        string="Régime matrimonial",
        required=True,
    )
    officier_etat_civil = fields.Char(string="Officier de l'État Civil")
    mention_ids = fields.One2many(
        "etat.civil.mention.marginale",
        "acte_mariage_id",
        string="Mentions marginales",
    )
    notification_mention_ids = fields.One2many(
        "etat.civil.mention.marginale",
        "source_acte_mariage_id",
        string="Notifications aux communes de naissance",
    )
    piece_ids = fields.One2many(
        "etat.civil.piece.justificative",
        "acte_mariage_id",
        string="Documents à vérifier",
    )
    def _required_piece_codes(self):
        self.ensure_one()
        required = set()
        if not self.donnees_historiques_incompletes:
            required.update({"cin_temoin_1", "cin_temoin_2"})
        else:
            if self.temoin_1_id:
                required.add("cin_temoin_1")
            if self.temoin_2_id:
                required.add("cin_temoin_2")
        for spouse_number in (1, 2):
            if getattr(self, f"conjoint_{spouse_number}_est_etranger"):
                required.add(f"passeport_{spouse_number}")
                if getattr(self, f"conjoint_{spouse_number}_capacite_requise"):
                    required.add(f"capacite_mariage_{spouse_number}")
                if getattr(
                    self, f"conjoint_{spouse_number}_residence_etranger_requise"
                ):
                    required.add(f"residence_etranger_{spouse_number}")
            else:
                required.update(
                    {
                        f"celibat_conjoint_{spouse_number}",
                        f"cin_conjoint_{spouse_number}",
                        f"residence_conjoint_{spouse_number}",
                    }
                )
        return required

    def _check_specific_transmission_requirements(self):
        self.ensure_one()
        errors = []
        if not self.conjoint_1_id:
            errors.append("Le premier conjoint doit être renseigné.")
        if not self.conjoint_2_id:
            errors.append("Le second conjoint doit être renseigné.")
        if not self.donnees_historiques_incompletes:
            if not self.temoin_1_id:
                errors.append("Le premier témoin doit être renseigné.")
            if not self.temoin_2_id:
                errors.append("Le second témoin doit être renseigné.")
        if not self.date_mariage:
            errors.append("La date du mariage est obligatoire.")
        if not (self.lieu_mariage or "").strip():
            errors.append("Le lieu du mariage est obligatoire.")
        return errors

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_pieces_justificatives()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {
            "conjoint_1_est_etranger",
            "conjoint_2_est_etranger",
            "conjoint_1_capacite_requise",
            "conjoint_2_capacite_requise",
            "conjoint_1_residence_etranger_requise",
            "conjoint_2_residence_etranger_requise",
        } & vals.keys():
            self._sync_pieces_justificatives()
        return result

    @api.constrains(
        "registre_id",
        "conjoint_1_id",
        "conjoint_2_id",
        "temoin_1_id",
        "temoin_2_id",
        "date_mariage",
    )
    def _check_acte_mariage(self):
        today = fields.Date.context_today(self)
        for record in self:
            if not record.registre_id or record.registre_id.type_registre != "mariage":
                raise ValidationError("L'acte doit être rattaché à un registre de mariage.")
            if record.conjoint_1_id == record.conjoint_2_id:
                raise ValidationError("Les deux conjoints doivent être des personnes différentes.")
            if not record.donnees_historiques_incompletes and record.statut not in ("brouillon", "a_corriger"):
                if not record.temoin_1_id or not record.temoin_2_id:
                    raise ValidationError("Les deux témoins doivent être renseignés pour cet acte.")
            if record.temoin_1_id and record.temoin_1_id in (record.conjoint_1_id, record.conjoint_2_id):
                raise ValidationError("Un conjoint ne peut pas être son propre témoin.")
            if record.temoin_2_id and (
                record.temoin_2_id in (record.conjoint_1_id, record.conjoint_2_id)
                or (record.temoin_1_id and record.temoin_2_id == record.temoin_1_id)
            ):
                raise ValidationError("Les témoins et les conjoints doivent être distincts.")
            if record.conjoint_1_id.statut_vital == "decede":
                raise ValidationError(
                    f"Le premier conjoint ({record.conjoint_1_id.nom_complet}) est enregistré comme décédé."
                )
            if record.conjoint_2_id.statut_vital == "decede":
                raise ValidationError(
                    f"Le second conjoint ({record.conjoint_2_id.nom_complet}) est enregistré comme décédé."
                )
            if record.conjoint_1_id.situation_matrimoniale == "marie":
                raise ValidationError(
                    f"Le premier conjoint ({record.conjoint_1_id.nom_complet}) est déjà marié."
                )
            if record.conjoint_2_id.situation_matrimoniale == "marie":
                raise ValidationError(
                    f"Le second conjoint ({record.conjoint_2_id.nom_complet}) est déjà marié."
                )
            if record.date_mariage and record.date_mariage > today:
                raise ValidationError("La date du mariage ne peut pas être dans le futur.")
            for conjoint, label in (
                (record.conjoint_1_id, "premier"),
                (record.conjoint_2_id, "second"),
            ):
                if conjoint.date_naissance and record.date_mariage and record.date_mariage < conjoint.date_naissance:
                    raise ValidationError(
                        f"La date du mariage ne peut pas précéder la naissance du {label} conjoint."
                    )

    def action_valider_acte(self):
        for record in self:
            for number, spouse in (
                (1, record.conjoint_1_id),
                (2, record.conjoint_2_id),
            ):
                birth_act = self.env["etat.civil.acte.naissance"].search(
                    [("enfant_id", "=", spouse.id)], limit=1
                )
                same_municipality = bool(
                    birth_act
                    and birth_act.registre_id.centre_id == record.registre_id.centre_id
                )
                mention = self.env["etat.civil.mention.marginale"].create({
                    "name": f"MARIAGE-{record.numero_acte}-{number}",
                    "type_mention": "mariage",
                    "date_mention": record.date_mariage,
                    "contenu": (
                        f"Mariage de {spouse.nom_complet} célébré le "
                        f"{record.date_mariage}."
                    ),
                    "personne_concernee_id": spouse.id,
                    "source_acte_mariage_id": record.id,
                    "acte_naissance_id": birth_act.id if same_municipality else False,
                    "individu_id": False if same_municipality else spouse.id,
                    "notification_commune_naissance": (
                        "inscrite" if same_municipality else "a_faire"
                    ),
                    "commune_naissance": spouse.lieu_naissance_commune or False,
                    "statut": "valide" if same_municipality else "brouillon",
                })
        res = super().action_valider_acte()
        for record in self:
            for spouse in (record.conjoint_1_id, record.conjoint_2_id):
                spouse.situation_matrimoniale = "marie"
        return res