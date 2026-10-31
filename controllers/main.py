import base64
import binascii
from datetime import date, datetime
import hashlib
import json
import logging
import re

from odoo import fields, http
from odoo.exceptions import AccessDenied, AccessError, UserError, ValidationError
from odoo.http import request


_logger = logging.getLogger(__name__)


class EtatCivilApiController(http.Controller):
    """HTTP JSON API for the civil-status application."""

    @http.route(
        '/api/v1/health',
        type='http',
        auth='none',
        methods=['GET'],
        csrf=False,
    )
    def health(self, **kwargs):
        return self._response({
            'status': 'ok',
            'service': 'etat_civil_api',
            'database': request.db or 'gestion_detat_civil',
        })

    @staticmethod
    def _response(payload, status=200):
        return request.make_json_response(payload, status=status)

    @staticmethod
    def _json_body():
        if request.httprequest.mimetype == 'application/json':
            payload = request.httprequest.get_json(silent=True)
        else:
            try:
                payload = json.loads(request.httprequest.get_data(as_text=True) or '{}')
            except json.JSONDecodeError as error:
                raise ValidationError('Le corps de la requête doit être un JSON valide.') from error
        if not isinstance(payload, dict):
            raise ValidationError('Le corps de la requête doit être un objet JSON.')
        return payload

    @staticmethod
    def _query_int(name, default, minimum, maximum):
        value = request.httprequest.args.get(name)
        if value is None:
            return default
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise ValidationError(f"Le paramètre {name} doit être un entier.")
        if not minimum <= value <= maximum:
            raise ValidationError(
                f"Le paramètre {name} doit être compris entre {minimum} et {maximum}."
            )
        return value

    @staticmethod
    def _serialize_value(value):
        if isinstance(value, (date, datetime)):
            return value.isoformat()
        return value

    @classmethod
    def _serialize_individu(cls, individu):
        if not individu:
            return None
        return {
            'id': individu.id,
            'nom_complet': individu.display_name,
            'cin': individu.cin,
            'nin': individu.cin,
            'nom': individu.nom,
            'prenoms': individu.prenoms,
            'sexe': individu.sexe,
            'date_naissance': cls._serialize_value(individu.date_naissance),
            'lieu_naissance_commune': individu.lieu_naissance_commune,
            'lieu_naissance_pays': individu.lieu_naissance_pays,
            'nationalite_actuelle': individu.nationalite_actuelle,
            'statut_vital': individu.statut_vital,
            'situation_matrimoniale': individu.situation_matrimoniale,
            'mentions_marginales': cls._serialize_personne_mentions(individu),
        }

    @classmethod
    def _serialize_acte_naissance(cls, acte):
        return {
            'id': acte.id,
            'type_acte': 'naissance',
            'numero_acte': acte.numero_acte,
            'feuillet_numero': acte.feuillet_numero,
            'registre_id': acte.registre_id.id,
            'registre': acte.registre_id.display_name,
            'statut': acte.statut,
            'date_dressage': cls._serialize_value(acte.date_dressage),
            'enfant': cls._serialize_individu(acte.enfant_id),
            'pere': cls._serialize_individu(acte.pere_id) if acte.pere_id else None,
            'mere': cls._serialize_individu(acte.mere_id) if acte.mere_id else None,
            'heure_naissance': acte.heure_naissance,
            'lieu_naissance': acte.lieu_naissance,
            'lieu_accouchement': acte.lieu_accouchement,
            'filiation': acte.filiation,
            'date_declaration_commune': cls._serialize_value(acte.date_declaration_commune),
            'declarant': cls._serialize_individu(acte.declarant_id) if acte.declarant_id else None,
            'est_jumeau': acte.est_jumeau,
            'rang_naissance': acte.rang_naissance,
            'certificat_medical_ref': acte.certificat_medical_ref,
            'texte_integral_acte': acte.texte_integral_acte,
            'hash_empreinte_num': acte.hash_empreinte_num,
            'qr_code_signature': acte.qr_code_signature,
            'mentions_marginales': [cls._serialize_mention(mention) for mention in acte.mention_ids],
            'pieces_justificatives': [cls._serialize_piece(piece) for piece in acte.piece_ids],
        }

    @classmethod
    def _serialize_acte_mariage(cls, acte):
        return {
            'id': acte.id,
            'type_acte': 'mariage',
            'numero_acte': acte.numero_acte,
            'feuillet_numero': acte.feuillet_numero,
            'registre_id': acte.registre_id.id,
            'registre': acte.registre_id.display_name,
            'statut': acte.statut,
            'date_dressage': cls._serialize_value(acte.date_dressage),
            'conjoint_1': cls._serialize_individu(acte.conjoint_1_id),
            'conjoint_2': cls._serialize_individu(acte.conjoint_2_id),
            'date_mariage': cls._serialize_value(acte.date_mariage),
            'lieu_mariage': acte.lieu_mariage,
            'regime_matrimonial': acte.regime_matrimonial,
            'conjoint_1_est_etranger': acte.conjoint_1_est_etranger,
            'conjoint_2_est_etranger': acte.conjoint_2_est_etranger,
            'temoin_1': cls._serialize_individu(acte.temoin_1_id),
            'temoin_2': cls._serialize_individu(acte.temoin_2_id),
            'notifications_naissance': [
                cls._serialize_mention(mention)
                for mention in acte.notification_mention_ids
            ],
            'officier_etat_civil': acte.officier_etat_civil,
            'texte_integral_acte': acte.texte_integral_acte,
            'hash_empreinte_num': acte.hash_empreinte_num,
            'qr_code_signature': acte.qr_code_signature,
            'mentions_marginales': [cls._serialize_mention(mention) for mention in acte.mention_ids],
            'pieces_justificatives': [cls._serialize_piece(piece) for piece in acte.piece_ids],
        }

    @classmethod
    def _serialize_acte_deces(cls, acte):
        return {
            'id': acte.id,
            'type_acte': 'deces',
            'numero_acte': acte.numero_acte,
            'feuillet_numero': acte.feuillet_numero,
            'registre_id': acte.registre_id.id,
            'registre': acte.registre_id.display_name,
            'statut': acte.statut,
            'date_dressage': cls._serialize_value(acte.date_dressage),
            'defunt': cls._serialize_individu(acte.defunt_id),
            'declarant': cls._serialize_individu(acte.declarant_id) if acte.declarant_id else None,
            'date_deces': cls._serialize_value(acte.date_deces),
            'heure_deces': acte.heure_deces,
            'lieu_deces': acte.lieu_deces,
            'cause_deces': acte.cause_deces,
            'certificat_medical_ref': acte.certificat_medical_ref,
            'texte_integral_acte': acte.texte_integral_acte,
            'hash_empreinte_num': acte.hash_empreinte_num,
            'qr_code_signature': acte.qr_code_signature,
            'mentions_marginales': [cls._serialize_mention(mention) for mention in acte.mention_ids],
            'pieces_justificatives': [cls._serialize_piece(piece) for piece in acte.piece_ids],
        }

    @staticmethod
    def _serialize_mention(mention):
        target = (
            mention.acte_naissance_id
            or mention.acte_mariage_id
            or mention.acte_deces_id
        )
        return {
            'id': mention.id,
            'reference': mention.name,
            'type': mention.type_mention,
            'date': mention.date_mention.isoformat() if mention.date_mention else None,
            'contenu': mention.contenu,
            'autorite': mention.autorite,
            'acte_id': target.id if target else None,
            'personne_id': mention.personne_concernee_id.id or mention.individu_id.id or None,
            'commune_naissance': mention.commune_naissance,
            'notification_commune_naissance': mention.notification_commune_naissance,
            'reference_notification': mention.reference_notification,
            'statut': mention.statut,
            'pieces_justificatives': [
                EtatCivilApiController._serialize_piece(piece)
                for piece in mention.piece_ids
            ],
        }

    @staticmethod
    def _serialize_personne_mentions(person):
        mentions = request.env['etat.civil.mention.marginale'].search([
            '|',
            '|',
            ('personne_concernee_id', '=', person.id),
            ('individu_id', '=', person.id),
            ('acte_naissance_id.enfant_id', '=', person.id),
        ])
        return [EtatCivilApiController._serialize_mention(item) for item in mentions]

    @staticmethod
    def _serialize_piece(piece):
        return {
            'id': piece.id,
            'code': piece.name,
            'nom': piece.display_name,
            'obligatoire': piece.obligatoire,
            'etat': piece.etat,
            'a_une_piece_jointe': bool(piece.attachment_ids),
        }

    @staticmethod
    def _apply_piece_updates(acte, pieces):
        if pieces is None:
            return
        if not isinstance(pieces, list):
            raise ValidationError('La liste des pièces justificatives est invalide.')
        owner_field = acte._pieces_owner_field()
        required = acte._required_piece_codes()
        updated_codes = set()
        for item in pieces:
            if not isinstance(item, dict):
                raise ValidationError('Chaque pièce doit être un objet JSON.')
            code = item.get('code')
            state = item.get('etat', 'recu')
            if code not in required:
                raise ValidationError('Cette pièce ne fait pas partie des justificatifs requis.')
            if code in updated_codes:
                raise ValidationError('Une pièce ne peut être transmise qu’une fois.')
            if state not in ('a_fournir', 'recu', 'verifie'):
                raise ValidationError('L’état de la pièce justificative est invalide.')
            updated_codes.add(code)
            piece = request.env['etat.civil.piece.justificative'].search(
                [(owner_field, '=', acte.id), ('name', '=', code)],
                limit=1,
            )
            if not piece:
                raise ValidationError('La pièce justificative demandée est introuvable.')
            piece.write({'etat': state})
            image_data = item.get('image_base64')
            if image_data:
                if not isinstance(image_data, str) or len(image_data) > 7_000_000:
                    raise ValidationError('La photo doit faire moins de 5 Mo.')
                try:
                    decoded = base64.b64decode(image_data, validate=True)
                except (binascii.Error, ValueError) as error:
                    raise ValidationError('Le contenu de la photo est invalide.') from error
                if len(decoded) > 5 * 1024 * 1024:
                    raise ValidationError('La photo doit faire moins de 5 Mo.')
                mime_type = item.get('image_mimetype') or 'image/jpeg'
                if mime_type not in ('image/jpeg', 'image/png', 'image/webp'):
                    raise ValidationError('Format photo non pris en charge.')
                attachment = request.env['ir.attachment'].create({
                    'name': item.get('image_name') or f'{code}.jpg',
                    'datas': image_data,
                    'mimetype': mime_type,
                    'res_model': 'etat.civil.piece.justificative',
                    'res_id': piece.id,
                })
                piece.write({'attachment_ids': [(4, attachment.id)]})

    @staticmethod
    def _create_marginal_mention_from_payload(
        payload, target_field=None, target_id=None
    ):
        if not isinstance(payload, dict):
            raise ValidationError('Les données de la mention sont invalides.')
        person_id = payload.get('personne_id')
        person = (
            request.env['etat.civil.individu'].browse(person_id).exists()
            if person_id
            else request.env['etat.civil.individu']
        )
        if person_id and not person:
            raise ValidationError('La personne concernée est introuvable.')
        birth_act = (
            request.env['etat.civil.acte.naissance'].search(
                [('enfant_id', '=', person.id)], limit=1
            )
            if person and not target_field
            else request.env['etat.civil.acte.naissance']
        )
        values = {
            'name': payload.get('reference') or payload.get('name'),
            'type_mention': payload.get('type') or payload.get('type_mention'),
            'date_mention': payload.get('date')
            or payload.get('date_mention')
            or fields.Date.context_today(request.env['etat.civil.mention.marginale']),
            'contenu': payload.get('contenu'),
            'autorite': payload.get('autorite'),
            'personne_concernee_id': person.id if person else False,
            'commune_naissance': person.lieu_naissance_commune if person else False,
            'acte_naissance_id': birth_act.id if birth_act else False,
            'individu_id': person.id if person and not birth_act else False,
            'pere_reconnaissant_id': payload.get('pere_reconnaissant_id') or False,
            'adoptant_id': payload.get('adoptant_id') or False,
            'source_approbation_adoption': payload.get(
                'source_approbation_adoption'
            ) or False,
        }
        if target_field and target_id:
            values[target_field] = target_id
        mention = request.env['etat.civil.mention.marginale'].create(values)
        EtatCivilApiController._apply_piece_updates(mention, payload.get('pieces'))
        return mention

    @classmethod
    def _serialize_registre(cls, reg):
        return {
            'id': reg.id,
            'designation': reg.designation,
            'annee': reg.annee,
            'type_registre': reg.type_registre,
            'numero_volume': reg.numero_volume,
            'centre_id': reg.centre_id.id,
            'centre_nom': reg.centre_id.nom_centre,
            'commune': reg.centre_id.commune,
            'est_cloture': reg.est_cloture,
            'date_ouverture': cls._serialize_value(reg.date_ouverture),
            'date_cloture': cls._serialize_value(reg.date_cloture),
        }

    @classmethod
    def _serialize_demande_guichet(cls, demande):
        return {
            'id': demande.id,
            'ticket_numero': demande.ticket_numero,
            'citoyen_nom': demande.citoyen_nom,
            'citoyen_cin': demande.citoyen_cin,
            'citoyen_nin': demande.citoyen_cin,
            'type_acte': demande.type_acte,
            'type_demande': demande.type_demande,
            'statut': demande.statut,
            'priorite': demande.priorite,
            'created_at': cls._serialize_value(demande.create_date),
            'processed_at': cls._serialize_value(demande.processed_at),
        }

    @staticmethod
    def _handle_error(error):
        if isinstance(error, ValidationError):
            return EtatCivilApiController._response({'error': str(error)}, status=400)
        if isinstance(error, AccessError):
            return EtatCivilApiController._response({'error': str(error)}, status=403)
        if isinstance(error, UserError):
            return EtatCivilApiController._response({'error': str(error)}, status=409)
        _logger.exception('Erreur inattendue dans l API Etat Civil', exc_info=error)
        return EtatCivilApiController._response({'error': 'Erreur interne du serveur.'}, status=500)

    @staticmethod
    def _resolve_or_create_individu(name, cin=None, sexe='M', date_naissance=None):
        if not name or not str(name).strip():
            return False
        clean_name = str(name).strip()
        model = request.env['etat.civil.individu']
        if cin and isinstance(cin, str) and re.fullmatch(r'[0-9]{12}', cin.strip()):
            match = model.search([('cin', '=', cin.strip())], limit=1)
            if match:
                return match.id
        match = model.search([('nom_complet', '=ilike', clean_name)], limit=1)
        if not match:
            match = model.search([('nom', '=ilike', clean_name)], limit=1)
        if match:
            return match.id
        vals = {
            'nom': clean_name,
            'sexe': sexe if sexe in ('M', 'F') else 'M',
            'date_naissance': date_naissance or fields.Date.context_today(model),
            'statut_vital': 'vivant',
            'situation_matrimoniale': 'celibataire',
        }
        if cin and isinstance(cin, str) and re.fullmatch(r'[0-9]{12}', cin.strip()):
            vals['cin'] = cin.strip()
        created = model.create(vals)
        return created.id

    @staticmethod
    def _get_default_registre(type_registre):
        model = request.env['etat.civil.registre']
        open_reg = model.search([
            ('type_registre', '=', type_registre),
            ('est_cloture', '=', False),
        ], order='annee desc, id desc', limit=1)
        if open_reg:
            return open_reg.id
        any_reg = model.search([('type_registre', '=', type_registre)], order='annee desc, id desc', limit=1)
        if any_reg:
            return any_reg.id
        centre = request.env['etat.civil.centre'].search([], limit=1)
        if not centre:
            centre = request.env['etat.civil.centre'].create({
                'name': 'Mairie Principale',
                'code_centre': 'CTR-01',
            })
        new_reg = model.create({
            'type_registre': type_registre,
            'annee': fields.Date.context_today(model).year,
            'numero_volume': 1,
            'centre_id': centre.id,
            'nombre_feuillets_max': 500,
            'est_cloture': False,
        })
        return new_reg.id

    # -------------------------------------------------------------------------
    # AUTHENTICATION
    # -------------------------------------------------------------------------

    @http.route(
        '/api/v1/auth/login',
        type='http',
        auth='none',
        methods=['POST'],
        csrf=False,
        save_session=True,
    )
    def login(self, **kwargs):
        """Authenticate an Odoo user and create a session cookie."""
        try:
            payload = self._json_body()
            login = payload.get('login')
            password = payload.get('password')
            if not login or not password:
                return self._response(
                    {'error': 'Les champs login et password sont obligatoires.'},
                    status=400,
                )
            target_db = payload.get('db') or request.db or 'gestion_detat_civil'
            try:
                # Odoo 17: authenticate(dbname, login, password) -> int uid
                res_auth = request.session.authenticate(target_db, login, password)
            except TypeError:
                # Fallback format dictionnaire Odoo 18
                res_auth = request.session.authenticate(
                    target_db,
                    {'login': login, 'password': password, 'type': 'password'},
                )
            uid = res_auth['uid'] if isinstance(res_auth, dict) else res_auth
            return self._response({
                'uid': uid,
                'session_id': request.session.sid,
                'message': 'Authentification réussie.',
            })
        except AccessDenied:
            return self._response({'error': 'Identifiants invalides.'}, status=401)
        except ValidationError as error:
            return self._response({'error': str(error)}, status=400)
        except Exception:
            _logger.exception('Erreur inattendue pendant l authentification API')
            return self._response({'error': 'Erreur interne du serveur.'}, status=500)

    @http.route(
        '/api/v1/auth/logout',
        type='http',
        auth='none',
        methods=['POST', 'GET'],
        csrf=False,
    )
    def logout(self, **kwargs):
        """Log out current user and invalidate session."""
        request.session.logout(keep_db=True)
        return self._response({'message': 'Déconnexion réussie.'})

    @http.route(
        '/api/v1/auth/me',
        type='http',
        auth='user',
        methods=['GET'],
        csrf=False,
    )
    def me(self, **kwargs):
        """Return the currently authenticated user information."""
        user = request.env.user
        return self._response({
            'uid': user.id,
            'name': user.name,
            'login': user.login,
            'is_agent': user.has_group('etat_civil.group_etat_civil_agent'),
            'is_officier': user.has_group('etat_civil.group_etat_civil_officier'),
            'is_admin': (
                user.has_group('etat_civil.group_etat_civil_admin')
                or user.has_group('base.group_system')
            ),
        })

    # -------------------------------------------------------------------------
    # PERSONNES / CITOYENS
    # -------------------------------------------------------------------------

    @http.route('/api/v1/personnes', type='http', auth='user', methods=['GET'], csrf=False)
    def search_personnes(self, **kwargs):
        try:
            page = self._query_int('page', 1, 1, 1000000)
            page_size = self._query_int('page_size', 25, 1, 100)
            query = (request.httprequest.args.get('q') or '').strip()
            domain = []
            if query:
                domain = ['|', '|', ('cin', 'ilike', query), ('nom', 'ilike', query), ('prenoms', 'ilike', query)]
            model = request.env['etat.civil.individu']
            total = model.search_count(domain)
            records = model.search(
                domain,
                order='nom asc, prenoms asc, id asc',
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            return self._response({
                'page': page,
                'page_size': page_size,
                'total': total,
                'data': [self._serialize_individu(record) for record in records],
            })
        except Exception as error:
            return self._handle_error(error)

    @http.route('/api/v1/personnes', type='http', auth='user', methods=['POST'], csrf=False)
    def create_personne(self, **kwargs):
        """Create a citizen / individu via API."""
        try:
            payload = self._json_body()
            allowed = {
                'cin', 'nin', 'nom', 'prenoms', 'sexe', 'date_naissance',
                'date_naissance_estimee', 'lieu_naissance_commune',
                'lieu_naissance_pays', 'profession_actuelle',
                'domicile_actuel', 'nationalite_actuelle',
                'statut_vital', 'situation_matrimoniale',
            }
            vals = {k: payload[k] for k in allowed if k in payload}
            legacy_cin = vals.pop('nin', None)
            if legacy_cin is not None:
                if vals.get('cin') not in (None, legacy_cin):
                    raise ValidationError("Les valeurs CIN reçues ne correspondent pas.")
                vals['cin'] = legacy_cin
            individu = request.env['etat.civil.individu'].create(vals)
            return self._response(self._serialize_individu(individu), status=201)
        except Exception as error:
            return self._handle_error(error)

    @http.route(
        ['/api/v1/personnes/<int:personne_id>', '/api/v1/personnes/<int:personne_id>/update'],
        type='http',
        auth='user',
        methods=['POST', 'PUT'],
        csrf=False,
    )
    def update_personne(self, personne_id, **kwargs):
        """Update a citizen / individu via API."""
        try:
            individu = request.env['etat.civil.individu'].browse(personne_id).exists()
            if not individu:
                return self._response({'error': 'Citoyen introuvable.'}, status=404)
            payload = self._json_body()
            allowed = {
                'cin', 'nin', 'nom', 'prenoms', 'sexe', 'date_naissance',
                'date_naissance_estimee', 'lieu_naissance_commune',
                'lieu_naissance_pays', 'profession_actuelle',
                'domicile_actuel', 'nationalite_actuelle',
                'statut_vital', 'situation_matrimoniale',
            }
            vals = {k: payload[k] for k in allowed if k in payload}
            legacy_cin = vals.pop('nin', None)
            if legacy_cin is not None:
                if vals.get('cin') not in (None, legacy_cin):
                    raise ValidationError("Les valeurs CIN reçues ne correspondent pas.")
                vals['cin'] = legacy_cin
            if vals:
                individu.write(vals)
            return self._response(self._serialize_individu(individu))
        except Exception as error:
            return self._handle_error(error)

    @http.route(
        '/api/v1/personnes/<int:personne_id>',
        type='http',
        auth='user',
        methods=['GET'],
        csrf=False,
    )
    def get_personne(self, personne_id, **kwargs):
        try:
            individu = request.env['etat.civil.individu'].browse(personne_id).exists()
            if not individu:
                return self._response({'error': 'Citoyen introuvable.'}, status=404)
            individu.check_access_rights('read')
            individu.check_access_rule('read')
            return self._response(self._serialize_individu(individu))
        except Exception as error:
            return self._handle_error(error)

    # -------------------------------------------------------------------------
    # REGISTRES & CENTRES
    # -------------------------------------------------------------------------

    @http.route('/api/v1/registres', type='http', auth='user', methods=['GET'], csrf=False)
    def list_registres(self, **kwargs):
        """List registers, filterable by active/open status and type."""
        try:
            domain = []
            type_reg = request.httprequest.args.get('type')
            if type_reg and type_reg in ('naissance', 'mariage', 'deces'):
                domain.append(('type_registre', '=', type_reg))
            annee = request.httprequest.args.get('annee')
            if annee:
                try:
                    domain.append(('annee', '=', int(annee)))
                except ValueError:
                    pass
            ouvert_uniquement = request.httprequest.args.get('ouvert')
            if ouvert_uniquement in ('1', 'true', 'True'):
                domain.append(('est_cloture', '=', False))

            registres = request.env['etat.civil.registre'].search(
                domain,
                order='annee desc, type_registre asc, numero_volume asc',
            )
            return self._response({
                'total': len(registres),
                'data': [self._serialize_registre(r) for r in registres],
            })
        except Exception as error:
            return self._handle_error(error)

    # -------------------------------------------------------------------------
    # ACTES MULTI-TYPES SEARCH
    # -------------------------------------------------------------------------

    @http.route('/api/v1/actes', type='http', auth='user', methods=['GET'], csrf=False)
    def search_actes(self, **kwargs):
        try:
            page = self._query_int('page', 1, 1, 1000000)
            page_size = self._query_int('page_size', 25, 1, 100)
            acte_type = request.httprequest.args.get('type', 'naissance')
            models_by_type = {
                'naissance': 'etat.civil.acte.naissance',
                'mariage': 'etat.civil.acte.mariage',
                'deces': 'etat.civil.acte.deces',
            }
            model_name = models_by_type.get(acte_type)
            if not model_name:
                raise ValidationError('Le type d’acte est invalide.')
            domain = []
            query = request.httprequest.args.get('q')
            if query:
                domain = ['|', ('numero_acte', 'ilike', query), ('texte_integral_acte', 'ilike', query)]
            statut = request.httprequest.args.get('statut')
            if statut:
                domain.append(('statut', '=', statut))
            model = request.env[model_name]
            total = model.search_count(domain)
            records = model.search(
                domain,
                order='date_dressage desc, id desc',
                offset=(page - 1) * page_size,
                limit=page_size,
            )

            if acte_type == 'naissance':
                data = [self._serialize_acte_naissance(r) for r in records]
            elif acte_type == 'mariage':
                data = [self._serialize_acte_mariage(r) for r in records]
            else:
                data = [self._serialize_acte_deces(r) for r in records]

            return self._response({
                'type': acte_type,
                'page': page,
                'page_size': page_size,
                'total': total,
                'data': data,
            })
        except Exception as error:
            return self._handle_error(error)

    # -------------------------------------------------------------------------
    # ACTES DE NAISSANCE
    # -------------------------------------------------------------------------

    @http.route('/api/v1/actes/naissance', type='http', auth='user', methods=['GET'], csrf=False)
    def list_actes_naissance(self, **kwargs):
        try:
            page = self._query_int('page', 1, 1, 1000000)
            page_size = self._query_int('page_size', 25, 1, 100)
            domain = []
            statut = request.httprequest.args.get('statut')
            if statut:
                allowed_statuses = {
                    'brouillon', 'en_attente', 'a_corriger',
                    'valide', 'rectifie', 'annule', 'archive',
                }
                if statut not in allowed_statuses:
                    raise ValidationError('Le statut demandé est invalide.')
                domain.append(('statut', '=', statut))
            actes_model = request.env['etat.civil.acte.naissance']
            total = actes_model.search_count(domain)
            actes = actes_model.search(
                domain,
                order='date_dressage desc, id desc',
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            return self._response({
                'page': page,
                'page_size': page_size,
                'count': len(actes),
                'total': total,
                'data': [self._serialize_acte_naissance(acte) for acte in actes],
            })
        except Exception as error:
            return self._handle_error(error)

    @http.route('/api/v1/actes/naissance', type='http', auth='user', methods=['POST'], csrf=False)
    def create_acte_naissance(self, **kwargs):
        try:
            payload = self._json_body()
            allowed_fields = {
                'numero_acte', 'feuillet_numero', 'registre_id', 'date_dressage',
                'texte_integral_acte', 'enfant_id', 'pere_id', 'mere_id',
                'heure_naissance', 'lieu_naissance', 'est_jumeau',
                'rang_naissance', 'certificat_medical_ref',
                'lieu_accouchement', 'filiation', 'date_declaration_commune',
                'declarant_id',
            }
            values = {key: payload[key] for key in allowed_fields if key in payload and payload[key] is not None}

            if not values.get('registre_id'):
                values['registre_id'] = self._get_default_registre('naissance')

            if not values.get('enfant_id') and payload.get('enfant_nom'):
                values['enfant_id'] = self._resolve_or_create_individu(
                    payload['enfant_nom'],
                    cin=payload.get('enfant_cin', payload.get('enfant_nin')),
                    sexe='M',
                    date_naissance=payload.get('date_naissance'),
                )
            if not values.get('mere_id') and payload.get('mere_nom'):
                values['mere_id'] = self._resolve_or_create_individu(payload['mere_nom'], sexe='F')
            if not values.get('pere_id') and payload.get('pere_nom'):
                values['pere_id'] = self._resolve_or_create_individu(payload['pere_nom'], sexe='M')
            if not values.get('declarant_id') and payload.get('declarant_nom'):
                values['declarant_id'] = self._resolve_or_create_individu(payload['declarant_nom'])

            acte = request.env['etat.civil.acte.naissance'].create(values)
            self._apply_piece_updates(acte, payload.get('pieces'))
            return self._response(self._serialize_acte_naissance(acte), status=201)
        except Exception as error:
            return self._handle_error(error)

    @http.route('/api/v1/actes/naissance/<int:acte_id>/valider', type='http', auth='user', methods=['POST'], csrf=False)
    def validate_acte_naissance(self, acte_id, **kwargs):
        try:
            acte = request.env['etat.civil.acte.naissance'].browse(acte_id).exists()
            if not acte:
                return self._response({'error': 'Acte de naissance introuvable.'}, status=404)
            acte.ensure_one()
            acte.action_valider_acte()
            return self._response(self._serialize_acte_naissance(acte))
        except Exception as error:
            return self._handle_error(error)

    # -------------------------------------------------------------------------
    # ACTES DE MARIAGE
    # -------------------------------------------------------------------------

    @http.route('/api/v1/actes/mariage', type='http', auth='user', methods=['GET'], csrf=False)
    def list_actes_mariage(self, **kwargs):
        try:
            page = self._query_int('page', 1, 1, 1000000)
            page_size = self._query_int('page_size', 25, 1, 100)
            domain = []
            statut = request.httprequest.args.get('statut')
            if statut:
                allowed_statuses = {
                    'brouillon', 'en_attente', 'a_corriger',
                    'valide', 'rectifie', 'annule', 'archive',
                }
                if statut not in allowed_statuses:
                    raise ValidationError('Le statut demandé est invalide.')
                domain.append(('statut', '=', statut))
            actes_model = request.env['etat.civil.acte.mariage']
            total = actes_model.search_count(domain)
            actes = actes_model.search(
                domain,
                order='date_dressage desc, id desc',
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            return self._response({
                'page': page,
                'page_size': page_size,
                'count': len(actes),
                'total': total,
                'data': [self._serialize_acte_mariage(acte) for acte in actes],
            })
        except Exception as error:
            return self._handle_error(error)

    @http.route('/api/v1/actes/mariage', type='http', auth='user', methods=['POST'], csrf=False)
    def create_acte_mariage(self, **kwargs):
        try:
            payload = self._json_body()
            allowed_fields = {
                'numero_acte', 'feuillet_numero', 'registre_id', 'date_dressage',
                'texte_integral_acte', 'conjoint_1_id', 'conjoint_2_id',
                'date_mariage', 'lieu_mariage', 'regime_matrimonial',
                'officier_etat_civil', 'conjoint_1_est_etranger',
                'conjoint_2_est_etranger', 'temoin_1_id', 'temoin_2_id',
            }
            values = {key: payload[key] for key in allowed_fields if key in payload and payload[key] is not None}

            if not values.get('registre_id'):
                values['registre_id'] = self._get_default_registre('mariage')

            if not values.get('conjoint_1_id') and payload.get('conjoint_1_nom'):
                values['conjoint_1_id'] = self._resolve_or_create_individu(payload['conjoint_1_nom'], sexe='M')
            if not values.get('conjoint_2_id') and payload.get('conjoint_2_nom'):
                values['conjoint_2_id'] = self._resolve_or_create_individu(payload['conjoint_2_nom'], sexe='F')
            for number in (1, 2):
                field_name = f'temoin_{number}_id'
                name = payload.get(f'temoin_{number}_nom')
                if not values.get(field_name) and name:
                    values[field_name] = self._resolve_or_create_individu(name)

            if not values.get('date_mariage'):
                values['date_mariage'] = payload.get('date_mariage') or fields.Date.today()
            if not values.get('lieu_mariage'):
                values['lieu_mariage'] = payload.get('lieu') or 'Commune urbaine'
            if not values.get('regime_matrimonial'):
                values['regime_matrimonial'] = 'communaute_biens'

            acte = request.env['etat.civil.acte.mariage'].create(values)
            self._apply_piece_updates(acte, payload.get('pieces'))
            return self._response(self._serialize_acte_mariage(acte), status=201)
        except Exception as error:
            return self._handle_error(error)

    @http.route('/api/v1/actes/mariage/<int:acte_id>/valider', type='http', auth='user', methods=['POST'], csrf=False)
    def validate_acte_mariage(self, acte_id, **kwargs):
        try:
            acte = request.env['etat.civil.acte.mariage'].browse(acte_id).exists()
            if not acte:
                return self._response({'error': 'Acte de mariage introuvable.'}, status=404)
            acte.ensure_one()
            acte.action_valider_acte()
            return self._response(self._serialize_acte_mariage(acte))
        except Exception as error:
            return self._handle_error(error)

    # -------------------------------------------------------------------------
    # ACTES DE DÉCÈS
    # -------------------------------------------------------------------------

    @http.route('/api/v1/actes/deces', type='http', auth='user', methods=['GET'], csrf=False)
    def list_actes_deces(self, **kwargs):
        try:
            page = self._query_int('page', 1, 1, 1000000)
            page_size = self._query_int('page_size', 25, 1, 100)
            domain = []
            statut = request.httprequest.args.get('statut')
            if statut:
                allowed_statuses = {
                    'brouillon', 'en_attente', 'a_corriger',
                    'valide', 'rectifie', 'annule', 'archive',
                }
                if statut not in allowed_statuses:
                    raise ValidationError('Le statut demandé est invalide.')
                domain.append(('statut', '=', statut))
            actes_model = request.env['etat.civil.acte.deces']
            total = actes_model.search_count(domain)
            actes = actes_model.search(
                domain,
                order='date_dressage desc, id desc',
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            return self._response({
                'page': page,
                'page_size': page_size,
                'count': len(actes),
                'total': total,
                'data': [self._serialize_acte_deces(acte) for acte in actes],
            })
        except Exception as error:
            return self._handle_error(error)

    @http.route('/api/v1/actes/deces', type='http', auth='user', methods=['POST'], csrf=False)
    def create_acte_deces(self, **kwargs):
        try:
            payload = self._json_body()
            allowed_fields = {
                'numero_acte', 'feuillet_numero', 'registre_id', 'date_dressage',
                'texte_integral_acte', 'defunt_id', 'declarant_id',
                'date_deces', 'heure_deces', 'lieu_deces', 'cause_deces',
                'certificat_medical_ref',
            }
            values = {key: payload[key] for key in allowed_fields if key in payload and payload[key] is not None}

            if not values.get('registre_id'):
                values['registre_id'] = self._get_default_registre('deces')

            if not values.get('defunt_id') and payload.get('defunt_nom'):
                values['defunt_id'] = self._resolve_or_create_individu(
                    payload['defunt_nom'],
                    cin=payload.get('defunt_cin', payload.get('defunt_nin')),
                    date_naissance='1970-01-01',
                )
            if not values.get('declarant_id') and payload.get('declarant_nom'):
                values['declarant_id'] = self._resolve_or_create_individu(payload['declarant_nom'])

            if not values.get('date_deces'):
                values['date_deces'] = payload.get('date_deces') or fields.Date.today()
            if not values.get('lieu_deces'):
                values['lieu_deces'] = payload.get('lieu') or 'Commune urbaine'

            acte = request.env['etat.civil.acte.deces'].create(values)
            self._apply_piece_updates(acte, payload.get('pieces'))
            return self._response(self._serialize_acte_deces(acte), status=201)
        except Exception as error:
            return self._handle_error(error)

    @http.route('/api/v1/actes/deces/<int:acte_id>/valider', type='http', auth='user', methods=['POST'], csrf=False)
    def validate_acte_deces(self, acte_id, **kwargs):
        try:
            acte = request.env['etat.civil.acte.deces'].browse(acte_id).exists()
            if not acte:
                return self._response({'error': 'Acte de décès introuvable.'}, status=404)
            acte.ensure_one()
            acte.action_valider_acte()
            return self._response(self._serialize_acte_deces(acte))
        except Exception as error:
            return self._handle_error(error)

    @http.route(
        [
            '/api/v1/actes/<string:acte_type>/<int:acte_id>',
            '/api/v1/actes/<string:acte_type>/<int:acte_id>/update',
        ],
        type='http',
        auth='user',
        methods=['POST', 'PUT'],
        csrf=False,
    )
    def update_acte(self, acte_type, acte_id, **kwargs):
        """Update an act in brouillon status via API."""
        try:
            model_name = {
                'naissance': 'etat.civil.acte.naissance',
                'mariage': 'etat.civil.acte.mariage',
                'deces': 'etat.civil.acte.deces',
            }.get(acte_type)
            if not model_name:
                raise ValidationError('Le type d’acte est invalide.')
            acte = request.env[model_name].browse(acte_id).exists()
            if not acte:
                return self._response({'error': 'Acte introuvable.'}, status=404)
            if acte.statut != 'brouillon':
                raise UserError(f"Seuls les actes au statut 'brouillon' peuvent être modifiés. Statut actuel: {acte.statut}")

            payload = self._json_body()
            allowed_by_type = {
                'naissance': {
                    'numero_acte', 'feuillet_numero', 'registre_id', 'date_dressage',
                    'texte_integral_acte', 'enfant_id', 'pere_id', 'mere_id',
                    'heure_naissance', 'lieu_naissance', 'est_jumeau',
                    'rang_naissance', 'certificat_medical_ref',
                    'lieu_accouchement', 'filiation', 'date_declaration_commune',
                    'declarant_id',
                },
                'mariage': {
                    'numero_acte', 'feuillet_numero', 'registre_id', 'date_dressage',
                    'texte_integral_acte', 'conjoint_1_id', 'conjoint_2_id',
                    'date_mariage', 'lieu_mariage', 'regime_matrimonial',
                    'officier_etat_civil', 'conjoint_1_est_etranger',
                    'conjoint_2_est_etranger', 'temoin_1_id', 'temoin_2_id',
                },
                'deces': {
                    'numero_acte', 'feuillet_numero', 'registre_id', 'date_dressage',
                    'texte_integral_acte', 'defunt_id', 'declarant_id',
                    'date_deces', 'heure_deces', 'lieu_deces', 'cause_deces',
                    'certificat_medical_ref',
                },
            }
            allowed = allowed_by_type[acte_type]
            vals = {k: payload[k] for k in allowed if k in payload and payload[k] is not None}
            if vals:
                acte.write(vals)
            self._apply_piece_updates(acte, payload.get('pieces'))

            serializer = {
                'naissance': self._serialize_acte_naissance,
                'mariage': self._serialize_acte_mariage,
                'deces': self._serialize_acte_deces,
            }[acte_type]
            return self._response(serializer(acte))
        except Exception as error:
            return self._handle_error(error)

    @http.route(
        '/api/v1/actes/<string:acte_type>/<int:acte_id>/valider',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=False,
    )
    def validate_acte_unified(self, acte_type, acte_id, **kwargs):
        """Unified validation route for any act type."""
        try:
            model_name = {
                'naissance': 'etat.civil.acte.naissance',
                'mariage': 'etat.civil.acte.mariage',
                'deces': 'etat.civil.acte.deces',
            }.get(acte_type)
            if not model_name:
                raise ValidationError('Le type d’acte est invalide.')
            acte = request.env[model_name].browse(acte_id).exists()
            if not acte:
                return self._response({'error': 'Acte introuvable.'}, status=404)
            acte.ensure_one()
            acte.action_valider_acte()
            serializer = {
                'naissance': self._serialize_acte_naissance,
                'mariage': self._serialize_acte_mariage,
                'deces': self._serialize_acte_deces,
            }[acte_type]
            return self._response(serializer(acte))
        except Exception as error:
            return self._handle_error(error)

    # -------------------------------------------------------------------------
    # MENTIONS MARGINALES
    # -------------------------------------------------------------------------

    @http.route(
        ['/api/v1/mentions', '/api/v1/personnes/<int:personne_id>/mentions'],
        type='http',
        auth='user',
        methods=['GET'],
        csrf=False,
    )
    def list_mentions(self, personne_id=None, **kwargs):
        try:
            page = self._query_int('page', 1, 1, 1000000)
            page_size = self._query_int('page_size', 25, 1, 100)
            model = request.env['etat.civil.mention.marginale']
            domain = []
            if personne_id:
                person = request.env['etat.civil.individu'].browse(personne_id).exists()
                if not person:
                    return self._response({'error': 'Citoyen introuvable.'}, status=404)
                person.check_access_rights('read')
                person.check_access_rule('read')
                domain = [
                    '|', '|',
                    ('personne_concernee_id', '=', person.id),
                    ('individu_id', '=', person.id),
                    ('acte_naissance_id.enfant_id', '=', person.id),
                ]
            mention_type = request.httprequest.args.get('type')
            if mention_type:
                if mention_type not in model._fields['type_mention'].get_values(model.env):
                    raise ValidationError('Le type de mention demandé est invalide.')
                domain.append(('type_mention', '=', mention_type))
            statut = request.httprequest.args.get('statut')
            if statut:
                if statut not in model._fields['statut'].get_values(model.env):
                    raise ValidationError('Le statut demandé est invalide.')
                domain.append(('statut', '=', statut))
            total = model.search_count(domain)
            mentions = model.search(
                domain,
                order='date_mention desc, id desc',
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            return self._response({
                'page': page,
                'page_size': page_size,
                'total': total,
                'data': [self._serialize_mention(mention) for mention in mentions],
            })
        except Exception as error:
            return self._handle_error(error)

    @http.route(
        '/api/v1/actes/<string:acte_type>/<int:acte_id>/mentions',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=False,
    )
    @http.route(
        '/api/v1/personnes/<int:personne_id>/mentions',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=False,
    )
    def add_mention(self, acte_type=None, acte_id=None, personne_id=None, **kwargs):
        try:
            payload = self._json_body()
            if personne_id:
                person = request.env['etat.civil.individu'].browse(personne_id).exists()
                if not person:
                    return self._response({'error': 'Citoyen introuvable.'}, status=404)
                payload['personne_id'] = person.id
                mention = self._create_marginal_mention_from_payload(payload)
                return self._response(self._serialize_mention(mention), status=201)
            model_name = {
                'naissance': 'etat.civil.acte.naissance',
                'mariage': 'etat.civil.acte.mariage',
                'deces': 'etat.civil.acte.deces',
            }.get(acte_type)
            field_name = {
                'naissance': 'acte_naissance_id',
                'mariage': 'acte_mariage_id',
                'deces': 'acte_deces_id',
            }.get(acte_type)
            if not model_name:
                raise ValidationError('Le type d’acte est invalide.')
            acte = request.env[model_name].browse(acte_id).exists()
            if not acte:
                return self._response({'error': 'Acte introuvable.'}, status=404)
            person_id = payload.get('personne_id')
            if person_id:
                person = request.env['etat.civil.individu'].browse(person_id).exists()
                if not person:
                    raise ValidationError('La personne concernée est introuvable.')
                if acte_type == 'mariage' and person not in (
                    acte.conjoint_1_id | acte.conjoint_2_id
                ):
                    raise ValidationError(
                        'La personne concernée doit être liée à cet acte.'
                    )
                if acte_type == 'deces' and person != acte.defunt_id:
                    raise ValidationError(
                        'La personne concernée doit être liée à cet acte.'
                    )
            if acte_type == 'naissance':
                payload['personne_id'] = acte.enfant_id.id
            mention = self._create_marginal_mention_from_payload(
                payload,
                target_field=field_name,
                target_id=acte.id,
            )
            return self._response(self._serialize_mention(mention), status=201)
        except Exception as error:
            return self._handle_error(error)

    @http.route(
        '/api/v1/mentions/<int:mention_id>/valider',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=False,
    )
    def validate_marginal_mention(self, mention_id, **kwargs):
        try:
            mention = request.env['etat.civil.mention.marginale'].browse(
                mention_id
            ).exists()
            if not mention:
                return self._response({'error': 'Mention marginale introuvable.'}, status=404)
            mention.action_valider_mention()
            return self._response(self._serialize_mention(mention))
        except Exception as error:
            return self._handle_error(error)

    # -------------------------------------------------------------------------
    # VÉRIFICATION D'ACTE & QR CODE
    # -------------------------------------------------------------------------

    @http.route('/api/v1/actes/<string:acte_type>/<int:acte_id>/verifier', type='http', auth='user', methods=['GET'], csrf=False)
    def verify_acte(self, acte_type, acte_id, **kwargs):
        """Verify the integrity of a civil act using the official model hash computation."""
        model_name = {
            'naissance': 'etat.civil.acte.naissance',
            'mariage': 'etat.civil.acte.mariage',
            'deces': 'etat.civil.acte.deces',
        }.get(acte_type)
        if not model_name:
            return self._response({'error': 'Le type d’acte est invalide.'}, status=400)
        acte = request.env[model_name].browse(acte_id).exists()
        if not acte:
            return self._response({'error': 'Acte introuvable.'}, status=404)

        expected_hash = acte._compute_integrity_hash()
        is_authentic = bool(
            acte.hash_empreinte_num
            and expected_hash == acte.hash_empreinte_num
            and acte.statut in ('valide', 'rectifie')
        )
        return self._response({
            'id': acte.id,
            'numero_acte': acte.numero_acte,
            'statut': acte.statut,
            'valide': is_authentic,
            'hash_enregistre': acte.hash_empreinte_num,
            'hash_calcule': expected_hash,
            'qr_code_signature': acte.qr_code_signature,
        })

    @http.route(
        '/api/v1/actes/verifier_qr',
        type='http',
        auth='none',
        methods=['GET', 'POST'],
        csrf=False,
    )
    def verify_qr(self, **kwargs):
        """
        Public / agent endpoint to verify a scanned QR code string.
        Format: 'etat-civil:<model_name>:<record_id>:<hash_sha256>'
        """
        try:
            if request.httprequest.method == 'POST':
                payload = self._json_body()
                qr_code = payload.get('qr_code') or payload.get('code') or ''
            else:
                qr_code = request.httprequest.args.get('code') or request.httprequest.args.get('qr') or ''

            qr_code = qr_code.strip()
            if not qr_code or not qr_code.startswith('etat-civil:'):
                return self._response({
                    'valide': False,
                    'erreur': 'Format de QR Code invalide (doit débuter par etat-civil:).',
                }, status=400)

            parts = qr_code.split(':')
            if len(parts) < 4:
                return self._response({
                    'valide': False,
                    'erreur': 'Payload QR incomplet.',
                }, status=400)

            _, model_name, record_id_str, provided_hash = parts[0], parts[1], parts[2], parts[3]
            allowed_models = {
                'etat.civil.acte.naissance': 'naissance',
                'etat.civil.acte.mariage': 'mariage',
                'etat.civil.acte.deces': 'deces',
            }
            if model_name not in allowed_models:
                return self._response({
                    'valide': False,
                    'erreur': 'Modèle d’acte inconnu.',
                }, status=400)

            try:
                record_id = int(record_id_str)
            except ValueError:
                return self._response({
                    'valide': False,
                    'erreur': 'Identifiant d’acte non numérique.',
                }, status=400)

            # Use sudo() here to allow public verifiers / mobile agents to verify certificate authenticity
            acte = request.env[model_name].sudo().browse(record_id).exists()
            if not acte:
                return self._response({
                    'valide': False,
                    'erreur': 'Acte introuvable dans le registre officiel.',
                }, status=404)

            computed_hash = acte._compute_integrity_hash()
            hash_matches = (
                bool(acte.hash_empreinte_num)
                and provided_hash.lower() == acte.hash_empreinte_num.lower()
                and computed_hash.lower() == acte.hash_empreinte_num.lower()
            )
            is_valid = hash_matches and acte.statut in ('valide', 'rectifie')

            acte_type = allowed_models[model_name]
            return self._response({
                'valide': is_valid,
                'statut': acte.statut,
                'statut_label': dict(acte._fields['statut'].selection).get(acte.statut),
                'hash_conforme': hash_matches,
                'acte': {
                    'id': acte.id,
                    'type_acte': acte_type,
                    'numero_acte': acte.numero_acte,
                },
            })
        except Exception as error:
            return self._handle_error(error)

    # -------------------------------------------------------------------------
    # FILE D'ATTENTE DU GUICHET
    # -------------------------------------------------------------------------

    @http.route(
        '/api/v1/demandes-guichet',
        type='http',
        auth='user',
        methods=['GET'],
        csrf=False,
    )
    def list_demandes_guichet(self, **kwargs):
        try:
            page = self._query_int('page', 1, 1, 1000000)
            page_size = self._query_int('page_size', 100, 1, 100)
            statut = request.httprequest.args.get('statut')
            allowed_statuses = {'en_attente', 'en_cours', 'traite', 'annule'}
            if statut and statut not in allowed_statuses:
                raise ValidationError('Le statut de ticket demandé est invalide.')
            domain = [('statut', '=', statut)] if statut else []
            model = request.env['etat.civil.demande.guichet']
            total = model.search_count(domain)
            records = model.search(
                domain,
                order='priorite desc, create_date asc, id asc',
                offset=(page - 1) * page_size,
                limit=page_size,
            )
            return self._response({
                'page': page,
                'page_size': page_size,
                'total': total,
                'data': [self._serialize_demande_guichet(row) for row in records],
            })
        except Exception as error:
            return self._handle_error(error)

    @http.route(
        '/api/v1/demandes-guichet',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=False,
    )
    def create_demande_guichet(self, **kwargs):
        try:
            payload = self._json_body()
            allowed_fields = {
                'citoyen_nom',
                'citoyen_cin',
                'citoyen_nin',
                'type_acte',
                'type_demande',
                'priorite',
            }
            values = {key: payload[key] for key in allowed_fields if key in payload}
            demande = request.env['etat.civil.demande.guichet'].create(values)
            return self._response(
                self._serialize_demande_guichet(demande),
                status=201,
            )
        except Exception as error:
            return self._handle_error(error)

    @http.route(
        '/api/v1/demandes-guichet/<int:demande_id>/statut',
        type='http',
        auth='user',
        methods=['POST'],
        csrf=False,
    )
    def update_demande_guichet_status(self, demande_id, **kwargs):
        try:
            payload = self._json_body()
            statut = payload.get('statut')
            demande = request.env['etat.civil.demande.guichet'].browse(
                demande_id
            ).exists()
            if not demande:
                return self._response(
                    {'error': 'Ticket guichet introuvable.'},
                    status=404,
                )
            demande.action_set_status(statut)
            return self._response(self._serialize_demande_guichet(demande))
        except Exception as error:
            return self._handle_error(error)

    # -------------------------------------------------------------------------
    # STATISTIQUES GLOBALES
    # -------------------------------------------------------------------------

    @http.route('/api/v1/statistiques', type='http', auth='user', methods=['GET'], csrf=False)
    def statistiques(self, **kwargs):
        """Return global statistical metrics for mobile and external dashboards."""
        try:
            today = date.today()
            today_start = datetime.combine(today, datetime.min.time())

            models = {
                'naissance': request.env['etat.civil.acte.naissance'],
                'mariage': request.env['etat.civil.acte.mariage'],
                'deces': request.env['etat.civil.acte.deces'],
            }

            by_type = {}
            total_actes = 0
            actes_today = 0
            brouillons = 0
            valides = 0
            annules = 0

            for type_name, model in models.items():
                count = model.search_count([])
                by_type[type_name] = count
                total_actes += count
                actes_today += model.search_count([('date_dressage', '>=', today_start)])
                brouillons += model.search_count([('statut', '=', 'brouillon')])
                valides += model.search_count([('statut', '=', 'valide')])
                annules += model.search_count([('statut', 'in', ('annule', 'archive'))])

            total_citoyens = request.env['etat.civil.individu'].search_count([])
            total_registres = request.env['etat.civil.registre'].search_count([])
            registres_ouverts = request.env['etat.civil.registre'].search_count([('est_cloture', '=', False)])
            demandes_guichet_en_attente = request.env[
                'etat.civil.demande.guichet'
            ].search_count([('statut', '=', 'en_attente')])

            return self._response({
                'total_actes': total_actes,
                'by_type': by_type,
                'actes_today': actes_today,
                'statut_counts': {
                    'brouillon': brouillons,
                    'valide': valides,
                    'annule_archive': annules,
                },
                'total_citoyens': total_citoyens,
                'total_registres': total_registres,
                'registres_ouverts': registres_ouverts,
                'demandes_guichet_en_attente': demandes_guichet_en_attente,
            })
        except Exception as error:
            return self._handle_error(error)
