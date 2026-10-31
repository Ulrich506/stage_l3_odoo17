
# Correctif `qr_code_image` — État Civil 2.0.2

## Cause constatée

Dans le code fourni, `qr_code_image` est **déclaré dans le modèle abstrait**
`etat.civil.acte.officiel` puis hérité par `etat.civil.acte.mariage`.

`models/__init__.py` importe bien `acte_officiel` avant `acte_mariage`.

Le point très important est que l'archive fournie ne contient pas de fichier
`views/acte_mariage_views.xml` à l'emplacement annoncé dans l'erreur. Elle
contient `views/actes_mariage_deces_views.xml`. Cela signifie que le fichier
chargé par l'instance Odoo et l'archive analysée peuvent être de versions
différentes, ou que la base utilise encore une ancienne vue.

## Correction

Le module 2.0.2 sépare désormais les vues de mariage et de décès :

- `views/acte_mariage_views.xml`
- `views/acte_deces_views.xml`

et les référence explicitement dans `__manifest__.py`.

La déclaration du champ critique reste centralisée dans :

`models/acte_officiel.py`

```python
qr_code_image = fields.Binary(
    string="QR de vérification",
    readonly=True,
    attachment=False,
)
```

## Mise à jour recommandée

1. Sauvegarder PostgreSQL.
2. Remplacer le dossier `etat_civil`.
3. Supprimer `__pycache__` / `.pyc`.
4. Exécuter :
   `python odoo-bin -c odoo.conf -d NOM_BASE -u etat_civil --stop-after-init`
5. Redémarrer Odoo.
6. Exécuter le script de validation runtime.
7. Faire `Ctrl+Shift+R` dans le navigateur.

Le script racine `deploy_validate_qr_fix.sh` automatise ces étapes.

## Important

Ne supprimez pas manuellement les colonnes SQL de `ir_model_fields` ou de vos
tables métier pour résoudre ce problème. Si la registry Odoo est correcte,
le champ hérité sera présent sur les trois modèles d'actes.
