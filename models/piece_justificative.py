from odoo import api, fields, models
from odoo.exceptions import AccessError, ValidationError


PIECE_TYPES = [
    ("declaration_hopital", "Déclaration de l’hôpital"),
    ("livret_famille", "Livret de famille"),
    ("residence_parent", "Certificat de résidence du parent"),
    ("cin_parent", "Photocopie CIN du parent"),
    ("celibat_conjoint_1", "Certificat de célibat du premier conjoint"),
    ("celibat_conjoint_2", "Certificat de célibat du second conjoint"),
    ("cin_conjoint_1", "Photocopie CIN du premier conjoint"),
    ("cin_conjoint_2", "Photocopie CIN du second conjoint"),
    ("cin_temoin_1", "Photocopie CIN du premier témoin"),
    ("cin_temoin_2", "Photocopie CIN du second témoin"),
    ("residence_conjoint_1", "Certificat de résidence du premier conjoint"),
    ("residence_conjoint_2", "Certificat de résidence du second conjoint"),
    ("residence_temoin_1", "Certificat de résidence du premier témoin"),
    ("residence_temoin_2", "Certificat de résidence du second témoin"),
    ("capacite_mariage_1", "Autorisation de capacité de mariage du premier conjoint"),
    ("capacite_mariage_2", "Autorisation de capacité de mariage du second conjoint"),
    ("passeport_1", "Passeport du premier conjoint étranger"),
    ("passeport_2", "Passeport du second conjoint étranger"),
    ("residence_etranger_1", "Certificat de résidence du premier conjoint étranger"),
    ("residence_etranger_2", "Certificat de résidence du second conjoint étranger"),
    ("cin_pere_reconnaissant", "Photocopie CIN du père reconnaissant"),
    ("residence_pere_reconnaissant", "Certificat de résidence du père reconnaissant"),
    ("lettre_fokontany_reconnaissance", "Lettre authentique du chef fokontany"),
    ("cin_enfant_majeur", "Photocopie CIN de l’enfant majeur"),
    ("residence_enfant_majeur", "Certificat de résidence de l’enfant majeur"),
    ("lettre_accord_famille", "Lettre d’accord de la famille"),
    ("lettre_fokontany_adoption", "Lettre authentique du chef fokontany"),
    ("cin_adoptant", "Photocopie CIN du parent adoptant"),
    ("residence_adoptant", "Certificat de résidence du parent adoptant"),
    ("cin_declarant_deces", "Photocopie CIN du déclarant du décès"),
    ("residence_declarant_deces", "Certificat de résidence du déclarant du décès"),
]


class EtatCivilPieceJustificative(models.Model):
    _name = "etat.civil.piece.justificative"
    _description = "Pièce justificative d’état civil"
    _order = "obligatoire desc, id"

    name = fields.Selection(PIECE_TYPES, string="Document", required=True)
    obligatoire = fields.Boolean(string="Obligatoire", default=True, readonly=True)
    etat = fields.Selection(
        [
            ("a_fournir", "À fournir"),
            ("recu", "Reçu"),
            ("verifie", "Reçu et vérifié"),
        ],
        string="État",
        required=True,
        default="a_fournir",
    )
    attachment_ids = fields.Many2many(
        "ir.attachment",
        "etat_civil_piece_attachment_rel",
        "piece_id",
        "attachment_id",
        string="Photos ou scans (facultatifs)",
    )
    acte_naissance_id = fields.Many2one(
        "etat.civil.acte.naissance", ondelete="cascade", index=True
    )
    acte_mariage_id = fields.Many2one(
        "etat.civil.acte.mariage", ondelete="cascade", index=True
    )
    acte_deces_id = fields.Many2one(
        "etat.civil.acte.deces", ondelete="cascade", index=True
    )
    mention_id = fields.Many2one(
        "etat.civil.mention.marginale", ondelete="cascade", index=True
    )

    @api.constrains(
        "acte_naissance_id",
        "acte_mariage_id",
        "acte_deces_id",
        "mention_id",
        "name",
        "etat",
    )
    def _check_owner_and_state(self):
        for record in self:
            owners = [
                record.acte_naissance_id,
                record.acte_mariage_id,
                record.acte_deces_id,
                record.mention_id,
            ]
            if sum(bool(owner) for owner in owners) != 1:
                raise ValidationError(
                    "Une pièce justificative doit appartenir à un seul dossier."
                )
            if record.etat == "verifie":
                if not record.obligatoire and not record.name:
                    raise ValidationError("Sélectionnez le document vérifié.")
            owner_field = next(
                (
                    field_name
                    for field_name, owner in zip(
                        (
                            "acte_naissance_id",
                            "acte_mariage_id",
                            "acte_deces_id",
                            "mention_id",
                        ),
                        owners,
                    )
                    if owner
                ),
                None,
            )
            if owner_field and record.name:
                duplicate = self.search(
                    [
                        (owner_field, "=", record[owner_field].id),
                        ("name", "=", record.name),
                        ("id", "!=", record.id),
                    ],
                    limit=1,
                )
                if duplicate:
                    raise ValidationError(
                        "Ce document figure déjà dans la liste du dossier."
                    )

    @api.model_create_multi
    def create(self, vals_list):
        if any(vals.get("etat") == "verifie" for vals in vals_list):
            self._ensure_verificateur()
        records = super().create(vals_list)
        owner_fields = (
            "acte_naissance_id",
            "acte_mariage_id",
            "acte_deces_id",
            "mention_id",
        )
        for record in records:
            owner_field = next(
                (field_name for field_name in owner_fields if record[field_name]),
                None,
            )
            if owner_field and record.name:
                record.with_context(etat_civil_sync_required=True).write({
                    "obligatoire": record.name in record[owner_field]._required_piece_codes(),
                })
        return records

    def write(self, vals):
        if vals.get("etat") == "verifie":
            self._ensure_verificateur()
        if "obligatoire" in vals and not self.env.context.get(
            "etat_civil_sync_required"
        ):
            raise AccessError(
                "Le caractère obligatoire d'une pièce est déterminé par la procédure."
            )
        result = super().write(vals)
        if "name" in vals or any(
            field_name in vals
            for field_name in (
                "acte_naissance_id",
                "acte_mariage_id",
                "acte_deces_id",
                "mention_id",
            )
        ):
            for record in self:
                owner = next(
                    (
                        record[field_name]
                        for field_name in (
                            "acte_naissance_id",
                            "acte_mariage_id",
                            "acte_deces_id",
                            "mention_id",
                        )
                        if record[field_name]
                    ),
                    False,
                )
                record.with_context(etat_civil_sync_required=True).write({
                    "obligatoire": bool(
                        owner and record.name in owner._required_piece_codes()
                    ),
                })
        return result

    def _ensure_verificateur(self):
        if not (
            self.env.user.has_group("etat_civil.group_etat_civil_officier")
            or self.env.user.has_group("base.group_system")
        ):
            raise AccessError("Seul un officier peut vérifier une pièce justificative.")
