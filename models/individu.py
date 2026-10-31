import re
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import ValidationError

class EtatCivilIndividu(models.Model):
    _name = 'etat.civil.individu'
    _description = 'Individu / Citoyen'
    _rec_name = 'nom_complet'

    cin = fields.Char(
        string='Carte d\'Identité Nationale (CIN)',
        index=True,
        help="Numéro de la Carte d'Identité Nationale : exactement 12 chiffres.",
    )
    nom = fields.Char(string='Nom', required=True)
    prenoms = fields.Char(string='Prénoms')
    nom_complet = fields.Char(string='Nom Complet', compute='_compute_nom_complet', store=True)
    
    sexe = fields.Selection([
        ('M', 'Masculin'),
        ('F', 'Féminin')
    ], string='Sexe', required=True)
    
    date_naissance = fields.Date(string='Date de naissance', required=True)
    cin_non_requise = fields.Boolean(
        string='CIN non requise',
        compute='_compute_cin_non_requise',
    )
    date_naissance_estimee = fields.Boolean(string='Date estimée', default=False)
    lieu_naissance_commune = fields.Char(
        string='Commune de naissance',
        default='Fianarantsoa',
    )
    lieu_naissance_pays = fields.Char(string='Pays de naissance', default='Madagascar')
    
    profession_actuelle = fields.Char(string='Profession')
    domicile_actuel = fields.Text(string='Domicile')
    nationalite_actuelle = fields.Char(string='Nationalité', default='Malagasy')
    
    statut_vital = fields.Selection([
        ('vivant', 'Vivant'),
        ('decede', 'Décédé'),
        ('disparu', 'Présumé Disparu')
    ], string='Statut vital', default='vivant', required=True)
    
    situation_matrimoniale = fields.Selection([
        ('celibataire', 'Célibataire'),
        ('marie', 'Marié(e)'),
        ('divorce', 'Divorcé(e)'),
        ('veuf', 'Veuf/Veuve')
    ], string='Situation matrimoniale', default='celibataire', required=True)

    _sql_constraints = [
        ('cin_unique', 'unique(cin)', 'Le numéro de CIN doit être unique.'),
        (
            'cin_format',
            "CHECK(cin IS NULL OR cin = '' OR cin ~ '^[0-9]{12}$')",
            'Le numéro de CIN doit contenir exactement 12 chiffres.',
        ),
    ]

    @api.constrains('date_naissance')
    def _check_date_naissance(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.date_naissance and record.date_naissance > today:
                raise ValidationError("La date de naissance ne peut pas être dans le futur.")

    @api.depends('date_naissance')
    def _compute_cin_non_requise(self):
        for record in self:
            today = fields.Date.context_today(record)
            record.cin_non_requise = bool(
                record.date_naissance
                and record.date_naissance > today - relativedelta(years=18)
            )

    @api.constrains('cin')
    def _check_cin_format(self):
        for record in self:
            if record.cin and not re.fullmatch(r'[0-9]{12}', record.cin):
                raise ValidationError('Le numéro de CIN doit contenir exactement 12 chiffres.')

    @api.model
    def _default_cin_for_newborn(self):
        return False

    @staticmethod
    def _normalize_cin(value):
        if not isinstance(value, str):
            return value
        value = value.strip() or False
        if value and not re.fullmatch(r'[0-9]{12}', value):
            raise ValidationError('Le numéro de CIN doit contenir exactement 12 chiffres.')
        return value

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            legacy_cin = vals.pop('nin', None)
            if legacy_cin is not None:
                if vals.get('cin') not in (None, legacy_cin):
                    raise ValidationError("Les valeurs CIN reçues ne correspondent pas.")
                vals['cin'] = legacy_cin
            if 'cin' in vals and vals['cin'] not in (None, ''):
                vals['cin'] = self._normalize_cin(vals['cin'])
        return super().create(vals_list)

    def write(self, vals):
        legacy_cin = vals.pop('nin', None)
        if legacy_cin is not None:
            if vals.get('cin') not in (None, legacy_cin):
                raise ValidationError("Les valeurs CIN reçues ne correspondent pas.")
            vals['cin'] = legacy_cin
        if 'cin' in vals and vals['cin'] not in (None, ''):
            vals['cin'] = self._normalize_cin(vals['cin'])
        return super().write(vals)

    @api.depends('nom', 'prenoms')
    def _compute_nom_complet(self):
        for rec in self:
            rec.nom_complet = f"{rec.nom or ''} {rec.prenoms or ''}".strip()