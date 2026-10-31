# -*- coding: utf-8 -*-
"""
Tests BRIQUE 5 : Rapports QWeb, QR codes, intégrité documentaire, chatter.

Ces tests vérifient :
- Le rendu correct des rapports PDF (naissance, mariage, décès) sous Odoo 17.
- La génération du hash SHA-256 et du QR code lors de la validation.
- La présence du disclaimer légal dans les rapports (non-substitution à la signature manuscrite).
- Le bon fonctionnement du chatter mail.thread.
"""
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestReportsAndSecurity(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.centre = cls.env["etat.civil.centre"].create(
            {
                "code_centre": "CPT-01",
                "nom_centre": "Centre Principal de Test",
                "commune": "Fianarantsoa",
            }
        )
        cls.registre_naissance = cls.env["etat.civil.registre"].create(
            {
                "annee": 2026,
                "type_registre": "naissance",
                "numero_volume": 1,
                "centre_id": cls.centre.id,
            }
        )
        cls.registre_mariage = cls.env["etat.civil.registre"].create(
            {
                "annee": 2026,
                "type_registre": "mariage",
                "numero_volume": 1,
                "centre_id": cls.centre.id,
            }
        )
        cls.registre_deces = cls.env["etat.civil.registre"].create(
            {
                "annee": 2026,
                "type_registre": "deces",
                "numero_volume": 1,
                "centre_id": cls.centre.id,
            }
        )

        cls.enfant = cls.env["etat.civil.individu"].create(
            {
                "nom": "Rakoto",
                "prenoms": "Soa Kely",
                "sexe": "F",
                "date_naissance": "2026-01-01",
                # Mineur : CIN non requise
            }
        )
        cls.mere = cls.env["etat.civil.individu"].create(
            {
                "nom": "Rasoa",
                "prenoms": "Bakoly",
                "sexe": "F",
                "date_naissance": "1995-05-10",
                "cin": "101995123456",
            }
        )
        cls.conjoint1 = cls.env["etat.civil.individu"].create(
            {
                "nom": "Rabe",
                "prenoms": "Jean",
                "sexe": "M",
                "date_naissance": "1990-03-15",
                "cin": "101990123456",
            }
        )
        cls.conjoint2 = cls.env["etat.civil.individu"].create(
            {
                "nom": "Razafy",
                "prenoms": "Marie",
                "sexe": "F",
                "date_naissance": "1992-07-20",
                "cin": "101992654321",
            }
        )
        cls.temoin1 = cls.env["etat.civil.individu"].create(
            {
                "nom": "Andria",
                "prenoms": "Hery",
                "sexe": "M",
                "date_naissance": "1988-02-14",
                "cin": "101988111222",
            }
        )
        cls.temoin2 = cls.env["etat.civil.individu"].create(
            {
                "nom": "Ranaivo",
                "prenoms": "Faly",
                "sexe": "M",
                "date_naissance": "1989-08-25",
                "cin": "101989333444",
            }
        )
        cls.defunt = cls.env["etat.civil.individu"].create(
            {
                "nom": "Rakotomalala",
                "prenoms": "Paul",
                "sexe": "M",
                "date_naissance": "1950-01-01",
                "cin": "101950123456",
            }
        )
        cls.declarant_deces = cls.env["etat.civil.individu"].create(
            {
                "nom": "Rakotomalala",
                "prenoms": "Fils Declarant",
                "sexe": "M",
                "date_naissance": "1975-06-10",
                "cin": "101975789456",
            }
        )

        officier_group = cls.env.ref("etat_civil.group_etat_civil_officier")
        cls.officier = cls.env["res.users"].create(
            {
                "name": "Officier Test Reports",
                "login": "officier_test_report@example.com",
                "email": "officier_test_report@example.com",
                "groups_id": [(6, 0, [officier_group.id, cls.env.ref("base.group_user").id])],
                "etat_civil_centre_ids": [(6, 0, [cls.centre.id])],
            }
        )

    def _render_report(self, xmlid, record_ids):
        """Helper compatible Odoo 17 pour rendre un rapport QWeb en HTML."""
        report = self.env.ref(xmlid)
        html, _ = report._render_qweb_html(report.id, record_ids)
        return html.decode("utf-8") if isinstance(html, bytes) else html

    def test_report_naissance_rendering_with_missing_optional_fields(self):
        """Le rapport de naissance doit se générer même sans père ni CIN pour mineur."""
        acte = self.env["etat.civil.acte.naissance"].create(
            {
                "registre_id": self.registre_naissance.id,
                "enfant_id": self.enfant.id,
                "mere_id": self.mere.id,
                # pere_id volontairement absent
                "lieu_naissance": "Fianarantsoa",
                "filiation": "illegitime",
                "lieu_accouchement": "hopital",
                "texte_integral_acte": "Le premier janvier deux mille vingt-six est née Soa Kely Rakoto.",
            }
        )

        html_str = self._render_report("etat_civil.action_report_acte_naissance", [acte.id])

        self.assertIn("Acte de Naissance", html_str)
        self.assertIn("Rakoto", html_str)
        self.assertIn("Soa Kely", html_str)
        self.assertIn("Rasoa", html_str)
        # Le père est absent → la section père ne doit pas apparaître
        self.assertNotIn("<strong>Père :</strong>", html_str)

    def test_report_mariage_rendering(self):
        """Le rapport de mariage doit se générer correctement avec tous les champs requis."""
        acte = self.env["etat.civil.acte.mariage"].create(
            {
                "registre_id": self.registre_mariage.id,
                "conjoint_1_id": self.conjoint1.id,
                "conjoint_2_id": self.conjoint2.id,
                "temoin_1_id": self.temoin1.id,
                "temoin_2_id": self.temoin2.id,
                "date_mariage": "2026-06-15",
                "lieu_mariage": "Mairie de Fianarantsoa",
                "regime_matrimonial": "communaute_biens",
                "texte_integral_acte": "Devant nous ont comparu publiquement...",
            }
        )

        html_str = self._render_report("etat_civil.action_report_acte_mariage", [acte.id])

        self.assertIn("Acte de Mariage", html_str)
        self.assertIn("Rabe", html_str)
        self.assertIn("Razafy", html_str)

    def test_report_deces_rendering(self):
        """Le rapport de décès doit se générer avec déclarant requis."""
        acte = self.env["etat.civil.acte.deces"].create(
            {
                "registre_id": self.registre_deces.id,
                "defunt_id": self.defunt.id,
                "declarant_id": self.declarant_deces.id,
                "date_deces": "2026-10-10",
                "lieu_deces": "Hôpital Tambohobe",
                "texte_integral_acte": "Le dix octobre deux mille vingt-six est décédé Paul Rakotomalala.",
            }
        )

        html_str = self._render_report("etat_civil.action_report_acte_deces", [acte.id])

        self.assertIn("Acte de Décès", html_str)
        self.assertIn("Rakotomalala", html_str)

    def test_qr_code_and_hash_generation_and_disclaimer_in_report(self):
        """Valide la génération du SHA-256, du QR code, et la présence du disclaimer légal."""
        acte = self.env["etat.civil.acte.naissance"].create(
            {
                "registre_id": self.registre_naissance.id,
                "enfant_id": self.enfant.id,
                "mere_id": self.mere.id,
                "lieu_naissance": "Fianarantsoa",
                "texte_integral_acte": "Texte officiel certifié pour validation du test.",
            }
        )

        # Avant validation : hash et QR absents
        self.assertFalse(acte.hash_empreinte_num)
        self.assertFalse(acte.qr_code_image)

        # L'officier vérifie les pièces puis valide
        acte.piece_ids.with_user(self.officier).write({"etat": "verifie"})
        acte.with_user(self.officier).action_valider_acte()

        # Après validation
        self.assertEqual(acte.statut, "valide")
        self.assertTrue(acte.hash_empreinte_num)
        self.assertEqual(len(acte.hash_empreinte_num), 64, "L'empreinte SHA-256 doit faire 64 caractères hex")
        self.assertTrue(acte.qr_code_image)

        # Rendu du rapport avec QR + hash
        html_str = self._render_report("etat_civil.action_report_acte_naissance", [acte.id])

        self.assertIn("Vérification d", html_str)
        self.assertIn("intégrité numérique", html_str)
        self.assertIn(acte.hash_empreinte_num, html_str)
        self.assertIn("data:image/png;base64,", html_str)
        # Disclaimer légal obligatoire
        self.assertIn("ne se substitue pas à la signature manuscrite", html_str)

    def test_chatter_and_messages(self):
        """Vérifie que mail.thread fonctionne : message_post crée bien un message dans le chatter."""
        acte = self.env["etat.civil.acte.naissance"].create(
            {
                "registre_id": self.registre_naissance.id,
                "enfant_id": self.enfant.id,
                "mere_id": self.mere.id,
                "lieu_naissance": "Fianarantsoa",
                "texte_integral_acte": "Texte officiel pour test du chatter.",
            }
        )

        msg = acte.message_post(
            body="Dossier vérifié par l'agent d'état civil.",
            message_type="comment",
            subtype_xmlid="mail.mt_comment",
        )
        self.assertTrue(msg)
        self.assertIn("Dossier vérifié", msg.body)
        comment_msgs = acte.message_ids.filtered(lambda m: m.message_type == "comment")
        self.assertEqual(len(comment_msgs), 1)

    # =========================================================================
    # P0 — Tests critiques ajoutés lors de la revue finale (Brique 7)
    # =========================================================================

    def test_integrity_hash_detects_tampering(self):
        """P0.2 — verify_integrity_hash() doit détecter toute altération du contenu après validation."""
        acte = self.env["etat.civil.acte.naissance"].create(
            {
                "registre_id": self.registre_naissance.id,
                "enfant_id": self.enfant.id,
                "mere_id": self.mere.id,
                "lieu_naissance": "Fianarantsoa",
                "texte_integral_acte": "Texte original officiel pour test d'intégrité.",
            }
        )
        # Valider l'acte pour générer le hash
        acte.piece_ids.with_user(self.officier).write({"etat": "verifie"})
        acte.with_user(self.officier).action_valider_acte()

        self.assertEqual(acte.statut, "valide")
        self.assertTrue(acte.hash_empreinte_num)
        original_hash = acte.hash_empreinte_num

        # Vérification positive : l'intégrité est confirmée
        is_valid, msg = acte.verify_integrity_hash()
        self.assertTrue(is_valid, "Le hash doit correspondre juste après validation")

        # Altération directe en base (simule une falsification)
        self.env.cr.execute(
            "UPDATE etat_civil_acte_naissance SET texte_integral_acte = %s WHERE id = %s",
            ("CONTENU FALSIFIÉ PAR UN ATTAQUANT", acte.id),
        )
        acte.invalidate_recordset(["texte_integral_acte"])

        # Vérification négative : la falsification doit être détectée
        is_valid_after, msg_after = acte.verify_integrity_hash()
        self.assertFalse(is_valid_after, "Le hash DOIT détecter la falsification du texte")
        self.assertIn("discordance", msg_after)

        # Le hash stocké ne doit pas avoir changé
        self.assertEqual(acte.hash_empreinte_num, original_hash)

    def test_historical_marriage_without_witnesses(self):
        """P0.1 — Un mariage historique avec donnees_historiques_incompletes=True
        peut exister sans témoins et son rapport doit se générer sans erreur."""
        acte_historique = self.env["etat.civil.acte.mariage"].create(
            {
                "registre_id": self.registre_mariage.id,
                "conjoint_1_id": self.conjoint1.id,
                "conjoint_2_id": self.conjoint2.id,
                # Pas de témoin : données historiques lacunaires
                "temoin_1_id": False,
                "temoin_2_id": False,
                "donnees_historiques_incompletes": True,
                "motif_regularisation": "Acte issu de la migration Odoo 18 : témoins non renseignés.",
                "date_mariage": "2010-03-15",
                "lieu_mariage": "Mairie Ancienne",
                "regime_matrimonial": "communaute_biens",
                "texte_integral_acte": "Acte historique incomplet transféré sans falsification.",
            }
        )

        # L'acte doit exister en base avec les témoins à False
        self.assertFalse(acte_historique.temoin_1_id)
        self.assertFalse(acte_historique.temoin_2_id)
        self.assertTrue(acte_historique.donnees_historiques_incompletes)

        # Le rapport doit se générer sans erreur
        html_str = self._render_report("etat_civil.action_report_acte_mariage", [acte_historique.id])
        self.assertIn("Acte de Mariage", html_str)

        # En revanche, un acte NORMAL sans témoins ne doit PAS pouvoir être transmis
        acte_normal = self.env["etat.civil.acte.mariage"].create(
            {
                "registre_id": self.registre_mariage.id,
                "conjoint_1_id": self.temoin1.id,  # Réutiliser d'autres individus
                "conjoint_2_id": self.temoin2.id,
                "temoin_1_id": False,
                "temoin_2_id": False,
                "date_mariage": "2026-06-15",
                "lieu_mariage": "Mairie Moderne",
                "regime_matrimonial": "separation_biens",
                "texte_integral_acte": "Acte normal sans témoins.",
            }
        )
        errors = acte_normal._check_specific_transmission_requirements()
        self.assertTrue(
            any("témoin" in e.lower() for e in errors),
            "Un acte normal sans témoins doit bloquer la transmission",
        )

    def test_territorial_security_isolation(self):
        """P0.3 — Un officier du Centre B ne peut ni lire ni valider un acte du Centre A."""
        centre_b = self.env["etat.civil.centre"].create(
            {
                "code_centre": "CTR-B-ISO",
                "nom_centre": "Centre Isolé B",
                "commune": "Autre Commune",
            }
        )
        officier_b = self.env["res.users"].create(
            {
                "name": "Officier Centre B",
                "login": "officier_centre_b_iso@test.com",
                "email": "officier_centre_b_iso@test.com",
                "groups_id": [
                    (6, 0, [self.env.ref("etat_civil.group_etat_civil_officier").id,
                             self.env.ref("base.group_user").id]),
                ],
                "etat_civil_centre_ids": [(6, 0, [centre_b.id])],
            }
        )

        # Créer un acte dans le Centre A (cls.centre)
        acte_a = self.env["etat.civil.acte.naissance"].create(
            {
                "registre_id": self.registre_naissance.id,
                "enfant_id": self.enfant.id,
                "mere_id": self.mere.id,
                "lieu_naissance": "Fianarantsoa",
                "texte_integral_acte": "Acte du centre A pour test d'isolation.",
            }
        )

        # L'officier B ne doit pas voir l'acte du Centre A (record rule)
        visible = self.env["etat.civil.acte.naissance"].with_user(officier_b).search(
            [("id", "=", acte_a.id)]
        )
        self.assertFalse(visible, "L'officier du Centre B ne doit pas voir les actes du Centre A")

        # Tentative de validation directe doit lever AccessError (compétence territoriale)
        acte_a.piece_ids.with_user(self.officier).write({"etat": "verifie"})
        with self.assertRaises(AccessError):
            acte_a.with_user(officier_b).action_valider_acte()

