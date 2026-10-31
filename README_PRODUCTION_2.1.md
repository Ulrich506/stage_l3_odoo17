# État Civil 2.1 — Odoo Web et application mobile

Odoo Web reste l’interface principale de gestion. L’application Flutter permet
aux agents de rechercher des citoyens, saisir des dossiers et consulter la file
du guichet via l’API du module.

## Correction principale

Le champ `qr_code_image` est déclaré dans le modèle abstrait officiel `etat.civil.acte.officiel` puis hérité par les trois actes :

- `etat.civil.acte.naissance`
- `etat.civil.acte.mariage`
- `etat.civil.acte.deces`

Le formulaire de mariage référence donc un champ présent dans la registry dès que le module est rechargé.

`qr_code_signature` contient maintenant la donnée de vérification QR (texte), alors que `qr_code_image` contient réellement l'image PNG encodée en base64. Cela évite le mélange de responsabilités de la version précédente.

## Parcours métier

- Les actes restent des brouillons jusqu’à leur validation par un officier.
- Les pièces obligatoires dépendent du type de dossier et des informations
  saisies. Leur scan ou leur photo est facultatif ; l’officier en vérifie la
  réception avant de valider.
- Une naissance à l’hôpital demande la déclaration de l’hôpital. Pour une
  naissance à la maison, la personne déclarante est requise. Les pièces de
  filiation légitime ou illégitime sont affichées selon le cas.
- Un mariage validé crée une mention pour chaque conjoint et conserve le suivi
  de notification à sa commune de naissance.
- Les mentions (reconnaissance, adoption simple, mariage, divorce, décès,
  veuvage et changement de nom) sont associées à la personne ou à l’acte visé.
  L’adoption complexe relève de la justice et n’est pas un parcours communal.

Les règles de procédure décrivent le fonctionnement demandé pour ce projet et
doivent être confirmées par la commune avant tout usage officiel.

Dans l’application Flutter, le Malagasy est sélectionné par défaut et le
français est disponible. La traduction des libellés est encore partielle ; les
textes d’Odoo dépendent également des traductions installées et de la langue du
compte utilisateur.

## Déploiement

Depuis le dossier `backend` :

```bash
export ODOO_BIN=/chemin/vers/odoo-bin
export ODOO_CONF=/chemin/vers/odoo.conf
export DB_NAME=gestion_detat_civil
./deploy_validate_etat_civil.sh
```

Optionnel :

```bash
export ODOO_SERVICE=odoo
export BACKUP_DIR=/var/backups/etat-civil
```

Le script : backup PostgreSQL → nettoyage `.pyc`/`__pycache__` → validation AST Python → diagnostic SQL → `-u etat_civil --stop-after-init` → validation registry → redémarrage.

## Modules Odoo à activer

Obligatoires pour ce module :

- `base`
- `web`
- `mail`

Optionnels selon ton environnement :

- `contacts`
- `documents`
- `auth_signup`
- `l10n_mg` si le module de localisation Madagascar est disponible dans ton installation et réellement utile à ton périmètre.

## Important

Ne supprime pas la base PostgreSQL pour corriger une erreur de vue. Mets à jour le module avec `-u etat_civil`, puis recharge les assets du navigateur.
