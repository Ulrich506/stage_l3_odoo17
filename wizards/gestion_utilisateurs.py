from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


# Rôles métiers du module État Civil selon le workflow opérationnel :
# - Agent : crée et prépare les actes d'état civil.
# - Officier : valide et signe officiellement les actes créés.
# - Administrateur : supervise le système, les paramètres et les comptes.
_CIVIL_ROLE_REFS = (
    "etat_civil.group_etat_civil_agent",
    "etat_civil.group_etat_civil_officier",
    "etat_civil.group_etat_civil_admin",
)


class EtatCivilGestionUtilisateur(models.TransientModel):
    _name = "etat.civil.gestion.utilisateur"
    _description = "Gestion des comptes État Civil"

    mode = fields.Selection(
        [("create", "Créer un compte"), ("edit", "Gérer un compte")],
        required=True,
        default="create",
    )
    user_id = fields.Many2one(
        "res.users",
        string="Compte interne",
        domain=[("share", "=", False)],
    )
    name = fields.Char(string="Nom complet")
    login = fields.Char(string="Identifiant")
    email = fields.Char(string="Adresse e-mail")
    role = fields.Selection(
        [
            ("agent", "Agent d'état civil"),
            ("officier", "Officier d'état civil"),
            ("admin", "Administrateur d'état civil"),
        ],
        string="Rôle État Civil",
        help=(
            "Workflow métier proposé :\n"
            "- Agent : crée les actes et les dossiers ;\n"
            "- Officier : valide et signe les actes ;\n"
            "- Administrateur : supervise le système et les comptes."
        ),
        required=True,
        default="agent",
    )
    new_user_role = fields.Selection(
        [
            ("agent", "Agent d'état civil"),
            ("officier", "Officier d'état civil"),
        ],
        string="Rôle du nouveau compte",
        required=True,
        default="agent",
    )
    password = fields.Char(string="Mot de passe initial / nouveau mot de passe")
    active = fields.Boolean(string="Compte actif", default=True)
    centre_ids = fields.Many2many(
        "etat.civil.centre",
        string="Centres d'état civil autorisés",
        help="Périmètre territorial de l'agent ou de l'officier.",
    )

    def _ensure_admin(self):
        if not self.env.user.has_group("etat_civil.group_etat_civil_admin"):
            raise AccessError(
                "Seul un administrateur d'état civil peut gérer les comptes."
            )

    def _role_group(self, role):
        role_ref = {
            "agent": _CIVIL_ROLE_REFS[0],
            "officier": _CIVIL_ROLE_REFS[1],
            "admin": _CIVIL_ROLE_REFS[2],
        }.get(role)
        if not role_ref:
            raise ValidationError("Sélectionnez un rôle État Civil valide.")
        return self.env.ref(role_ref)

    def _validate_target(self, user):
        if not user or user.share:
            raise ValidationError(
                "La gestion des rôles État Civil est réservée aux comptes internes."
            )
        if (
            user.id == self.env.ref("base.user_admin").id
            or self.env.ref("base.group_system") in user.groups_id
        ):
            raise AccessError(
                "Les administrateurs techniques Odoo ne peuvent pas être gérés ici."
            )

    def _ensure_admin_remains(self, user, target_role, target_active):
        admin_group = self.env.ref(_CIVIL_ROLE_REFS[2])
        if user and admin_group in user.groups_id:
            if target_role != "admin" or not target_active:
                other_admins = self.env["res.users"].sudo().search_count(
                    [
                        ("id", "!=", user.id),
                        ("active", "=", True),
                        ("groups_id", "in", admin_group.id),
                    ]
                )
                if not other_admins:
                    raise UserError(
                        "Impossible de retirer ou désactiver le dernier administrateur "
                        "d'état civil actif."
                    )

    @api.onchange("user_id")
    def _onchange_user_id(self):
        if not self.user_id:
            return
        user = self.user_id
        self.name = user.name
        self.login = user.login
        self.email = user.email
        self.active = user.active
        self.password = False
        self.centre_ids = user.etat_civil_centre_ids
        if self.env.ref(_CIVIL_ROLE_REFS[2]) in user.groups_id:
            self.role = "admin"
        elif self.env.ref(_CIVIL_ROLE_REFS[1]) in user.groups_id:
            self.role = "officier"
        elif self.env.ref(_CIVIL_ROLE_REFS[0]) in user.groups_id:
            self.role = "agent"
        else:
            self.role = "agent"

    def action_save(self):
        self.ensure_one()
        self._ensure_admin()
        target_role = self.new_user_role if self.mode == "create" else self.role
        if self.mode == "create" and target_role not in ("agent", "officier"):
            raise ValidationError(
                "Un nouveau compte doit être créé comme agent ou officier d'état civil."
            )
        role_group = self._role_group(target_role)

        if not (self.name or "").strip() or not (self.login or "").strip():
            raise ValidationError("Le nom et l'identifiant sont obligatoires.")

        users = self.env["res.users"].sudo().with_context(no_reset_password=True)
        if self.mode == "create":
            if not (self.password or "").strip():
                raise ValidationError("Saisissez un mot de passe initial.")
            user = users.create(
                {
                    "name": self.name.strip(),
                    "login": self.login.strip(),
                    "email": (self.email or "").strip() or False,
                    "password": self.password,
                    "groups_id": [(6, 0, [role_group.id])],
                    "etat_civil_centre_ids": [(6, 0, self.centre_ids.ids)],
                }
            )
        else:
            user = self.user_id.sudo()
            self._validate_target(user)
            self._ensure_admin_remains(user, target_role, self.active)

            role_groups = [self.env.ref(group_ref).id for group_ref in _CIVIL_ROLE_REFS]
            values = {
                "name": self.name.strip(),
                "login": self.login.strip(),
                "email": (self.email or "").strip() or False,
                "active": self.active,
                "groups_id": [(3, group_id) for group_id in role_groups]
                + [(4, role_group.id)],
                "etat_civil_centre_ids": [(6, 0, self.centre_ids.ids)],
            }
            if self.password:
                values["password"] = self.password
            user.write(values)

        return {"type": "ir.actions.act_window_close"}
