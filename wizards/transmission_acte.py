from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError


class EtatCivilTransmissionActeWizard(models.TransientModel):
    _name = "etat.civil.transmission.acte.wizard"
    _description = "Transmission d'un acte à un officier d'état civil"

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
    centre_id = fields.Many2one("etat.civil.centre", string="Centre d'état civil", readonly=True)
    officier_id = fields.Many2one(
        "res.users",
        string="Officier d'état civil compétent",
        required=True,
        domain="[('id', 'in', available_officier_ids)]",
    )
    available_officier_ids = fields.Many2many(
        "res.users",
        compute="_compute_available_officiers",
        string="Officiers disponibles",
    )
    notes = fields.Text(string="Note ou message pour l'officier (facultatif)")

    @api.depends("centre_id")
    def _compute_available_officiers(self):
        officier_group = self.env.ref("etat_civil.group_etat_civil_officier")
        base_officiers = self.env["res.users"].sudo().search([
            ("groups_id", "in", officier_group.id),
            ("active", "=", True),
            ("share", "=", False),
        ])
        for wizard in self:
            if wizard.centre_id:
                competent = base_officiers.filtered(
                    lambda user: wizard.centre_id in user.etat_civil_centre_ids
                )
            else:
                competent = self.env["res.users"]
            wizard.available_officier_ids = competent

    def action_confirmer_transmission(self):
        self.ensure_one()
        if not self.officier_id:
            raise ValidationError("Veuillez sélectionner un officier compétent.")

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
        return acte.action_envoyer_validation(officier=self.officier_id, notes=self.notes)
