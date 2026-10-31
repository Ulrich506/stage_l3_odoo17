from odoo import fields, models


class ResUsers(models.Model):
    _inherit = "res.users"

    etat_civil_centre_ids = fields.Many2many(
        "etat.civil.centre",
        "etat_civil_user_centre_rel",
        "user_id",
        "centre_id",
        string="Centres d'état civil autorisés",
        help=(
            "Centres auxquels cet utilisateur est affecté pour les opérations "
            "d'état civil. Les agents et officiers ne peuvent travailler que "
            "dans les centres de leur périmètre."
        ),
    )
