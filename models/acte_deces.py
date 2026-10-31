from odoo import api, fields, models
from odoo.exceptions import ValidationError


class EtatCivilActeDeces(models.Model):
    _name = 'etat.civil.acte.deces'
    _inherit = 'etat.civil.acte.officiel'
    _description = 'Acte de Décès'

    defunt_id = fields.Many2one('etat.civil.individu', string='Défunt', required=True)
    date_deces = fields.Date(string='Date du décès', required=True, default=fields.Date.context_today)
    heure_deces = fields.Float(string='Heure du décès')
    lieu_deces = fields.Char(string='Lieu du décès', required=True)
    cause_deces = fields.Char(string='Cause du décès')
    officier_etat_civil = fields.Char(string="Officier de l'État Civil")
    declarant_id = fields.Many2one('etat.civil.individu', string='Déclarant')
    certificat_medical_ref = fields.Char(string='Référence du certificat médical')
    mention_ids = fields.One2many('etat.civil.mention.marginale', 'acte_deces_id', string='Mentions marginales')
    piece_ids = fields.One2many(
        'etat.civil.piece.justificative',
        'acte_deces_id',
        string='Documents à vérifier',
    )

    _sql_constraints = [
        ('defunt_unique', 'unique(defunt_id)', "Un acte de décès existe déjà pour cet individu."),
    ]

    def _required_piece_codes(self):
        return {'cin_declarant_deces', 'residence_declarant_deces'}

    def _check_specific_transmission_requirements(self):
        self.ensure_one()
        errors = []
        if not self.defunt_id:
            errors.append("Le défunt doit être renseigné.")
        if not self.declarant_id:
            errors.append("La personne ayant déclaré le décès est obligatoire.")
        if not self.date_deces:
            errors.append("La date du décès est obligatoire.")
        if not (self.lieu_deces or "").strip():
            errors.append("Le lieu du décès est obligatoire.")
        return errors

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_pieces_justificatives()
        return records

    @api.constrains('registre_id', 'defunt_id', 'declarant_id', 'date_deces', 'heure_deces')
    def _check_acte_deces(self):
        today = fields.Date.context_today(self)
        for record in self:
            if record.registre_id.type_registre != 'deces':
                raise ValidationError("L'acte doit être rattaché à un registre de décès.")
            if record.defunt_id and record.declarant_id and record.defunt_id == record.declarant_id:
                raise ValidationError("Le déclarant ne peut pas être le défunt lui-même.")
            if not record.declarant_id:
                raise ValidationError("Indiquez la personne qui déclare le décès.")
            if record.date_deces > today:
                raise ValidationError("La date du décès ne peut pas être dans le futur.")
            if record.defunt_id.date_naissance and record.date_deces < record.defunt_id.date_naissance:
                raise ValidationError("La date du décès ne peut pas précéder la date de naissance.")
            if record.heure_deces is not False and not 0 <= record.heure_deces < 24:
                raise ValidationError("L'heure du décès doit être comprise entre 0 et 24 heures.")

    def action_valider_acte(self):
        """Mise à jour automatique du statut vital du défunt après validation"""
        res = super().action_valider_acte()
        for record in self:
            if record.defunt_id:
                record.defunt_id.statut_vital = 'decede'
        return res