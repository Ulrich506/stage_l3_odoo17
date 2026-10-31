from odoo import fields, models


class EtatCivilExchangeLog(models.Model):
    _name = "etat.civil.exchange.log"
    _description = "Journal des importations et exportations de citoyens"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, readonly=True)
    operation = fields.Selection(
        [("import", "Importation"), ("export", "Exportation")],
        required=True,
        readonly=True,
    )
    state = fields.Selection(
        [
            ("success", "Terminé"),
            ("partial", "Terminé avec erreurs"),
            ("failed", "Échec"),
        ],
        required=True,
        readonly=True,
    )
    user_id = fields.Many2one("res.users", required=True, readonly=True)
    file_name = fields.Char(readonly=True)
    file_format = fields.Char(readonly=True)
    total_rows = fields.Integer(readonly=True)
    imported_rows = fields.Integer(readonly=True)
    updated_rows = fields.Integer(readonly=True)
    skipped_rows = fields.Integer(readonly=True)
    duplicate_rows = fields.Integer(readonly=True)
    error_rows = fields.Integer(readonly=True)
