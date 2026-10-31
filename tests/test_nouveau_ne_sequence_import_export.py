# -*- coding: utf-8 -*-
import base64
import csv
import io
import json
import xml.etree.ElementTree as ET

from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestNouveauNeSequenceImportExport(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Individu = cls.env["etat.civil.individu"]
        cls.ActeNaissance = cls.env["etat.civil.acte.naissance"]
        cls.ActeMariage = cls.env["etat.civil.acte.mariage"]
        cls.ActeDeces = cls.env["etat.civil.acte.deces"]

        cls.centre = cls.env["etat.civil.centre"].create({
            "code_centre": "CPT-TEST",
            "nom_centre": "Centre de Test",
            "commune": "Fianarantsoa",
        })

        cls.reg_naissance = cls.env["etat.civil.registre"].create({
            "annee": 2026,
            "type_registre": "naissance",
            "numero_volume": 1,
            "centre_id": cls.centre.id,
        })
        cls.reg_mariage = cls.env["etat.civil.registre"].create({
            "annee": 2026,
            "type_registre": "mariage",
            "numero_volume": 1,
            "centre_id": cls.centre.id,
        })
        cls.reg_deces = cls.env["etat.civil.registre"].create({
            "annee": 2026,
            "type_registre": "deces",
            "numero_volume": 1,
            "centre_id": cls.centre.id,
        })

    # ═══════════════════════════════════════════════════════════════════════
    # 1. NOUVEAU-NÉ : CRÉATION SANS CIN ET SANS PROFESSION
    # ═══════════════════════════════════════════════════════════════════════

    def test_01_creation_nouveau_ne_sans_cin_et_sans_profession(self):
        """Un nouveau-né doit pouvoir être créé sans CIN et sans profession."""
        enfant = self.Individu.create({
            "nom": "Rakoto",
            "prenoms": "Kely",
            "sexe": "M",
            "date_naissance": "2026-10-31",
            "lieu_naissance_commune": "Fianarantsoa",
            "lieu_naissance_pays": "Madagascar",
            "statut_vital": "vivant",
            "situation_matrimoniale": "celibataire",
        })
        self.assertTrue(enfant.id)
        self.assertFalse(enfant.cin, "La CIN doit rester vide pour un nouveau-né sans CIN")
        self.assertFalse(enfant.profession_actuelle, "Aucune profession ne doit être demandée")
        self.assertEqual(enfant.statut_vital, "vivant")
        self.assertEqual(enfant.situation_matrimoniale, "celibataire")

    def test_02_nouveau_ne_cin_format_et_unicite(self):
        """Si une CIN est fournie pour un enfant, son format (12 chiffres) et unicité sont validés."""
        # Format invalide (lettres ou mauvais nombre de chiffres)
        with self.assertRaises(ValidationError):
            self.Individu.create({
                "nom": "Rasoa",
                "prenoms": "Kely",
                "sexe": "F",
                "date_naissance": "2026-10-31",
                "cin": "12345ABC",
            })

        # Format valide (12 chiffres)
        enfant1 = self.Individu.create({
            "nom": "Rabe",
            "prenoms": "Soa",
            "sexe": "M",
            "date_naissance": "2026-10-31",
            "cin": "201999888777",
        })
        self.assertEqual(enfant1.cin, "201999888777")

        # Doublon de CIN -> ValidationError
        with self.assertRaises(ValidationError):
            self.Individu.create({
                "nom": "Rabe",
                "prenoms": "Doublon",
                "sexe": "M",
                "date_naissance": "2026-10-31",
                "cin": "201999888777",
            })

    def test_03_creation_adulte_avec_cin_et_profession(self):
        """Un citoyen adulte peut être créé avec CIN valide et profession."""
        adulte = self.Individu.create({
            "nom": "Randria",
            "prenoms": "Jean",
            "sexe": "M",
            "date_naissance": "1990-05-15",
            "cin": "101987654321",
            "profession_actuelle": "Enseignant",
            "domicile_actuel": "Fianarantsoa Centre",
        })
        self.assertEqual(adulte.cin, "101987654321")
        self.assertEqual(adulte.profession_actuelle, "Enseignant")

    # ═══════════════════════════════════════════════════════════════════════
    # 2. ACTE DE NAISSANCE ET SÉPARATION DES CIN PARENTS / DÉCLARANT / ENFANT
    # ═══════════════════════════════════════════════════════════════════════

    def test_04_cin_parents_distinctes_de_lenfant(self):
        """Les CIN du père, de la mère et du déclarant doivent être distinctes de celle de l'enfant."""
        pere = self.Individu.create({
            "nom": "Rakoto",
            "prenoms": "Père",
            "sexe": "M",
            "date_naissance": "1985-01-01",
            "cin": "101111111111",
        })
        mere = self.Individu.create({
            "nom": "Rasoa",
            "prenoms": "Mère",
            "sexe": "F",
            "date_naissance": "1988-02-02",
            "cin": "101222222222",
        })
        declarant = self.Individu.create({
            "nom": "Rabe",
            "prenoms": "Déclarant",
            "sexe": "M",
            "date_naissance": "1980-03-03",
            "cin": "101333333333",
        })
        enfant = self.Individu.create({
            "nom": "Rakoto",
            "prenoms": "Bébé",
            "sexe": "M",
            "date_naissance": "2026-10-31",
            "cin": False,  # Pas de CIN personnelle
        })

        acte = self.ActeNaissance.create({
            "registre_id": self.reg_naissance.id,
            "enfant_id": enfant.id,
            "pere_id": pere.id,
            "mere_id": mere.id,
            "declarant_id": declarant.id,
            "lieu_naissance": "Hôpital Principal",
            "lieu_accouchement": "hopital",
            "filiation": "legitime",
            "texte_integral_acte": "Acte de naissance de Rakoto Bébé...",
        })

        self.assertEqual(acte.cin_pere, "101111111111")
        self.assertEqual(acte.cin_mere, "101222222222")
        self.assertEqual(acte.cin_declarant, "101333333333")
        self.assertFalse(acte.enfant_id.cin)
        self.assertNotEqual(acte.enfant_id.cin, acte.cin_pere)
        self.assertNotEqual(acte.enfant_id.cin, acte.cin_mere)

    # ═══════════════════════════════════════════════════════════════════════
    # 3. NUMÉROTATION AUTOMATIQUE : PAS D'INCRÉMENTATION PRÉMATURÉE
    # ═══════════════════════════════════════════════════════════════════════

    def test_05_sequence_non_consommee_a_louverture_du_formulaire(self):
        """L'ouverture ou l'abandon d'un formulaire (new()) ne doit consommer aucun numéro."""
        # Instancier sans sauvegarder
        draft_form = self.ActeNaissance.new({
            "registre_id": self.reg_naissance.id,
            "lieu_accouchement": "hopital",
        })
        # Le numéro d'acte doit être vide dans le draft
        self.assertFalse(draft_form.numero_acte)

        # Enregistrer un premier acte
        enfant1 = self.Individu.create({
            "nom": "Premier",
            "sexe": "M",
            "date_naissance": "2026-10-31",
        })
        mere = self.Individu.create({
            "nom": "Mere",
            "sexe": "F",
            "date_naissance": "1995-01-01",
        })
        acte1 = self.ActeNaissance.create({
            "registre_id": self.reg_naissance.id,
            "enfant_id": enfant1.id,
            "mere_id": mere.id,
            "lieu_naissance": "Maternité",
            "texte_integral_acte": "Texte acte 1",
        })
        num1 = acte1.numero_acte
        self.assertTrue(num1.startswith("NAI/"))
        num1_seq = int(num1.split("/")[-1])

        # Ouvrir un autre formulaire puis l'abandonner
        draft2 = self.ActeNaissance.new({
            "registre_id": self.reg_naissance.id,
        })
        self.assertFalse(draft2.numero_acte)

        # Enregistrer un deuxième acte
        enfant2 = self.Individu.create({
            "nom": "Deuxieme",
            "sexe": "F",
            "date_naissance": "2026-10-31",
        })
        acte2 = self.ActeNaissance.create({
            "registre_id": self.reg_naissance.id,
            "enfant_id": enfant2.id,
            "mere_id": mere.id,
            "lieu_naissance": "Maternité",
            "texte_integral_acte": "Texte acte 2",
        })
        num2 = acte2.numero_acte
        num2_seq = int(num2.split("/")[-1])

        # Vérifier que les numéros se suivent rigoureusement (+1, aucun trou)
        self.assertEqual(num2_seq, num1_seq + 1, "Le compteur ne doit pas avoir sauté de numéro")

    def test_06_sequences_independantes_mariage_et_deces(self):
        """Chaque type d'acte (naissance, mariage, décès) possède sa propre séquence indépendante."""
        epoux = self.Individu.create({"nom": "Epoux", "sexe": "M", "date_naissance": "1990-01-01"})
        epouse = self.Individu.create({"nom": "Epouse", "sexe": "F", "date_naissance": "1992-01-01"})
        temoin1 = self.Individu.create({"nom": "T1", "sexe": "M", "date_naissance": "1980-01-01", "cin": "101999999001"})
        temoin2 = self.Individu.create({"nom": "T2", "sexe": "F", "date_naissance": "1982-01-01", "cin": "101999999002"})

        mariage = self.ActeMariage.create({
            "registre_id": self.reg_mariage.id,
            "conjoint_1_id": epoux.id,
            "conjoint_2_id": epouse.id,
            "temoin_1_id": temoin1.id,
            "temoin_2_id": temoin2.id,
            "date_mariage": "2026-10-31",
            "lieu_mariage": "Mairie",
            "texte_integral_acte": "Texte mariage",
        })
        self.assertTrue(mariage.numero_acte.startswith("MAR/"))

        defunt = self.Individu.create({"nom": "Defunt", "sexe": "M", "date_naissance": "1950-01-01"})
        declarant = self.Individu.create({"nom": "DeclarantD", "sexe": "M", "date_naissance": "1980-01-01"})
        deces = self.ActeDeces.create({
            "registre_id": self.reg_deces.id,
            "defunt_id": defunt.id,
            "declarant_id": declarant.id,
            "date_deces": "2026-10-31",
            "lieu_deces": "Hôpital",
            "texte_integral_acte": "Texte décès",
        })
        self.assertTrue(deces.numero_acte.startswith("DEC/"))

    # ═══════════════════════════════════════════════════════════════════════
    # 4. IMPORTATION : CSV, JSON, XML, XLSX, DOUBLONS
    # ═══════════════════════════════════════════════════════════════════════

    def test_07_import_csv(self):
        """Test importation d'un fichier CSV avec auto-mapping et création de citoyens."""
        csv_data = (
            "nom,prenom,sexe,date_naissance,cin,domicile\n"
            "Andria,Paul,Masculin,1995-04-10,101555444333,Antsirabe\n"
            "Razafy,Marie,Féminin,1998-08-20,101666777888,Fianarantsoa\n"
        )
        wizard = self.env["etat.civil.import.wizard"].create({
            "file_data": base64.b64encode(csv_data.encode("utf-8")),
            "file_name": "citoyens.csv",
            "duplicate_strategy": "skip",
        })
        self.assertEqual(wizard.file_format, "csv")

        # Étape 1 : détection
        wizard.action_detect_columns()
        self.assertEqual(wizard.state, "mapping")
        mapping = json.loads(wizard.column_mapping)
        self.assertEqual(mapping.get("nom"), "nom")
        self.assertEqual(mapping.get("prenom"), "prenoms")
        self.assertEqual(mapping.get("sexe"), "sexe")
        self.assertEqual(mapping.get("date_naissance"), "date_naissance")

        # Étape 2 : aperçu
        wizard.action_preview()
        self.assertEqual(wizard.state, "preview")

        # Étape 3 : importation
        wizard.action_import()
        self.assertEqual(wizard.state, "done")
        self.assertEqual(wizard.result_imported, 2)
        self.assertEqual(wizard.result_errors, 0)

        # Vérification des enregistrements créés
        p = self.Individu.search([("cin", "=", "101555444333")])
        self.assertTrue(p)
        self.assertEqual(p.nom, "Andria")
        self.assertEqual(p.prenoms, "Paul")
        self.assertEqual(p.sexe, "M")

    def test_08_import_json(self):
        """Test importation d'un fichier JSON."""
        json_content = json.dumps([
            {
                "nom": "JsonNom",
                "prenoms": "JsonPrenom",
                "sexe": "M",
                "date_naissance": "2001-02-03",
                "cin": "101888999000",
            }
        ])
        wizard = self.env["etat.civil.import.wizard"].create({
            "file_data": base64.b64encode(json_content.encode("utf-8")),
            "file_name": "citoyens.json",
        })
        self.assertEqual(wizard.file_format, "json")
        wizard.action_detect_columns()
        wizard.action_import()
        self.assertEqual(wizard.result_imported, 1)

        c = self.Individu.search([("cin", "=", "101888999000")])
        self.assertTrue(c)
        self.assertEqual(c.nom, "JsonNom")

    def test_09_import_xml(self):
        """Test importation d'un fichier XML."""
        xml_content = (
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<citoyens>\n'
            '  <citoyen>\n'
            '    <nom>XmlNom</nom>\n'
            '    <prenoms>XmlPrenom</prenoms>\n'
            '    <sexe>F</sexe>\n'
            '    <date_naissance>2002-03-04</date_naissance>\n'
            '    <cin>101777888999</cin>\n'
            '  </citoyen>\n'
            '</citoyens>'
        )
        wizard = self.env["etat.civil.import.wizard"].create({
            "file_data": base64.b64encode(xml_content.encode("utf-8")),
            "file_name": "citoyens.xml",
        })
        self.assertEqual(wizard.file_format, "xml")
        wizard.action_detect_columns()
        wizard.action_import()
        self.assertEqual(wizard.result_imported, 1)

        c = self.Individu.search([("cin", "=", "101777888999")])
        self.assertTrue(c)
        self.assertEqual(c.nom, "XmlNom")

    def test_10_import_xlsx(self):
        """Test importation d'un fichier Excel (.xlsx)."""
        import openpyxl
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.append(["nom", "prenoms", "sexe", "date_naissance", "cin"])
        ws.append(["XlsxNom", "XlsxPrenom", "M", "1999-12-31", "101444555666"])
        buf = io.BytesIO()
        wb.save(buf)

        wizard = self.env["etat.civil.import.wizard"].create({
            "file_data": base64.b64encode(buf.getvalue()),
            "file_name": "citoyens.xlsx",
        })
        self.assertEqual(wizard.file_format, "xlsx")
        wizard.action_detect_columns()
        wizard.action_import()
        self.assertEqual(wizard.result_imported, 1)

        c = self.Individu.search([("cin", "=", "101444555666")])
        self.assertTrue(c)
        self.assertEqual(c.nom, "XlsxNom")

    def test_11_detection_doublons_et_strategies(self):
        """Test détection des doublons avec stratégies skip, update et report."""
        # Créer un citoyen existant
        self.Individu.create({
            "nom": "Existant",
            "prenoms": "Test",
            "sexe": "M",
            "date_naissance": "1990-01-01",
            "cin": "101000111222",
            "domicile_actuel": "Ancien domicile",
        })

        # Données avec le même CIN et nouveau domicile
        csv_dup = (
            "nom,prenom,sexe,date_naissance,cin,domicile\n"
            "Existant,Test,M,1990-01-01,101000111222,Nouveau domicile\n"
        )

        # 1. Stratégie 'skip'
        w_skip = self.env["etat.civil.import.wizard"].create({
            "file_data": base64.b64encode(csv_dup.encode("utf-8")),
            "file_name": "dup.csv",
            "duplicate_strategy": "skip",
        })
        w_skip.action_detect_columns()
        w_skip.action_import()
        self.assertEqual(w_skip.result_duplicates, 1)
        self.assertEqual(w_skip.result_skipped, 1)
        self.assertEqual(w_skip.result_imported, 0)
        c = self.Individu.search([("cin", "=", "101000111222")])
        self.assertEqual(c.domicile_actuel, "Ancien domicile", "Le domicile ne doit pas avoir changé avec skip")

        # 2. Stratégie 'update'
        w_upd = self.env["etat.civil.import.wizard"].create({
            "file_data": base64.b64encode(csv_dup.encode("utf-8")),
            "file_name": "dup.csv",
            "duplicate_strategy": "update",
        })
        w_upd.action_detect_columns()
        w_upd.action_import()
        self.assertEqual(w_upd.result_updated, 1)
        c.refresh()
        self.assertEqual(c.domicile_actuel, "Nouveau domicile", "Le domicile doit être mis à jour avec update")

        # 3. Stratégie 'report'
        w_rep = self.env["etat.civil.import.wizard"].create({
            "file_data": base64.b64encode(csv_dup.encode("utf-8")),
            "file_name": "dup.csv",
            "duplicate_strategy": "report",
        })
        w_rep.action_detect_columns()
        w_rep.action_import()
        self.assertEqual(w_rep.result_duplicates, 1)
        self.assertTrue(w_rep.result_error_file, "Un fichier rapport doit être généré")

    # ═══════════════════════════════════════════════════════════════════════
    # 5. EXPORTATION DES CITOYENS : CSV, JSON, XML, XLSX
    # ═══════════════════════════════════════════════════════════════════════

    def test_12_exportation_citoyens(self):
        """Test exportation des citoyens dans différents formats."""
        export_w = self.env["etat.civil.export.wizard"].create({
            "export_format": "csv",
            "export_filter": "all",
            "include_fields": "essential",
        })
        export_w.action_export()
        self.assertEqual(export_w.state, "done")
        self.assertTrue(export_w.result_file)
        self.assertEqual(export_w.result_file_name, "citoyens_export.csv")

        # Test export JSON
        export_json = self.env["etat.civil.export.wizard"].create({
            "export_format": "json",
            "export_filter": "all",
        })
        export_json.action_export()
        self.assertTrue(export_json.result_file)
        self.assertEqual(export_json.result_file_name, "citoyens_export.json")

        # Test export XML
        export_xml = self.env["etat.civil.export.wizard"].create({
            "export_format": "xml",
            "export_filter": "all",
        })
        export_xml.action_export()
        self.assertTrue(export_xml.result_file)
        self.assertEqual(export_xml.result_file_name, "citoyens_export.xml")

        # Test export XLSX
        export_xlsx = self.env["etat.civil.export.wizard"].create({
            "export_format": "xlsx",
            "export_filter": "all",
        })
        export_xlsx.action_export()
        self.assertTrue(export_xlsx.result_file)
        self.assertEqual(export_xlsx.result_file_name, "citoyens_export.xlsx")
