from dateutil.relativedelta import relativedelta

from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


class EtatCivilMentionMarginale(models.Model):
    _name = 'etat.civil.mention.marginale'
    _description = 'Mention marginale d’état civil'
    _order = 'date_mention desc, id desc'

    name = fields.Char(string='Référence', required=True, readonly=True)
    type_mention = fields.Selection([
        ('mariage', 'Mariage'),
        ('divorce', 'Divorce'),
        ('deces', 'Décès'),
        ('reconnaissance', 'Reconnaissance de paternité'),
        ('adoption', 'Adoption simple (communale)'),
        ('veuvage', 'Veuvage'),
        ('rectification', 'Rectification'),
        ('changement_nom', 'Changement de nom'),
        ('autre', 'Autre'),
    ], string='Type de mention', required=True)
    date_mention = fields.Date(string='Date de la mention', required=True, default=fields.Date.context_today)
    contenu = fields.Text(string='Contenu de la mention', required=True)
    autorite = fields.Char(string='Autorité ayant apposé la mention')
    statut = fields.Selection(
        [('brouillon', 'À compléter'), ('valide', 'Validée')],
        string='État de la mention',
        default='brouillon',
        required=True,
    )
    personne_concernee_id = fields.Many2one(
        'etat.civil.individu',
        string='Personne concernée',
        index=True,
    )
    pere_reconnaissant_id = fields.Many2one(
        'etat.civil.individu', string='Père qui reconnaît l’enfant'
    )
    adoptant_id = fields.Many2one(
        'etat.civil.individu', string='Parent adoptant'
    )
    source_approbation_adoption = fields.Selection(
        [('famille', 'Famille de l’enfant'), ('fokontany', 'Chef fokontany')],
        string='Origine de la lettre d’accord',
    )
    commune_naissance = fields.Char(
        string='Commune de naissance à notifier',
        help='Commune où se trouve la copie de naissance à mettre à jour.',
    )
    notification_commune_naissance = fields.Selection(
        [
            ('a_faire', 'Notification à faire'),
            ('envoyee', 'Courrier envoyé'),
            ('inscrite', 'Mention inscrite sur la copie de naissance'),
        ],
        string='Notification à la commune de naissance',
        default='a_faire',
        required=True,
    )
    reference_notification = fields.Char(string='Référence du courrier de notification')
    acte_naissance_id = fields.Many2one('etat.civil.acte.naissance', string='Acte de naissance', ondelete='cascade')
    acte_mariage_id = fields.Many2one('etat.civil.acte.mariage', string='Acte de mariage', ondelete='cascade')
    acte_deces_id = fields.Many2one('etat.civil.acte.deces', string='Acte de décès', ondelete='cascade')
    source_acte_mariage_id = fields.Many2one(
        'etat.civil.acte.mariage', string='Acte de mariage à l’origine'
    )
    source_acte_deces_id = fields.Many2one(
        'etat.civil.acte.deces', string='Acte de décès à l’origine'
    )
    individu_id = fields.Many2one(
        'etat.civil.individu',
        string='Copie de naissance à notifier',
        ondelete='cascade',
        index=True,
    )
    piece_ids = fields.One2many(
        'etat.civil.piece.justificative', 'mention_id', string='Documents à vérifier'
    )

    @api.model_create_multi
    def create(self, vals_list):
        self._ensure_officier()
        sequence_by_type = {
            'mariage': 'etat.civil.mention.mariage',
            'divorce': 'etat.civil.mention.divorce',
            'deces': 'etat.civil.mention.deces',
            'reconnaissance': 'etat.civil.mention.reconnaissance',
            'adoption': 'etat.civil.mention.adoption',
            'veuvage': 'etat.civil.mention.veuvage',
            'rectification': 'etat.civil.mention.rectification',
            'changement_nom': 'etat.civil.mention.changement_nom',
            'autre': 'etat.civil.mention.autre',
        }
        for vals in vals_list:
            if not (vals.get('name') or '').strip():
                sequence_code = sequence_by_type.get(
                    vals.get('type_mention'),
                    'etat.civil.mention.autre',
                )
                sequence = self.env['ir.sequence'].sudo()
                reference = sequence.next_by_code(sequence_code)
                while reference and self.sudo().search_count([('name', '=', reference)]):
                    reference = sequence.next_by_code(sequence_code)
                if not reference:
                    raise ValidationError("La séquence de référence de cette mention n'est pas configurée.")
                vals['name'] = reference
        birth_model = self.env['etat.civil.acte.naissance']
        for vals in vals_list:
            if vals.get('personne_concernee_id') and not any(
                vals.get(field_name)
                for field_name in (
                    'acte_naissance_id',
                    'acte_mariage_id',
                    'acte_deces_id',
                    'individu_id',
                )
            ):
                birth_act = birth_model.search(
                    [('enfant_id', '=', vals['personne_concernee_id'])], limit=1
                )
                if birth_act:
                    vals['acte_naissance_id'] = birth_act.id
                else:
                    vals['individu_id'] = vals['personne_concernee_id']
            elif vals.get('acte_naissance_id') and not vals.get('personne_concernee_id'):
                birth_act = birth_model.browse(vals['acte_naissance_id'])
                vals['personne_concernee_id'] = birth_act.enfant_id.id
            if vals.get('personne_concernee_id') and not vals.get('commune_naissance'):
                person = self.env['etat.civil.individu'].browse(
                    vals['personne_concernee_id']
                )
                vals['commune_naissance'] = person.lieu_naissance_commune
        records = super().create(vals_list)
        records._sync_pieces_justificatives()
        return records

    def _ensure_officier(self):
        if not (
            self.env.user.has_group('etat_civil.group_etat_civil_officier')
            or self.env.user.has_group('base.group_system')
        ):
            raise AccessError("Seul un officier d'état civil peut gérer les mentions marginales.")

    def _pieces_owner_field(self):
        return 'mention_id'

    def _sync_pieces_justificatives(self):
        for record in self:
            required = record._required_piece_codes()
            existing = {piece.name: piece for piece in record.piece_ids}
            for code, piece in existing.items():
                piece.with_context(etat_civil_sync_required=True).write({
                    'obligatoire': code in required,
                })
            missing = required - existing.keys()
            if missing:
                self.env['etat.civil.piece.justificative'].create([
                    {'name': code, 'obligatoire': True, 'mention_id': record.id}
                    for code in sorted(missing)
                ])

    def _check_pieces_justificatives(self):
        self.ensure_one()
        missing = self.piece_ids.filtered(
            lambda piece: piece.obligatoire and piece.etat != 'verifie'
        )
        if missing:
            names = ', '.join(missing.mapped('display_name'))
            raise ValidationError(
                "Les pièces obligatoires doivent être reçues et vérifiées : %s."
                % names
            )

    def action_valider_mention(self):
        self._ensure_officier()
        for record in self:
            if record.statut != 'brouillon':
                raise ValidationError("Seule une mention à compléter peut être validée.")
            record._sync_pieces_justificatives()
            record._check_pieces_justificatives()
            if record.type_mention == 'reconnaissance' and not record.pere_reconnaissant_id:
                raise ValidationError("Sélectionnez le père qui reconnaît l’enfant.")
            if record.type_mention in ('reconnaissance', 'adoption') and not record.personne_concernee_id:
                raise ValidationError("Sélectionnez l’enfant concerné par cette mention.")
            if record.type_mention == 'adoption':
                if not record.adoptant_id:
                    raise ValidationError("Sélectionnez le parent adoptant.")
                if not record.source_approbation_adoption:
                    raise ValidationError(
                        "Indiquez si la lettre d’accord vient de la famille ou du fokontany."
                    )
            record.statut = 'valide'
            if record.personne_concernee_id:
                if record.type_mention == 'mariage':
                    record.personne_concernee_id.situation_matrimoniale = 'marie'
                elif record.type_mention == 'divorce':
                    record.personne_concernee_id.situation_matrimoniale = 'divorce'
                elif record.type_mention == 'veuvage':
                    record.personne_concernee_id.situation_matrimoniale = 'veuf'
        return True

    def write(self, vals):
        self._ensure_officier()
        protected = {
            'type_mention',
            'date_mention',
            'contenu',
            'personne_concernee_id',
            'personne_concernee_id',
            'pere_reconnaissant_id',
            'adoptant_id',
            'source_approbation_adoption',
            'acte_naissance_id',
            'acte_mariage_id',
            'acte_deces_id',
            'individu_id',
        }
        if protected.intersection(vals) and any(record.statut == 'valide' for record in self):
            raise ValidationError("Une mention validée ne peut plus être modifiée.")
        result = super().write(vals)
        if protected.intersection(vals):
            self._sync_pieces_justificatives()
        return result

    def unlink(self):
        self._ensure_officier()
        return super().unlink()

    @api.constrains(
        'personne_concernee_id',
        'acte_naissance_id',
        'acte_mariage_id',
        'acte_deces_id',
        'individu_id',
        'contenu',
    )
    def _check_target_and_content(self):
        for record in self:
            targets = sum(bool(value) for value in (
                record.acte_naissance_id,
                record.acte_mariage_id,
                record.acte_deces_id,
                record.individu_id,
            ))
            if targets != 1:
                raise ValidationError('Une mention doit être liée à un seul acte.')
            if not record.contenu or not record.contenu.strip():
                raise ValidationError('Le contenu de la mention ne peut pas être vide.')

    def _required_piece_codes(self):
        self.ensure_one()
        if self.type_mention == 'reconnaissance' and self.personne_concernee_id:
            birth_date = self.personne_concernee_id.date_naissance
            if not birth_date:
                raise ValidationError(
                    "La date de naissance est requise pour déterminer si l’enfant est majeur."
                )
            majority_date = birth_date + relativedelta(years=18)
            if self.date_mention < majority_date:
                return {
                    'cin_pere_reconnaissant',
                    'residence_pere_reconnaissant',
                    'lettre_fokontany_reconnaissance',
                }
            return {'cin_enfant_majeur', 'residence_enfant_majeur'}
        if self.type_mention == 'adoption':
            required = {'cin_adoptant', 'residence_adoptant'}
            if self.source_approbation_adoption == 'famille':
                required.add('lettre_accord_famille')
            elif self.source_approbation_adoption == 'fokontany':
                required.add('lettre_fokontany_adoption')
            return required
        return set()