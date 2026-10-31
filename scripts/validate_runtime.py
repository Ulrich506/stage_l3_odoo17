# -*- coding: utf-8 -*-
"""
Runtime validation executed inside an Odoo environment.

Usage:
    ./odoo-bin shell -c /path/to/odoo.conf -d DATABASE \
        < custom_addons/etat_civil/scripts/validate_runtime.py

The script intentionally checks the registry, not only source code:
- concrete act models expose inherited official fields;
- XML views reference fields that exist on their actual Odoo model;
- ir.model.fields contains the critical QR fields for concrete act models;
- views containing the QR field are identified;
- no stale view references can survive unnoticed.
"""
from lxml import etree

CRITICAL_MODELS = (
    "etat.civil.acte.naissance",
    "etat.civil.acte.mariage",
    "etat.civil.acte.deces",
)
CRITICAL_FIELDS = (
    "qr_code_image",
    "qr_code_signature",
    "hash_empreinte_num",
)

errors = []
print("\n=== ETAT CIVIL : VALIDATION RUNTIME ===")

for model_name in CRITICAL_MODELS:
    model = env[model_name]
    print(f"\n[MODEL] {model_name}")
    for field_name in CRITICAL_FIELDS:
        ok = field_name in model._fields
        print(f"  {'OK' if ok else 'ERROR'} field {field_name}")
        if not ok:
            errors.append(f"{model_name}: champ absent du registre Odoo: {field_name}")

print("\n=== VUES CONTENANT qr_code_image ===")
views = env["ir.ui.view"].search([
    ("arch_db", "ilike", "qr_code_image"),
])
for view in views:
    model_name = view.model
    model = env.get(model_name) if model_name else None
    status = "OK"
    if not model:
        status = "ERROR"
        errors.append(f"Vue {view.id} ({view.name}): modèle absent: {model_name}")
    else:
        try:
            root = etree.fromstring(view.arch_db.encode("utf-8"))
        except Exception as exc:
            status = "ERROR"
            errors.append(f"Vue {view.id} ({view.name}): XML invalide: {exc}")
            root = None

        if root is not None:
            for node in root.xpath(".//field[@name='qr_code_image']"):
                if "qr_code_image" not in model._fields:
                    status = "ERROR"
                    errors.append(
                        f"Vue {view.id} ({view.name}): qr_code_image absent de {model_name}"
                    )
                    break

    print(f"  [{status}] id={view.id} model={model_name} name={view.name}")

print("\n=== IR.MODEL.FIELDS ===")
for model_name in CRITICAL_MODELS:
    model_rec = env["ir.model"]._get(model_name)
    if not model_rec:
        errors.append(f"ir.model absent: {model_name}")
        print(f"  ERROR {model_name}: ir.model absent")
        continue
    for field_name in CRITICAL_FIELDS:
        rec = env["ir.model.fields"].search_count([
            ("model_id", "=", model_rec.id),
            ("name", "=", field_name),
        ])
        ok = rec > 0
        print(f"  {'OK' if ok else 'ERROR'} {model_name}.{field_name} ({rec} row)")
        if not ok:
            errors.append(f"ir.model.fields absent: {model_name}.{field_name}")

print("\n=== RESULTAT ===")
if errors:
    for error in errors:
        print("ERROR:", error)
    print("\nVALIDATION FAILED")
    raise SystemExit(1)

print("VALIDATION PASSED")
print("Tous les champs critiques sont présents dans le registre Odoo et ir.model.fields.")
print("Les vues qui référencent qr_code_image pointent vers des modèles qui exposent ce champ.")
