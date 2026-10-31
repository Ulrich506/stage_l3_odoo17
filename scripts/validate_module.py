#!/usr/bin/env python3
"""Source-level validator for the critical qr_code_image inheritance chain."""
from pathlib import Path
import re
import sys

MODULE = Path(__file__).resolve().parents[1]
MODELS = MODULE / "models"
MANIFEST = MODULE / "__manifest__.py"

def classes():
    result = {}
    for path in MODELS.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(
            r"class\s+\w+\(models\.(?:Model|AbstractModel|TransientModel)\):(?P<body>.*?)(?=\nclass\s|\Z)",
            text, re.S
        ):
            body = match.group("body")
            name = re.search(r"_name\s*=\s*['\"]([^'\"]+)['\"]", body)
            if not name:
                continue
            inherit = re.search(r"_inherit\s*=\s*['\"]([^'\"]+)['\"]", body)
            fields = set(re.findall(r"^\s*([A-Za-z_]\w*)\s*=\s*fields\.", body, re.M))
            result[name.group(1)] = {
                "file": path.name,
                "inherit": inherit.group(1) if inherit else None,
                "fields": fields,
            }
    return result

def inherited_fields(model, defs, seen=None):
    seen = set() if seen is None else seen
    if model in seen:
        return set()
    seen.add(model)
    data = defs.get(model)
    if not data:
        return set()
    result = set(data["fields"])
    if data["inherit"]:
        result |= inherited_fields(data["inherit"], defs, seen)
    return result

def check():
    defs = classes()
    errors = []

    required_chain = {
        "etat.civil.acte.officiel": {"qr_code_image", "qr_code_signature", "hash_empreinte_num"},
        "etat.civil.acte.mariage": set(),
        "etat.civil.acte.naissance": set(),
        "etat.civil.acte.deces": set(),
    }
    for model, needed in required_chain.items():
        if model not in defs:
            errors.append(f"Modèle Python absent: {model}")
            continue
        for field in needed:
            if field not in defs[model]["fields"]:
                errors.append(f"{model}: champ critique absent: {field}")

    ticket_model = defs.get("etat.civil.demande.guichet")
    if not ticket_model:
        errors.append("Modèle Python absent: etat.civil.demande.guichet")
    else:
        for field in (
            "ticket_numero",
            "citoyen_nom",
            "type_acte",
            "type_demande",
            "statut",
            "priorite",
        ):
            if field not in ticket_model["fields"]:
                errors.append(f"etat.civil.demande.guichet: champ absent: {field}")

    for concrete in (
        "etat.civil.acte.mariage",
        "etat.civil.acte.naissance",
        "etat.civil.acte.deces",
    ):
        fields = inherited_fields(concrete, defs)
        for field in ("qr_code_image", "qr_code_signature", "hash_empreinte_num"):
            if field not in fields:
                errors.append(f"{concrete}: héritage incomplet pour {field}")

    init_text = (MODELS / "__init__.py").read_text(encoding="utf-8")
    if "from . import acte_officiel" not in init_text:
        errors.append("models/__init__.py: acte_officiel non importé")
    if "from . import acte_mariage" not in init_text:
        errors.append("models/__init__.py: acte_mariage non importé")
    if "from . import demande_guichet" not in init_text:
        errors.append("models/__init__.py: demande_guichet non importé")
    wizards_init = (MODULE / "wizards/__init__.py").read_text(encoding="utf-8")
    if "from . import gestion_utilisateurs" not in wizards_init:
        errors.append("wizards/__init__.py: gestion_utilisateurs non importé")

    manifest = MANIFEST.read_text(encoding="utf-8")
    for dep in ('"base"', '"mail"', '"web"'):
        if dep not in manifest:
            errors.append(f"__manifest__.py: dépendance absente {dep}")
    for xml in ("views/acte_mariage_views.xml", "views/acte_deces_views.xml"):
        if xml not in manifest:
            errors.append(f"__manifest__.py: XML non chargé {xml}")
    for xml in (
        "data/demande_guichet_sequence.xml",
        "views/demandes_guichet_views.xml",
        "views/gestion_utilisateurs_views.xml",
    ):
        if xml not in manifest:
            errors.append(f"__manifest__.py: XML non chargé {xml}")

    access = (MODULE / "security/ir.model.access.csv").read_text(encoding="utf-8")
    if "model_etat_civil_demande_guichet" not in access:
        errors.append("Droits d'accès du modèle demande guichet absents")
    if "model_etat_civil_gestion_utilisateur" not in access:
        errors.append("Droits du gestionnaire de comptes absents")

    user_management = (MODULE / "wizards/gestion_utilisateurs.py").read_text(encoding="utf-8")
    for required in ("_ensure_admin", "_ensure_admin_remains", "base.group_system"):
        if required not in user_management:
            errors.append(f"Gestion des comptes: contrôle de sécurité absent ({required})")

    act_model = (MODELS / "acte_officiel.py").read_text(encoding="utf-8")
    if 'if "statut" in vals and not internal_transition' not in act_model:
        errors.append("Le statut des actes peut être modifié directement")

    controller = (MODULE / "controllers/main.py").read_text(encoding="utf-8")
    for route in (
        "/api/v1/demandes-guichet",
        "/api/v1/demandes-guichet/<int:demande_id>/statut",
    ):
        if route not in controller:
            errors.append(f"Route API guichet absente: {route}")

    if errors:
        print("VALIDATION SOURCE FAILED")
        for e in errors:
            print(" -", e)
        return 1

    print("VALIDATION SOURCE OK")
    print(" - qr_code_image déclaré dans l'abstract officiel")
    print(" - héritage présent sur naissance/mariage/décès")
    print(" - imports présents")
    print(" - dépendances manifest présentes")
    print(" - vues mariage/décès présentes dans le manifest")
    print(" - modèle, droits, vues et API de file guichet présents")
    print(" - gestion des comptes réservée à l'administrateur État Civil")
    print(" - changements directs de statut des actes bloqués")
    return 0

if __name__ == "__main__":
    raise SystemExit(check())
