from odoo import fields, models
from odoo.exceptions import UserError, ValidationError


class EtatCivilRetourCorrectionWizard(models.TransientModel):
    _name = "etat.civil.retour.correction.wizard"
    _description = "Retour pour correction ou refus d'un acte"

    action_type = fields.Selection(
        selection=[
            ("correction", "Retourner le dossier pour correction à l'agent"),
            ("refus", "Refuser définitivement le dossier"),
        ],
        string="Décision",
        required=True,
        default="correction",
    )
    acte_type = fields.Selection(
        selection=[
            ("naissance", "Acte de naissance"),
            ("mariage", "Acte de mariage"),
            ("deces", "Acte de décès"),
        ],
        required=True,
        readonly=True,
    )
    acte_id = fields.Integer(required=True, readonly=True)
    acte_display = fields.Char(string="Dossier / Acte", readonly=True)
    motif = fields.Text(string="Motif explicite", required=True)

    def action_confirmer(self):
        self.ensure_one()
        motif = (self.motif or "").strip()
        if not motif:
            raise ValidationError("Le motif explicite est obligatoire.")

        models_by_type = {
            "naissance": "etat.civil.acte.naissance",
            "mariage": "etat.civil.acte.mariage",
            "deces": "etat.civil.acte.deces",
        }
        model_name = models_by_type.get(self.acte_type)
        if not model_name:
            raise UserError("Type d'acte invalide.")

        acte = self.env[model_name].browse(self.acte_id).exists()
        if not acte:
            raise UserError("Le dossier demandé est introuvable ou a été supprimé.")
        acte.check_access_rights("read")
        acte.check_access_rule("read")

        if self.action_type == "correction":
            return acte.action_retourner_correction(motif)
        else:
            return acte.action_refuser_acte(motif)
