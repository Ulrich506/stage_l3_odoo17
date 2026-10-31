from odoo import api, fields, models
from odoo.exceptions import ValidationError

class EtatCivilActeNaissance(models.Model):
    _name = 'etat.civil.acte.naissance'
    _inherit = 'etat.civil.acte.officiel'
    _description = 'Acte de Naissance'

    # Enfant sujet de l'acte
    enfant_id = fields.Many2one('etat.civil.individu', string='Enfant Nouveau-né', required=True)
    
    # Heure et lieu précis
    heure_naissance = fields.Float(string='Heure de naissance (ex: 14.5 = 14h30)')
    lieu_naissance = fields.Char(string='Lieu exact de la naissance')
    lieu_accouchement = fields.Selection(
        [('hopital', 'À l’hôpital'), ('maison', 'À la maison'), ('autre', 'Autre lieu')],
        string='Lieu de l’accouchement',
        required=True,
        default='hopital',
    )
    lieu_accouchement_autre = fields.Char(string='Préciser le lieu d’accouchement')
    filiation = fields.Selection(
        [
            ('legitime', 'Filiation établie'),
            ('illegitime', 'Filiation à préciser'),
        ],
        string='Situation de filiation',
        required=True,
        default='legitime',
    )
    date_declaration_commune = fields.Date(
        string='Date de déclaration à la commune',
        help='Le délai d’une ou deux semaines est indicatif et n’est pas obligatoire.',
    )
    declarant_id = fields.Many2one(
        'etat.civil.individu', string='Personne ayant déclaré la naissance'
    )
    
    # Parents
    pere_id = fields.Many2one('etat.civil.individu', string='Père')
    mere_id = fields.Many2one('etat.civil.individu', string='Mère', required=True)
    
    # Informations complémentaires
    est_jumeau = fields.Boolean(string='Est un jumeau', default=False)
    rang_naissance = fields.Integer(string='Rang de naissance dans la fratrie', default=1)
    certificat_medical_ref = fields.Char(string='Référence du certificat médical d\'accouchement')
    mention_ids = fields.One2many('etat.civil.mention.marginale', 'acte_naissance_id', string='Mentions marginales')
    piece_ids = fields.One2many(
        'etat.civil.piece.justificative',
        'acte_naissance_id',
        string='Pièces justificatives',
    )

    # Champ de confort : affiche la date de naissance de l'enfant sans dupliquer la donnée.
    date_naissance_enfant = fields.Date(
        string='Date de naissance (enfant)',
        related='enfant_id.date_naissance',
        store=False,
    )

    # Identification distincte des parents et déclarant
    cin_pere = fields.Char(
        string="CIN du père",
        related='pere_id.cin',
        store=False,
        readonly=True,
    )
    cin_mere = fields.Char(
        string="CIN de la mère",
        related='mere_id.cin',
        store=False,
        readonly=True,
    )
    cin_declarant = fields.Char(
        string="CIN du déclarant",
        related='declarant_id.cin',
        store=False,
        readonly=True,
    )

    _sql_constraints = [
        ('enfant_unique', 'unique(enfant_id)', "Un acte de naissance existe déjà pour cet individu."),
    ]

    def _required_piece_codes(self):
        self.ensure_one()
        required = set()
        if self.lieu_accouchement == 'hopital':
            required.add('declaration_hopital')
        if self.filiation == 'legitime':
            required.update({'livret_famille', 'residence_parent'})
        elif self.filiation == 'illegitime':
            required.add('cin_parent')
        return required

    def _check_specific_transmission_requirements(self):
        self.ensure_one()
        errors = []
        if not self.enfant_id:
            errors.append("L'enfant sujet de l'acte de naissance doit être renseigné.")
        if not self.mere_id:
            errors.append("La mère de l'enfant doit être renseignée.")
        if self.lieu_accouchement == 'maison' and not self.declarant_id:
            errors.append("Pour une naissance à domicile, le déclarant de la naissance est obligatoire.")
        if self.lieu_accouchement == 'autre' and not (self.lieu_accouchement_autre or '').strip():
            errors.append("Précisez le lieu d'accouchement lorsque le lieu n'est ni l'hôpital ni la maison.")
        if not (self.lieu_naissance or "").strip():
            errors.append("Le lieu exact de naissance doit être renseigné.")
        return errors

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._sync_pieces_justificatives()
        return records

    def write(self, vals):
        result = super().write(vals)
        if {'lieu_accouchement', 'filiation'} & vals.keys():
            self._sync_pieces_justificatives()
        return result

    @api.constrains('registre_id', 'enfant_id', 'pere_id', 'mere_id', 'heure_naissance', 'rang_naissance')
    def _check_acte_naissance(self):
        for record in self:
            if record.registre_id.type_registre != 'naissance':
                raise ValidationError("L'acte doit être rattaché à un registre de naissance.")
            if record.enfant_id:
                if record.enfant_id == record.pere_id or record.enfant_id == record.mere_id:
                    raise ValidationError("L'enfant ne peut pas être désigné comme son propre parent.")
                if record.enfant_id.sexe not in (False, 'M', 'F'):
                    raise ValidationError("Le sexe de l'enfant n'est pas valide.")
            if record.pere_id and record.mere_id and record.pere_id == record.mere_id:
                raise ValidationError("Le père et la mère doivent être deux personnes distinctes.")
            if record.pere_id and record.pere_id.sexe != 'M':
                raise ValidationError("La personne désignée comme père doit être de sexe masculin.")
            if record.mere_id and record.mere_id.sexe != 'F':
                raise ValidationError("La personne désignée comme mère doit être de sexe féminin.")
            if record.heure_naissance is not False and not 0 <= record.heure_naissance < 24:
                raise ValidationError("L'heure de naissance doit être comprise entre 0 et 24 heures.")
            if (record.rang_naissance or 0) < 1:
                raise ValidationError('Le rang de naissance doit être supérieur à zéro.')
            if record.lieu_accouchement == 'maison' and not record.declarant_id:
                raise ValidationError(
                    "Pour une naissance à la maison, indiquez la personne qui déclare la naissance."
                )
            if record.lieu_accouchement == 'autre' and not (record.lieu_accouchement_autre or '').strip():
                raise ValidationError("Précisez le lieu d'accouchement lorsque le lieu n'est ni l'hôpital ni la maison.")