from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEtatCivilRolePermissions(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.agent_group = cls.env.ref("etat_civil.group_etat_civil_agent")
        cls.officer_group = cls.env.ref("etat_civil.group_etat_civil_officier")
        cls.admin_group = cls.env.ref("etat_civil.group_etat_civil_admin")
        cls.agent = cls.env["res.users"].create(
            {
                "name": "Role test agent",
                "login": "role-test-agent",
                "email": "role-agent@example.test",
                "groups_id": [(6, 0, [cls.agent_group.id])],
            }
        )
        cls.officer = cls.env["res.users"].create(
            {
                "name": "Role test officer",
                "login": "role-test-officer",
                "email": "role-officer@example.test",
                "groups_id": [(6, 0, [cls.officer_group.id])],
            }
        )
        cls.admin = cls.env["res.users"].create(
            {
                "name": "Role test admin",
                "login": "role-test-admin",
                "groups_id": [(6, 0, [cls.admin_group.id])],
            }
        )
    def _create_birth_act(self):
        centre = self.env["etat.civil.centre"].sudo().create(
            {
                "code_centre": "ROLE-TEST",
                "nom_centre": "Centre de test des rôles",
                "commune": "Commune de test",
            }
        )
        registre = self.env["etat.civil.registre"].sudo().create(
            {
                "annee": 2026,
                "type_registre": "naissance",
                "numero_volume": 1,
                "centre_id": centre.id,
            }
        )
        self.agent.sudo().write({"etat_civil_centre_ids": [(4, centre.id)]})
        self.officer.sudo().write({"etat_civil_centre_ids": [(4, centre.id)]})
        enfant = self.env["etat.civil.individu"].with_user(self.agent).create(
            {
                "nom": "Enfant",
                "sexe": "M",
                "date_naissance": "2026-01-01",
            }
        )
        mere = self.env["etat.civil.individu"].with_user(self.agent).create(
            {
                "nom": "Mère",
                "sexe": "F",
                "date_naissance": "2000-01-01",
            }
        )
        return self.env["etat.civil.acte.naissance"].with_user(self.agent).create(
            {
                "numero_acte": "ROLE-1",
                "feuillet_numero": 1,
                "registre_id": registre.id,
                "texte_integral_acte": "Brouillon de test",
                "lieu_naissance": "Commune de test",
                "enfant_id": enfant.id,
                "mere_id": mere.id,
            }
        )

    def test_act_numbers_and_page_numbers_are_defaulted_by_act_type(self):
        centre = self.env["etat.civil.centre"].sudo().create(
            {
                "code_centre": "NUM-SEQ-TEST",
                "nom_centre": "Centre de test des séquences",
                "commune": "Commune de test",
            }
        )
        for type_registre, model_name, prefix in (
            ("mariage", "etat.civil.acte.mariage", "MAR/"),
            ("deces", "etat.civil.acte.deces", "DEC/"),
        ):
            registre = self.env["etat.civil.registre"].sudo().create(
                {
                    "annee": 2026,
                    "type_registre": type_registre,
                    "numero_volume": 1,
                    "centre_id": centre.id,
                }
            )
            draft = self.env[model_name].sudo().create(
                {
                    "registre_id": registre.id,
                    "texte_integral_acte": "Brouillon de test",
                    **(
                        {
                            "conjoint_1_id": self._create_person("Conjoint 1", "M", "1980-01-01").id,
                            "conjoint_2_id": self._create_person("Conjoint 2", "F", "1981-01-01").id,
                            "temoin_1_id": self._create_person("Témoin 1", "M", "1970-01-01").id,
                            "temoin_2_id": self._create_person("Témoin 2", "F", "1971-01-01").id,
                            "date_mariage": "2001-01-01",
                            "lieu_mariage": "Commune de test",
                            "regime_matrimonial": "communaute_biens",
                        }
                        if type_registre == "mariage"
                        else {
                            "defunt_id": self._create_person("Défunt", "M", "1960-01-01").id,
                            "declarant_id": self._create_person("Déclarant", "F", "1980-01-01").id,
                            "date_deces": "2000-01-01",
                            "lieu_deces": "Commune de test",
                        }
                    ),
                }
            )
            self.assertTrue(draft.numero_acte.startswith(prefix))
            self.assertEqual(draft.feuillet_numero, 1)

    def _create_person(self, name, sex, birth_date):
        return self.env["etat.civil.individu"].sudo().create(
            {
                "nom": name,
                "sexe": sex,
                "date_naissance": birth_date,
            }
        )

    def test_manual_act_number_is_preserved_and_folio_increments_per_register(self):
        first_act = self._create_birth_act()
        self.assertEqual(first_act.numero_acte, "ROLE-1")
        self.assertEqual(first_act.feuillet_numero, 1)

        enfant = self.env["etat.civil.individu"].with_user(self.agent).create(
            {
                "nom": "Deuxième enfant",
                "sexe": "F",
                "date_naissance": "2026-02-01",
            }
        )
        second_act = self.env["etat.civil.acte.naissance"].with_user(self.agent).create(
            {
                "registre_id": first_act.registre_id.id,
                "texte_integral_acte": "Deuxième brouillon de test",
                "lieu_naissance": "Commune de test",
                "enfant_id": enfant.id,
                "mere_id": first_act.mere_id.id,
            }
        )
        self.assertTrue(second_act.numero_acte.startswith("NAI/"))
        self.assertEqual(second_act.feuillet_numero, 2)

    def test_agent_transmits_to_the_assigned_officer(self):
        acte = self._create_birth_act()
        acte.piece_ids.with_user(self.agent).write({"etat": "recu"})

        acte.action_envoyer_validation()

        self.assertEqual(acte.statut, "en_attente")
        self.assertEqual(acte.officier_validateur_id, self.officer)
        self.assertEqual(acte.agent_transmetteur_id, self.agent)
        self.assertTrue(acte.date_transmission)

    def test_agent_cannot_assign_an_officer_from_another_centre(self):
        acte = self._create_birth_act()
        acte.piece_ids.with_user(self.agent).write({"etat": "recu"})
        other_centre = self.env["etat.civil.centre"].sudo().create(
            {
                "code_centre": "OTHER-ROLE-TEST",
                "nom_centre": "Autre centre de test",
                "commune": "Autre commune",
            }
        )
        other_officer = self.env["res.users"].sudo().create(
            {
                "name": "Officer from another centre",
                "login": "role-test-other-officer",
                "groups_id": [(6, 0, [self.officer_group.id])],
                "etat_civil_centre_ids": [(4, other_centre.id)],
            }
        )

        with self.assertRaises(AccessError):
            acte.action_envoyer_validation(officier=other_officer)

    def test_agent_cannot_read_acts_outside_assigned_centres(self):
        other_centre = self.env["etat.civil.centre"].sudo().create(
            {
                "code_centre": "OTHER-READ-TEST",
                "nom_centre": "Centre de lecture externe",
                "commune": "Autre commune",
            }
        )
        other_register = self.env["etat.civil.registre"].sudo().create(
            {
                "annee": 2026,
                "type_registre": "naissance",
                "numero_volume": 1,
                "centre_id": other_centre.id,
            }
        )
        other_act = self.env["etat.civil.acte.naissance"].sudo().create(
            {
                "numero_acte": "OTHER-READ-1",
                "feuillet_numero": 1,
                "registre_id": other_register.id,
                "texte_integral_acte": "Acte du centre externe",
                "enfant_id": self.env["etat.civil.individu"].sudo().create(
                    {
                        "nom": "Enfant externe",
                        "sexe": "M",
                        "date_naissance": "2026-01-01",
                    }
                ).id,
                "mere_id": self.env["etat.civil.individu"].sudo().create(
                    {
                        "nom": "Mère externe",
                        "sexe": "F",
                        "date_naissance": "2000-01-01",
                    }
                ).id,
            }
        )

        visible = self.env["etat.civil.acte.naissance"].with_user(self.agent).search(
            [("id", "=", other_act.id)]
        )
        self.assertFalse(visible)

    def test_agent_cannot_set_act_status_directly_or_validate(self):
        acte = self._create_birth_act()

        with self.assertRaises(UserError):
            acte.write({"statut": "valide"})
        with self.assertRaises(UserError):
            acte.action_valider_acte()

    def test_civil_admin_does_not_receive_officer_validation_rights_from_module_groups(self):
        acte = self._create_birth_act()

        self.assertTrue(self.admin.has_group("etat_civil.group_etat_civil_agent"))
        self.assertFalse(self.admin.has_group("etat_civil.group_etat_civil_officier"))
        with self.assertRaises(UserError):
            acte.with_user(self.admin).action_valider_acte()

    def test_officer_validation_locks_all_act_data_but_keeps_mentions_optional(self):
        acte = self._create_birth_act()
        acte.piece_ids.with_user(self.officer).write({"etat": "verifie"})
        acte.with_user(self.officer).action_valider_acte()

        with self.assertRaises(UserError):
            acte.with_user(self.agent).write({"lieu_naissance": "Modification interdite"})

        acte.with_user(self.officer).write(
            {
                "mention_ids": [
                    (
                        0,
                        0,
                        {
                            "name": "Rectification facultative",
                            "type_mention": "rectification",
                            "contenu": "Mention de correction officielle",
                        },
                    )
                ]
            }
        )
        self.assertEqual(len(acte.mention_ids), 1)

    def test_act_validation_requires_verified_documents(self):
        acte = self._create_birth_act()
        with self.assertRaises(ValidationError):
            acte.with_user(self.officer).action_valider_acte()
        acte.piece_ids.with_user(self.officer).write({"etat": "verifie"})
        acte.with_user(self.officer).action_valider_acte()
        self.assertEqual(acte.statut, "valide")

    def test_only_officer_can_verify_required_documents(self):
        acte = self._create_birth_act()
        with self.assertRaises(AccessError):
            acte.piece_ids.with_user(self.agent).write({"etat": "verifie"})

    def test_agent_can_read_but_cannot_create_marginal_mentions(self):
        with self.assertRaises(AccessError):
            self.env["etat.civil.mention.marginale"].with_user(self.agent).create(
                {
                    "name": "Mention réservée",
                    "type_mention": "rectification",
                    "contenu": "Test de restriction",
                    "acte_naissance_id": 1,
                }
            )

    def test_civil_admin_can_create_role_limited_internal_user(self):
        wizard = self.env["etat.civil.gestion.utilisateur"].with_user(
            self.admin
        ).create(
            {
                "mode": "create",
                "name": "Utilisateur créé par admin",
                "login": "role-created-agent",
                "new_user_role": "agent",
                "password": "Test-Only-Password-2026",
            }
        )
        wizard.action_save()
        user = self.env["res.users"].sudo().search(
            [("login", "=", "role-created-agent")], limit=1
        )
        self.assertTrue(user)
        self.assertFalse(user.share)
        self.assertIn(self.agent_group, user.groups_id)
        self.assertNotIn(self.officer_group, user.groups_id)
        self.assertNotIn(self.admin_group, user.groups_id)
        self.assertNotIn(self.env.ref("base.group_system"), user.groups_id)

    def test_civil_admin_can_create_an_officer_account(self):
        wizard = self.env["etat.civil.gestion.utilisateur"].with_user(
            self.admin
        ).create(
            {
                "mode": "create",
                "name": "Officier créé par admin",
                "login": "role-created-officer",
                "new_user_role": "officier",
                "password": "Test-Only-Password-2026",
            }
        )
        wizard.action_save()
        user = self.env["res.users"].sudo().search(
            [("login", "=", "role-created-officer")], limit=1
        )
        self.assertIn(self.officer_group, user.groups_id)
        self.assertIn(self.agent_group, user.groups_id)
        self.assertNotIn(self.admin_group, user.groups_id)

    def test_agent_cannot_open_user_management(self):
        with self.assertRaises(AccessError):
            self.env["etat.civil.gestion.utilisateur"].with_user(self.agent).create(
                {"mode": "create"}
            )

    def test_civil_admin_can_change_an_internal_users_role(self):
        wizard = self.env["etat.civil.gestion.utilisateur"].with_user(
            self.admin
        ).create(
            {
                "mode": "edit",
                "user_id": self.agent.id,
                "name": self.agent.name,
                "login": self.agent.login,
                "role": "officier",
                "active": True,
            }
        )
        wizard.action_save()
        self.agent.invalidate_recordset(["groups_id"])
        self.assertIn(self.officer_group, self.agent.groups_id)
        self.assertIn(self.agent_group, self.agent.groups_id)
        self.assertNotIn(self.admin_group, self.agent.groups_id)

    def test_cannot_disable_last_civil_admin(self):
        wizard = self.env["etat.civil.gestion.utilisateur"].with_user(
            self.admin
        ).create(
            {
                "mode": "edit",
                "user_id": self.admin.id,
                "name": self.admin.name,
                "login": self.admin.login,
                "role": "agent",
                "active": False,
            }
        )
        with self.assertRaises(UserError):
            wizard.action_save()

    def test_incomplete_act_cannot_be_transmitted(self):
        acte = self._create_birth_act()
        with self.assertRaises(ValidationError):
            acte.action_envoyer_validation()
        self.assertEqual(acte.statut, "brouillon")

    def test_double_transmission_is_rejected(self):
        acte = self._create_birth_act()
        acte.piece_ids.with_user(self.agent).write({"etat": "recu"})
        acte.action_envoyer_validation()
        with self.assertRaises(UserError):
            acte.action_envoyer_validation()
        self.assertEqual(acte.statut, "en_attente")

    def test_officer_can_return_for_correction_and_agent_can_resubmit(self):
        acte = self._create_birth_act()
        acte.piece_ids.with_user(self.agent).write({"etat": "recu"})
        acte.action_envoyer_validation()
        acte.with_user(self.officer).action_retourner_correction("Pièce illisible")
        self.assertEqual(acte.statut, "a_corriger")
        self.assertEqual(acte.motif_correction, "Pièce illisible")
        acte.with_user(self.agent).write({"texte_integral_acte": "Texte corrigé"})
        acte.with_user(self.agent).action_envoyer_validation()
        self.assertEqual(acte.statut, "en_attente")

    def test_officer_can_refuse_waiting_act(self):
        acte = self._create_birth_act()
        acte.piece_ids.with_user(self.agent).write({"etat": "recu"})
        acte.action_envoyer_validation()
        acte.with_user(self.officer).action_refuser_acte("Dossier hors compétence communale")
        self.assertEqual(acte.statut, "annule")
        self.assertIn("hors compétence", acte.motif_annulation)

    def test_validated_act_cannot_be_transmitted(self):
        acte = self._create_birth_act()
        acte.piece_ids.with_user(self.officer).write({"etat": "verifie"})
        acte.with_user(self.officer).action_valider_acte()
        with self.assertRaises(UserError):
            acte.with_user(self.agent).action_envoyer_validation()

    def test_officer_from_another_centre_cannot_validate(self):
        acte = self._create_birth_act()
        acte.piece_ids.with_user(self.agent).write({"etat": "recu"})
        acte.action_envoyer_validation()
        other_centre = self.env["etat.civil.centre"].sudo().create(
            {
                "code_centre": "OTHER-VALIDATE",
                "nom_centre": "Centre non compétent",
                "commune": "Autre commune",
            }
        )
        outsider = self.env["res.users"].sudo().create(
            {
                "name": "Officier extérieur",
                "login": "role-test-outsider-officer",
                "groups_id": [(6, 0, [self.officer_group.id])],
                "etat_civil_centre_ids": [(4, other_centre.id)],
            }
        )
        visible = self.env["etat.civil.acte.naissance"].with_user(outsider).search(
            [("id", "=", acte.id)]
        )
        self.assertFalse(visible)
        with self.assertRaises(AccessError):
            acte.with_user(outsider).action_valider_acte()

    def test_officer_full_lifecycle_annulation_and_archivage(self):
        acte = self._create_birth_act()
        acte.piece_ids.with_user(self.officer).write({"etat": "verifie"})
        acte.with_user(self.officer).action_valider_acte()
        self.assertEqual(acte.statut, "valide")

        # Un acte validé ne peut pas être archivé directement (doit être annulé d'abord)
        with self.assertRaises(UserError):
            acte.with_user(self.officer).action_archiver_acte()

        # Un agent ne peut pas annuler un acte (UserError via _ensure_officier)
        with self.assertRaises(UserError):
            acte.with_user(self.agent).action_annuler_acte("Motif agent interdit")

        # L'officier compétent annule l'acte
        acte.with_user(self.officer).action_annuler_acte("Erreur matérielle avérée sur la filiation")
        self.assertEqual(acte.statut, "annule")
        self.assertIn("Erreur matérielle", acte.motif_annulation)

        # L'officier compétent archive l'acte annulé
        acte.with_user(self.officer).action_archiver_acte()
        self.assertEqual(acte.statut, "archive")

    def test_cancellation_wizard(self):
        acte = self._create_birth_act()
        acte.piece_ids.with_user(self.officer).write({"etat": "verifie"})
        acte.with_user(self.officer).action_valider_acte()

        wizard = self.env["etat.civil.annulation.acte.wizard"].with_user(self.officer).create({
            "acte_type": "naissance",
            "acte_id": acte.id,
            "acte_display": acte.display_name,
            "motif": "Annulation légale via wizard",
        })
        wizard.action_confirmer()
        self.assertEqual(acte.statut, "annule")
        self.assertEqual(acte.motif_annulation, "Annulation légale via wizard")
