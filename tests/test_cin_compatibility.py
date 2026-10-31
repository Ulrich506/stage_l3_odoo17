from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestCINCompatibility(TransactionCase):
    def test_individu_accepts_legacy_api_key_and_stores_cin(self):
        person = self.env["etat.civil.individu"].create(
            {
                "nin": "101234567890",
                "nom": "Test CIN",
                "sexe": "M",
                "date_naissance": "2000-01-01",
            }
        )

        self.assertEqual(person.cin, "101234567890")
        person.write({"nin": "101234567891"})
        self.assertEqual(person.cin, "101234567891")

    def test_individu_rejects_invalid_cin_length(self):
        with self.assertRaises(ValidationError):
            self.env["etat.civil.individu"].create(
                {
                    "cin": "10123456789",
                    "nom": "Invalid CIN",
                    "sexe": "M",
                    "date_naissance": "2000-01-01",
                }
            )

    def test_guichet_accepts_legacy_citizen_nin_key(self):
        ticket = self.env["etat.civil.demande.guichet"].create(
            {
                "citoyen_nom": "Test CIN",
                "citoyen_nin": "101234567890",
                "type_acte": "naissance",
                "type_demande": "extrait",
            }
        )

        self.assertEqual(ticket.citoyen_cin, "101234567890")

        ticket.write({"citoyen_nin": "101234567891"})
        self.assertEqual(ticket.citoyen_cin, "101234567891")

    def test_guichet_status_changes_only_through_actions(self):
        ticket = self.env["etat.civil.demande.guichet"].create(
            {
                "citoyen_nom": "Test ticket",
                "type_acte": "naissance",
                "type_demande": "extrait",
            }
        )

        with self.assertRaises(UserError):
            ticket.write({"statut": "en_cours"})

        ticket.action_appeler_au_guichet()
        self.assertEqual(ticket.statut, "en_cours")
        ticket.action_marquer_traite()
        self.assertEqual(ticket.statut, "traite")
        self.assertTrue(ticket.processed_at)

    def test_birth_filiation_piece_rules_remain_distinct_and_neutral(self):
        birth = self.env["etat.civil.acte.naissance"].new(
            {"lieu_accouchement": "maison", "filiation": "legitime"}
        )
        established = birth._required_piece_codes()
        self.assertEqual(
            established,
            {"livret_famille", "residence_parent"},
        )

        birth.filiation = "illegitime"
        self.assertEqual(birth._required_piece_codes(), {"cin_parent"})
        labels = dict(self.env["etat.civil.acte.naissance"]._fields["filiation"].selection)
        self.assertEqual(labels["legitime"], "Filiation établie")
        self.assertEqual(labels["illegitime"], "Filiation à préciser")

    def test_marriage_foreign_documents_and_witness_requirements_are_explicit(self):
        marriage = self.env["etat.civil.acte.mariage"].new(
            {
                "conjoint_1_est_etranger": True,
                "conjoint_2_est_etranger": False,
            }
        )
        self.assertEqual(
            marriage._required_piece_codes(),
            {
                "cin_temoin_1",
                "cin_temoin_2",
                "passeport_1",
                "celibat_conjoint_2",
                "cin_conjoint_2",
                "residence_conjoint_2",
            },
        )

        marriage.conjoint_1_capacite_requise = True
        marriage.conjoint_1_residence_etranger_requise = True
        self.assertIn("capacite_mariage_1", marriage._required_piece_codes())
        self.assertIn("residence_etranger_1", marriage._required_piece_codes())
