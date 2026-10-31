import base64
import csv
import io
import json
import logging
import os
import tempfile
import zipfile

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Maximum file sizes
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB
MAX_ZIP_TOTAL = 200 * 1024 * 1024  # 200 MB decompressed
BATCH_SIZE = 500

# Auto-mapping: common external column names → Odoo field names
AUTO_MAPPING = {
    'nom': 'nom',
    'name': 'nom',
    'last_name': 'nom',
    'lastname': 'nom',
    'family_name': 'nom',
    'nom_famille': 'nom',
    'prenom': 'prenoms',
    'prenoms': 'prenoms',
    'first_name': 'prenoms',
    'firstname': 'prenoms',
    'given_name': 'prenoms',
    'cin': 'cin',
    'nin': 'cin',
    'id_number': 'cin',
    'carte_identite': 'cin',
    'sexe': 'sexe',
    'sex': 'sexe',
    'gender': 'sexe',
    'genre': 'sexe',
    'date_naissance': 'date_naissance',
    'birth_date': 'date_naissance',
    'date_of_birth': 'date_naissance',
    'dob': 'date_naissance',
    'nationalite': 'nationalite_actuelle',
    'nationality': 'nationalite_actuelle',
    'nationalite_actuelle': 'nationalite_actuelle',
    'domicile': 'domicile_actuel',
    'address': 'domicile_actuel',
    'adresse': 'domicile_actuel',
    'domicile_actuel': 'domicile_actuel',
    'profession': 'profession_actuelle',
    'profession_actuelle': 'profession_actuelle',
    'job': 'profession_actuelle',
    'commune_naissance': 'lieu_naissance_commune',
    'lieu_naissance_commune': 'lieu_naissance_commune',
    'birthplace': 'lieu_naissance_commune',
    'lieu_naissance': 'lieu_naissance_commune',
    'pays_naissance': 'lieu_naissance_pays',
    'lieu_naissance_pays': 'lieu_naissance_pays',
    'birth_country': 'lieu_naissance_pays',
    'country': 'lieu_naissance_pays',
    'statut_vital': 'statut_vital',
    'vital_status': 'statut_vital',
    'situation_matrimoniale': 'situation_matrimoniale',
    'marital_status': 'situation_matrimoniale',
}

# Fields allowed for import on etat.civil.individu
IMPORTABLE_FIELDS = {
    'nom', 'prenoms', 'cin', 'sexe', 'date_naissance',
    'date_naissance_estimee', 'lieu_naissance_commune', 'lieu_naissance_pays',
    'nationalite_actuelle', 'domicile_actuel', 'profession_actuelle',
    'statut_vital', 'situation_matrimoniale',
}


def _create_exchange_log(
    env,
    operation,
    state,
    file_name,
    file_format,
    total_rows=0,
    imported_rows=0,
    updated_rows=0,
    skipped_rows=0,
    duplicate_rows=0,
    error_rows=0,
):
    operation_label = _("Importation") if operation == "import" else _("Exportation")
    env["etat.civil.exchange.log"].sudo().create({
        "name": "%s — %s" % (operation_label, file_name or _("sans nom")),
        "operation": operation,
        "state": state,
        "user_id": env.uid,
        "file_name": file_name,
        "file_format": file_format,
        "total_rows": total_rows,
        "imported_rows": imported_rows,
        "updated_rows": updated_rows,
        "skipped_rows": skipped_rows,
        "duplicate_rows": duplicate_rows,
        "error_rows": error_rows,
    })


class EtatCivilImportWizard(models.TransientModel):
    _name = 'etat.civil.import.wizard'
    _description = "Assistant d'importation des citoyens"

    file_data = fields.Binary(string='Fichier à importer', required=True)
    file_name = fields.Char(string='Nom du fichier')
    file_format = fields.Selection([
        ('csv', 'CSV'),
        ('xlsx', 'Excel (.xlsx)'),
        ('xls', 'Excel ancien (.xls)'),
        ('json', 'JSON'),
        ('xml', 'XML'),
        ('ods', 'ODS (LibreOffice)'),
        ('zip', 'ZIP (archive)'),
    ], string='Format', compute='_compute_file_format', store=True)

    duplicate_strategy = fields.Selection([
        ('skip', 'Ignorer les doublons'),
        ('update', 'Mettre à jour les doublons'),
        ('report', 'Signaler les doublons (ne pas importer)'),
    ], string='Stratégie de doublons', default='skip', required=True)

    state = fields.Selection([
        ('upload', 'Téléverser'),
        ('mapping', 'Correspondance des colonnes'),
        ('preview', 'Aperçu'),
        ('done', 'Terminé'),
    ], default='upload', string='Étape')

    # Mapping fields (stored as JSON)
    detected_columns = fields.Text(string='Colonnes détectées (JSON)', readonly=True)
    column_mapping = fields.Text(
        string='Correspondance des colonnes (JSON)',
        help='JSON dict: {"external_col": "odoo_field_or_empty", ...}',
    )
    preview_data = fields.Text(string='Aperçu (JSON)', readonly=True)

    # Results
    result_total = fields.Integer(string='Lignes analysées', readonly=True)
    result_imported = fields.Integer(string='Citoyens importés', readonly=True)
    result_updated = fields.Integer(string='Citoyens mis à jour', readonly=True)
    result_duplicates = fields.Integer(string='Doublons détectés', readonly=True)
    result_skipped = fields.Integer(string='Lignes ignorées', readonly=True)
    result_errors = fields.Integer(string='Erreurs', readonly=True)
    result_details = fields.Text(string='Détails / erreurs', readonly=True)
    result_error_file = fields.Binary(string='Rapport des erreurs', readonly=True)
    result_error_file_name = fields.Char(string='Nom du rapport', readonly=True)

    @api.depends('file_name')
    def _compute_file_format(self):
        ext_map = {
            '.csv': 'csv',
            '.xlsx': 'xlsx',
            '.xls': 'xls',
            '.json': 'json',
            '.xml': 'xml',
            '.ods': 'ods',
            '.zip': 'zip',
        }
        for rec in self:
            ext = ''
            if rec.file_name:
                ext = os.path.splitext(rec.file_name)[1].lower()
            rec.file_format = ext_map.get(ext, False)

    def _decode_file(self):
        """Decode binary field and validate file size."""
        self.ensure_one()
        if not self.file_data:
            raise UserError(_("Aucun fichier fourni."))
        raw = base64.b64decode(self.file_data)
        if len(raw) > MAX_FILE_SIZE:
            raise UserError(
                _("Le fichier dépasse la taille maximale autorisée (%d Mo).")
                % (MAX_FILE_SIZE // (1024 * 1024))
            )
        return raw

    def _parse_file(self, raw=None):
        """Parse the uploaded file and return a list of dicts (rows)."""
        self.ensure_one()
        if raw is None:
            raw = self._decode_file()
        fmt = self.file_format
        if not fmt:
            raise UserError(_("Format de fichier non reconnu. Extensions acceptées : .csv, .xlsx, .xls, .json, .xml, .ods, .zip"))
        if fmt == 'csv':
            return self._parse_csv(raw)
        elif fmt == 'xlsx':
            return self._parse_xlsx(raw)
        elif fmt == 'xls':
            return self._parse_xls(raw)
        elif fmt == 'json':
            return self._parse_json(raw)
        elif fmt == 'xml':
            return self._parse_xml(raw)
        elif fmt == 'ods':
            return self._parse_ods(raw)
        elif fmt == 'zip':
            return self._parse_zip(raw)
        raise UserError(_("Format '%s' non pris en charge.") % fmt)

    def _parse_csv(self, raw):
        try:
            text = raw.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise UserError(_("Le fichier CSV n'est pas encodé en UTF-8.")) from exc
        reader = csv.DictReader(io.StringIO(text))
        return [dict(row) for row in reader]

    def _parse_xlsx(self, raw):
        try:
            import openpyxl
        except ImportError:
            raise UserError(_("La bibliothèque 'openpyxl' est nécessaire pour importer des fichiers Excel (.xlsx). Installez-la avec : pip install openpyxl"))
        wb = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        if not rows:
            return []
        headers = [str(h or '').strip() for h in rows[0]]
        result = []
        for row in rows[1:]:
            d = {}
            for i, val in enumerate(row):
                if i < len(headers) and headers[i]:
                    d[headers[i]] = str(val) if val is not None else ''
            result.append(d)
        wb.close()
        return result

    def _parse_xls(self, raw):
        try:
            import xlrd
        except ImportError:
            raise UserError(_("La bibliothèque 'xlrd' est nécessaire pour les fichiers .xls. Installez-la avec : pip install xlrd"))
        wb = xlrd.open_workbook(file_contents=raw)
        ws = wb.sheet_by_index(0)
        headers = [str(ws.cell_value(0, c)).strip() for c in range(ws.ncols)]
        result = []
        for r in range(1, ws.nrows):
            d = {}
            for c in range(ws.ncols):
                if headers[c]:
                    d[headers[c]] = str(ws.cell_value(r, c)).strip()
            result.append(d)
        return result

    def _parse_json(self, raw):
        text = raw.decode('utf-8-sig', errors='replace')
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get('data', data.get('citoyens', data.get('records', [])))
        if not isinstance(data, list):
            raise UserError(_("Le fichier JSON doit contenir une liste de citoyens."))
        return [{str(k): str(v) if v is not None else '' for k, v in row.items()} for row in data if isinstance(row, dict)]

    def _parse_xml(self, raw):
        import xml.etree.ElementTree as ET
        if b'<!DOCTYPE' in raw.upper() or b'<!ENTITY' in raw.upper():
            raise UserError(_("Les déclarations DTD et entités XML ne sont pas autorisées."))
        root = ET.fromstring(raw)
        result = []
        # Support both <citoyens><citoyen>...</citoyen></citoyens>
        # and <records><record>...</record></records>
        for child in root:
            d = {}
            for elem in child:
                d[elem.tag] = (elem.text or '').strip()
            if d:
                result.append(d)
        return result

    def _parse_ods(self, raw):
        try:
            from odf.opendocument import load as odf_load
            from odf.table import Table, TableRow, TableCell
            from odf.text import P
        except ImportError:
            raise UserError(_("La bibliothèque 'odfpy' est nécessaire pour les fichiers .ods. Installez-la avec : pip install odfpy"))
        doc = odf_load(io.BytesIO(raw))
        result = []
        for table in doc.getElementsByType(Table):
            rows = table.getElementsByType(TableRow)
            if not rows:
                continue
            headers = []
            for cell in rows[0].getElementsByType(TableCell):
                text_parts = []
                for p in cell.getElementsByType(P):
                    text_content = ''
                    for child_node in p.childNodes:
                        text_content += str(child_node)
                    text_parts.append(text_content.strip())
                headers.append(' '.join(text_parts).strip())
            for row in rows[1:]:
                d = {}
                cells = row.getElementsByType(TableCell)
                for i, cell in enumerate(cells):
                    if i < len(headers) and headers[i]:
                        text_parts = []
                        for p in cell.getElementsByType(P):
                            text_content = ''
                            for child_node in p.childNodes:
                                text_content += str(child_node)
                            text_parts.append(text_content.strip())
                        d[headers[i]] = ' '.join(text_parts).strip()
                if any(v for v in d.values()):
                    result.append(d)
            break  # Only first table
        return result

    def _parse_zip(self, raw):
        """Parse supported files in an archive without extracting them."""
        total_decompressed = 0
        all_rows = []
        with zipfile.ZipFile(io.BytesIO(raw), 'r') as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                normalized_name = info.filename.replace('\\', '/')
                if (
                    normalized_name.startswith('/')
                    or any(part == '..' for part in normalized_name.split('/'))
                ):
                    raise UserError(
                        _("Le fichier ZIP contient un chemin non autorisé : %s")
                        % info.filename
                    )
                total_decompressed += info.file_size
                if total_decompressed > MAX_ZIP_TOTAL:
                    raise UserError(
                        _("La taille totale décompressée dépasse la limite (%d Mo).")
                        % (MAX_ZIP_TOTAL // (1024 * 1024))
                    )
                ext = os.path.splitext(info.filename)[1].lower()
                if ext not in ('.csv', '.xlsx', '.xls', '.json', '.xml', '.ods'):
                    continue
                inner_raw = zf.read(info.filename)
                # Create a temporary sub-wizard to parse each file
                sub = self.new({
                    'file_name': info.filename,
                    'file_format': {
                        '.csv': 'csv', '.xlsx': 'xlsx', '.xls': 'xls',
                        '.json': 'json', '.xml': 'xml', '.ods': 'ods',
                    }.get(ext),
                })
                try:
                    all_rows.extend(sub._parse_file(inner_raw))
                except Exception as e:
                    _logger.warning("Could not parse %s from uploaded ZIP: %s", info.filename, e)
                    raise UserError(
                        _("Impossible de lire le fichier « %s » contenu dans l'archive : %s")
                        % (info.filename, str(e))
                    ) from e
        return all_rows

    def action_detect_columns(self):
        """Step 1 → Step 2: Parse file and detect columns."""
        self.ensure_one()
        rows = self._parse_file()
        if not rows:
            raise UserError(_("Le fichier ne contient aucune donnée."))

        # Collect all column names
        columns = list(dict.fromkeys(
            col for row in rows for col in row.keys() if col.strip()
        ))

        # Auto-map columns
        mapping = {}
        for col in columns:
            normalized = col.strip().lower().replace(' ', '_').replace('-', '_')
            odoo_field = AUTO_MAPPING.get(normalized, '')
            mapping[col] = odoo_field

        self.write({
            'detected_columns': json.dumps(columns, ensure_ascii=False),
            'column_mapping': json.dumps(mapping, ensure_ascii=False),
            'state': 'mapping',
        })
        return self._reopen_wizard()

    def action_preview(self):
        """Step 2 → Step 3: Show preview of mapped data."""
        self.ensure_one()
        rows = self._parse_file()
        mapping = json.loads(self.column_mapping or '{}')

        preview_rows = []
        for row in rows[:20]:  # Show max 20 rows
            mapped = {}
            for ext_col, odoo_field in mapping.items():
                if odoo_field and odoo_field in IMPORTABLE_FIELDS:
                    val = row.get(ext_col, '')
                    mapped[odoo_field] = val
            if mapped:
                preview_rows.append(mapped)

        self.write({
            'preview_data': json.dumps(preview_rows, ensure_ascii=False, indent=2),
            'state': 'preview',
        })
        return self._reopen_wizard()

    def action_import(self):
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                return self._action_import()
        except Exception:
            _create_exchange_log(
                self.env,
                "import",
                "failed",
                self.file_name,
                self.file_format,
                error_rows=1,
            )
            raise

    def _action_import(self):
        """Step 3 → Step 4: Execute the actual import."""
        self.ensure_one()
        rows = self._parse_file()
        mapping = json.loads(self.column_mapping or '{}')

        # Build active mapping (only mapped fields)
        active_mapping = {
            ext_col: odoo_field
            for ext_col, odoo_field in mapping.items()
            if odoo_field and odoo_field in IMPORTABLE_FIELDS
        }

        if not active_mapping:
            raise UserError(_("Aucune correspondance de colonne valide n'a été définie."))

        Individu = self.env['etat.civil.individu']
        total = len(rows)
        imported = 0
        updated = 0
        duplicates = 0
        skipped = 0
        errors = 0
        error_details = []

        # Process in batches
        for batch_start in range(0, total, BATCH_SIZE):
            batch = rows[batch_start:batch_start + BATCH_SIZE]
            for idx, row in enumerate(batch):
                line_num = batch_start + idx + 2  # +2 for header + 0-index
                try:
                    with self.env.cr.savepoint():
                        vals = self._map_row(row, active_mapping, line_num)
                        if not vals:
                            skipped += 1
                            continue

                        # Check for duplicates
                        existing = self._find_duplicate(vals, Individu)
                        if existing:
                            duplicates += 1
                            if self.duplicate_strategy == 'skip':
                                skipped += 1
                                continue
                            elif self.duplicate_strategy == 'update':
                                update_vals = {k: v for k, v in vals.items() if v}
                                if 'cin' in update_vals:
                                    del update_vals['cin']
                                if update_vals:
                                    existing.write(update_vals)
                                    updated += 1
                                else:
                                    skipped += 1
                                continue
                            elif self.duplicate_strategy == 'report':
                                error_details.append(
                                    _("Ligne %d : doublon détecté (CIN: %s, Nom: %s %s).")
                                    % (line_num, vals.get('cin', ''), vals.get('nom', ''), vals.get('prenoms', ''))
                                )
                                skipped += 1
                                continue

                        if not vals.get('nom'):
                            error_details.append(_("Ligne %d : le nom est obligatoire.") % line_num)
                            errors += 1
                            continue
                        if not vals.get('sexe'):
                            error_details.append(_("Ligne %d : le sexe est obligatoire.") % line_num)
                            errors += 1
                            continue
                        if not vals.get('date_naissance'):
                            error_details.append(_("Ligne %d : la date de naissance est obligatoire.") % line_num)
                            errors += 1
                            continue

                        Individu.create(vals)
                        imported += 1

                except ValidationError as e:
                    errors += 1
                    error_details.append(_("Ligne %d : %s") % (line_num, str(e)))
                except Exception as e:
                    errors += 1
                    error_details.append(_("Ligne %d : erreur inattendue — %s") % (line_num, str(e)))
                    _logger.exception("Import error at line %d", line_num)

        # Generate error report file
        error_file = False
        error_file_name = False
        if error_details:
            report_text = '\n'.join(error_details)
            error_file = base64.b64encode(report_text.encode('utf-8'))
            error_file_name = 'rapport_erreurs_import.txt'

        _create_exchange_log(
            self.env,
            "import",
            "partial" if errors else "success",
            self.file_name,
            self.file_format,
            total_rows=total,
            imported_rows=imported,
            updated_rows=updated,
            skipped_rows=skipped,
            duplicate_rows=duplicates,
            error_rows=errors,
        )
        self.write({
            'state': 'done',
            'result_total': total,
            'result_imported': imported,
            'result_updated': updated,
            'result_duplicates': duplicates,
            'result_skipped': skipped,
            'result_errors': errors,
            'result_details': '\n'.join(error_details[:100]) if error_details else _("Importation terminée sans erreur."),
            'result_error_file': error_file,
            'result_error_file_name': error_file_name,
        })
        return self._reopen_wizard()

    def _map_row(self, row, active_mapping, line_num):
        """Map a single row from external columns to Odoo fields."""
        vals = {}
        for ext_col, odoo_field in active_mapping.items():
            raw_val = (row.get(ext_col) or '').strip()
            if not raw_val:
                continue
            if odoo_field == 'sexe':
                raw_lower = raw_val.lower()
                if raw_lower in ('m', 'masculin', 'male', 'homme', 'h'):
                    vals['sexe'] = 'M'
                elif raw_lower in ('f', 'féminin', 'feminin', 'female', 'femme'):
                    vals['sexe'] = 'F'
                else:
                    vals['sexe'] = raw_val
            elif odoo_field == 'date_naissance':
                vals['date_naissance'] = self._parse_date(raw_val, line_num)
            elif odoo_field == 'statut_vital':
                raw_lower = raw_val.lower()
                if raw_lower in ('vivant', 'alive', 'living', 'v'):
                    vals['statut_vital'] = 'vivant'
                elif raw_lower in ('décédé', 'decede', 'dead', 'deceased', 'd'):
                    vals['statut_vital'] = 'decede'
                elif raw_lower in ('disparu', 'missing', 'presumed_missing'):
                    vals['statut_vital'] = 'disparu'
                else:
                    vals['statut_vital'] = raw_val
            elif odoo_field == 'situation_matrimoniale':
                raw_lower = raw_val.lower()
                sm_map = {
                    'célibataire': 'celibataire', 'celibataire': 'celibataire',
                    'single': 'celibataire',
                    'marié': 'marie', 'mariée': 'marie', 'marie': 'marie',
                    'married': 'marie',
                    'divorcé': 'divorce', 'divorcée': 'divorce', 'divorce': 'divorce',
                    'divorced': 'divorce',
                    'veuf': 'veuf', 'veuve': 'veuf', 'widowed': 'veuf',
                }
                vals['situation_matrimoniale'] = sm_map.get(raw_lower, raw_val)
            elif odoo_field == 'date_naissance_estimee':
                raw_lower = raw_val.lower()
                vals['date_naissance_estimee'] = raw_lower in ('true', 'oui', '1', 'yes', 'vrai')
            else:
                vals[odoo_field] = raw_val
        return vals

    def _parse_date(self, raw_val, line_num):
        """Parse a date string to YYYY-MM-DD format."""
        import re
        from datetime import datetime
        patterns = [
            ('%Y-%m-%d', None),
            ('%d/%m/%Y', None),
            ('%d-%m-%Y', None),
            ('%m/%d/%Y', None),
            ('%Y/%m/%d', None),
            ('%d.%m.%Y', None),
        ]
        for fmt, _ in patterns:
            try:
                dt = datetime.strptime(raw_val.strip(), fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
        # Try ISO format
        try:
            dt = datetime.fromisoformat(raw_val.strip()[:10])
            return dt.strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            pass
        raise ValidationError(
            _("Ligne %d : date de naissance invalide '%s'. Formats acceptés : YYYY-MM-DD, DD/MM/YYYY, DD-MM-YYYY.")
            % (line_num, raw_val)
        )

    def _find_duplicate(self, vals, Individu):
        """Check if a citizen already exists based on CIN or reliable composite criteria.

        Never match on name alone, as multiple people can share identical names.
        """
        cin = (vals.get('cin') or '').strip()
        if cin:
            existing = Individu.search([('cin', '=', cin)], limit=1)
            if existing:
                return existing

        nom = (vals.get('nom') or '').strip()
        prenoms = (vals.get('prenoms') or '').strip()
        date_naissance = vals.get('date_naissance')
        commune = (vals.get('lieu_naissance_commune') or '').strip()

        # Reliable composite check: match on nom + date_naissance + (prenoms or commune)
        if nom and date_naissance and (prenoms or commune):
            domain = [
                ('nom', '=ilike', nom),
                ('date_naissance', '=', date_naissance),
            ]
            if prenoms:
                domain.append(('prenoms', '=ilike', prenoms))
            if commune:
                domain.append(('lieu_naissance_commune', '=ilike', commune))
            existing = Individu.search(domain, limit=1)
            if existing:
                return existing

        return False

    def _reopen_wizard(self):
        """Return action to re-open this wizard at its current state."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_back_to_mapping(self):
        """Go back from preview to mapping step."""
        self.ensure_one()
        self.state = 'mapping'
        return self._reopen_wizard()

    def action_back_to_upload(self):
        """Go back from mapping to upload step."""
        self.ensure_one()
        self.state = 'upload'
        return self._reopen_wizard()


class EtatCivilExportWizard(models.TransientModel):
    _name = 'etat.civil.export.wizard'
    _description = "Assistant d'exportation des citoyens"

    export_format = fields.Selection([
        ('csv', 'CSV'),
        ('xlsx', 'Excel (.xlsx)'),
        ('json', 'JSON'),
        ('xml', 'XML'),
        ('ods', 'ODS (LibreOffice)'),
    ], string='Format', default='csv', required=True)

    export_filter = fields.Selection([
        ('all', 'Tous les citoyens'),
        ('vivants', 'Vivants uniquement'),
        ('decedes', 'Décédés uniquement'),
    ], string='Filtre', default='all', required=True)

    include_fields = fields.Selection([
        ('essential', 'Champs essentiels (nom, CIN, sexe, naissance)'),
        ('full', 'Tous les champs'),
    ], string='Champs à exporter', default='essential', required=True)

    result_file = fields.Binary(string='Fichier exporté', readonly=True)
    result_file_name = fields.Char(string='Nom du fichier', readonly=True)
    state = fields.Selection([
        ('config', 'Configuration'),
        ('done', 'Terminé'),
    ], default='config', string='Étape')

    result_count = fields.Integer(string='Citoyens exportés', readonly=True)

    def _get_domain(self):
        domain = []
        if self.export_filter == 'vivants':
            domain.append(('statut_vital', '=', 'vivant'))
        elif self.export_filter == 'decedes':
            domain.append(('statut_vital', '=', 'decede'))
        return domain

    def _get_fields(self):
        essential = ['cin', 'nom', 'prenoms', 'sexe', 'date_naissance',
                     'lieu_naissance_commune', 'lieu_naissance_pays', 'nationalite_actuelle']
        full_fields = essential + [
            'date_naissance_estimee', 'domicile_actuel', 'profession_actuelle',
            'statut_vital', 'situation_matrimoniale',
        ]
        if self.include_fields == 'full':
            return full_fields
        return essential

    def _get_records(self):
        return self.env['etat.civil.individu'].search(self._get_domain())

    def _records_to_dicts(self, records, field_list):
        result = []
        for rec in records:
            d = {}
            for f in field_list:
                val = getattr(rec, f, None)
                if hasattr(val, 'strftime'):
                    val = val.strftime('%Y-%m-%d')
                elif isinstance(val, bool):
                    val = 'Oui' if val else 'Non'
                elif val is False:
                    val = ''
                else:
                    val = str(val) if val else ''
                d[f] = val
            result.append(d)
        return result

    def action_export(self):
        self.ensure_one()
        try:
            with self.env.cr.savepoint():
                return self._action_export()
        except Exception:
            _create_exchange_log(
                self.env,
                "export",
                "failed",
                False,
                self.export_format,
                error_rows=1,
            )
            raise

    def _action_export(self):
        self.ensure_one()
        records = self._get_records()
        field_list = self._get_fields()
        data = self._records_to_dicts(records, field_list)

        fmt = self.export_format
        if fmt == 'csv':
            content, fname = self._export_csv(data, field_list)
        elif fmt == 'xlsx':
            content, fname = self._export_xlsx(data, field_list)
        elif fmt == 'json':
            content, fname = self._export_json(data)
        elif fmt == 'xml':
            content, fname = self._export_xml(data)
        elif fmt == 'ods':
            content, fname = self._export_ods(data, field_list)
        else:
            raise UserError(_("Format d'exportation non pris en charge."))

        self.write({
            'result_file': base64.b64encode(content),
            'result_file_name': fname,
            'result_count': len(data),
            'state': 'done',
        })
        _create_exchange_log(
            self.env,
            "export",
            "success",
            fname,
            fmt,
            total_rows=len(data),
        )
        return self._reopen_wizard()

    def _export_csv(self, data, field_list):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=field_list, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(data)
        return output.getvalue().encode('utf-8-sig'), 'citoyens_export.csv'

    def _export_xlsx(self, data, field_list):
        try:
            import openpyxl
        except ImportError:
            raise UserError(_("La bibliothèque 'openpyxl' est nécessaire pour exporter en Excel. Installez-la avec : pip install openpyxl"))
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Citoyens'
        ws.append(field_list)
        for row in data:
            ws.append([row.get(f, '') for f in field_list])
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue(), 'citoyens_export.xlsx'

    def _export_json(self, data):
        content = json.dumps({'citoyens': data}, ensure_ascii=False, indent=2)
        return content.encode('utf-8'), 'citoyens_export.json'

    def _export_xml(self, data):
        import xml.etree.ElementTree as ET
        root = ET.Element('citoyens')
        for row in data:
            child = ET.SubElement(root, 'citoyen')
            for k, v in row.items():
                elem = ET.SubElement(child, k)
                elem.text = v
        buf = io.BytesIO()
        tree = ET.ElementTree(root)
        tree.write(buf, encoding='utf-8', xml_declaration=True)
        return buf.getvalue(), 'citoyens_export.xml'

    def _export_ods(self, data, field_list):
        try:
            from odf.opendocument import OpenDocumentSpreadsheet
            from odf.table import Table, TableRow, TableCell
            from odf.text import P
        except ImportError:
            raise UserError(_("La bibliothèque 'odfpy' est nécessaire pour exporter en ODS. Installez-la avec : pip install odfpy"))
        doc = OpenDocumentSpreadsheet()
        table = Table(name='Citoyens')
        # Header
        header_row = TableRow()
        for f in field_list:
            cell = TableCell()
            cell.addElement(P(text=f))
            header_row.addElement(cell)
        table.addElement(header_row)
        # Data
        for row in data:
            tr = TableRow()
            for f in field_list:
                cell = TableCell()
                cell.addElement(P(text=row.get(f, '')))
                tr.addElement(cell)
            table.addElement(tr)
        doc.spreadsheet.addElement(table)
        buf = io.BytesIO()
        doc.save(buf)
        return buf.getvalue(), 'citoyens_export.ods'

    def _reopen_wizard(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
