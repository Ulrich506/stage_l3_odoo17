from odoo import fields, models
from odoo.exceptions import UserError


class EtatCivilAnnulationActeWizard(models.TransientModel):
    _name = 'etat.civil.annulation.acte.wizard'
    _description = 'Annulation d\'un acte d\'état civil'

    acte_type = fields.Selection(
        selection=[
            ('naissance', 'Acte de naissance'),
            ('mariage', 'Acte de mariage'),
            ('deces', 'Acte de décès'),
        ],
        required=True,
        readonly=True,
    )
    acte_id = fields.Integer(required=True, readonly=True)
    acte_display = fields.Char(string='Acte', readonly=True)
    motif = fields.Text(string='Motif d\'annulation', required=True)

    def action_confirmer(self):
        self.ensure_one()
        if not self.motif or not self.motif.strip():
            raise UserError("Le motif d'annulation est obligatoire.")
        models_by_type = {
            'naissance': 'etat.civil.acte.naissance',
            'mariage': 'etat.civil.acte.mariage',
            'deces': 'etat.civil.acte.deces',
        }
        model = self.env[models_by_type[self.acte_type]]
        acte = model.browse(self.acte_id).exists()
        if not acte:
            raise UserError("L'acte demandé n'existe plus.")
        acte.action_annuler_acte(self.motif)
        return {'type': 'ir.actions.act_window_close'}
