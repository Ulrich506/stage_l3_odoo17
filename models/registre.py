from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EtatCivilCentre(models.Model):
    _name = 'etat.civil.centre'
    _description = "Centre d'État Civil / Mairie"
    _rec_name = 'nom_centre'

    code_centre = fields.Char(string='Code Centre', required=True)
    nom_centre = fields.Char(string='Nom du Centre', required=True)
    commune = fields.Char(string='Commune', required=True)
    district_province = fields.Char(string='District / Région')
    pays = fields.Char(string='Pays', default='Madagascar')

    _sql_constraints = [
        ('code_centre_unique', 'unique(code_centre)', 'Le code du centre doit être unique.'),
    ]


class EtatCivilRegistre(models.Model):
    _name = 'etat.civil.registre'
    _description = 'Registre Annuel des Actes'
    _rec_name = 'designation'

    annee = fields.Integer(string='Année', required=True, default=lambda self: fields.Date.context_today(self).year)
    type_registre = fields.Selection([
        ('naissance', 'Naissance'),
        ('mariage', 'Mariage'),
        ('deces', 'Décès')
    ], string='Type de Registre', required=True)

    numero_volume = fields.Integer(string='Volume N°', default=1, required=True)
    centre_id = fields.Many2one('etat.civil.centre', string="Centre d'État Civil", required=True)
    est_cloture = fields.Boolean(string='Clôturé', default=False, readonly=True)

    date_ouverture = fields.Date(string="Date d'ouverture", default=fields.Date.context_today)
    date_cloture = fields.Date(string='Date de clôture')

    designation = fields.Char(string='Désignation', compute='_compute_designation', store=True)

    _sql_constraints = [
        (
            'registre_unique',
            'unique(annee, type_registre, numero_volume, centre_id)',
            'Un registre de même type, année, volume et centre existe déjà.',
        ),
    ]

    @api.depends('annee', 'type_registre', 'numero_volume')
    def _compute_designation(self):
        for rec in self:
            rec.designation = f"Registre {rec.type_registre or ''} - {rec.annee} (Vol. {rec.numero_volume})"

    @api.constrains('annee', 'numero_volume', 'date_ouverture', 'date_cloture', 'est_cloture')
    def _check_registre_dates(self):
        for record in self:
            if (record.annee or 0) < 1:
                raise ValidationError("L'année du registre doit être valide.")
            if (record.numero_volume or 0) < 1:
                raise ValidationError("Le numéro de volume doit être supérieur à zéro.")
            if record.date_cloture and record.date_ouverture and record.date_cloture < record.date_ouverture:
                raise ValidationError("La date de clôture ne peut pas précéder la date d'ouverture.")
            if record.est_cloture and not record.date_cloture:
                raise ValidationError("Un registre clôturé doit avoir une date de clôture.")

    def action_cloturer_registre(self):
        if not (
            self.env.user.has_group('etat_civil.group_etat_civil_admin')
            or self.env.user.has_group('base.group_system')
        ):
            raise ValidationError("Seul l'administrateur d'état civil peut clôturer un registre.")
        for record in self:
            if record.est_cloture:
                raise ValidationError("Ce registre est déjà clôturé.")
            record.write({
                'est_cloture': True,
                'date_cloture': record.date_cloture or fields.Date.context_today(self),
            })

    def action_rouvrir_registre(self):
        if not (
            self.env.user.has_group('etat_civil.group_etat_civil_admin')
            or self.env.user.has_group('base.group_system')
        ):
            raise ValidationError("Seul l'administrateur d'état civil peut rouvrir un registre.")
        for record in self:
            if not record.est_cloture:
                raise ValidationError("Ce registre n'est pas clôturé.")
            record.write({
                'est_cloture': False,
            })