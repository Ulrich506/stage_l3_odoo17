# État Civil — Odoo Web et application mobile

Odoo Web et l'application Flutter sont deux interfaces du même module serveur. PostgreSQL géré par Odoo est la source centrale des données ; le mobile utilise l'API Odoo et un cache SQLite local pour les consultations et brouillons hors connexion.

## Ce qui est intégré

- Menus réduits aux tâches d’état civil ; pas de tableau de bord statistique.
- Gestion des actes de naissance, mariage et décès.
- Gestion des citoyens / individus.
- Suivi des pièces requises par procédure ; photos ou scans facultatifs et vérification réservée à l’officier.
- Mentions marginales avec reconnaissance, adoption simple, mariage, divorce, décès, veuvage et changement de nom.
- Notifications de mariage à suivre vers les communes de naissance.
- File d'attente guichet partagée entre Odoo Web et l'application mobile.
- Recherche, filtres, regroupements et vues liste/kanban.
- Workflow : brouillon → validation → annulation → archivage.
- Annulation avec motif obligatoire dans une fenêtre de confirmation.
- Historique via le chatter Odoo.
- Empreinte SHA-256 et QR de vérification lors de la validation.
- Impression PDF des actes.
- Rôles : Agent, Officier, Administrateur d’état civil.
- Gestion des utilisateurs par l'administrateur État Civil, sans donner les droits techniques Odoo.

## Rôles et autorisations

- **Agent** : gère les citoyens, les brouillons d'actes et les tickets du guichet. Il peut consulter les mentions marginales, mais ne peut pas les créer ni les modifier. Il ne peut pas valider un acte.
- **Officier** : hérite des droits de l'agent et peut valider, annuler, archiver et, si nécessaire, marquer un acte comme rectifié. La rectification est une action facultative ; elle ne fait pas partie de la validation normale.
- **Administrateur d'état civil** : supervise le module et gère les centres, registres et comptes utilisateurs. Il hérite des droits de consultation et de préparation de l'agent, mais pas des droits métier de validation et de signature de l'officier. Depuis **État Civil → Administration → Utilisateurs**, il peut créer un compte interne ou modifier son rôle, ses coordonnées, son mot de passe et son état actif. Les comptes sont désactivés plutôt que supprimés, afin de conserver la traçabilité. Cet accès ne confère pas les paramètres techniques d'administration Odoo.

Les groupes supérieurs héritent des groupes inférieurs. Le statut d'un acte ne peut pas être modifié directement : il doit passer par les actions autorisées afin d'éviter qu'un agent contourne la validation d'un officier.

## File d'attente et API mobile

Les tickets sont stockés dans le modèle `etat.civil.demande.guichet`, avec un numéro attribué par une séquence Odoo. L'écran **État Civil → File d'attente** et l'application mobile utilisent les mêmes tickets via les routes authentifiées :

- `GET /api/v1/demandes-guichet`
- `POST /api/v1/demandes-guichet`
- `POST /api/v1/demandes-guichet/<id>/statut`

Créer un ticket ou changer son statut nécessite un compte Odoo membre du groupe Agent d'état civil. Les tickets définitivement traités ou annulés ne peuvent plus être modifiés.

## Installation

Copier `etat_civil` dans le dossier `custom_addons` indiqué dans `odoo.conf`, redémarrer Odoo, puis mettre à jour la liste des applications et installer/mettre à jour **Gestion d’État Civil**.

Commande typique :

```bash
./odoo-bin -c /chemin/odoo.conf -d gestion_detat_civil -u etat_civil --stop-after-init
```

La mise à jour vers la version 2.1.6 remplace les champs CIN à l'écran tout en
conservant les données des anciennes colonnes NIN dans les colonnes CIN.
L'API continue de lire les anciennes clés pendant la transition vers les
clients mobiles mis à jour. Elle supprime également de la base l'ancien menu
« Tableau de bord » et son action client, qui ne sont plus utilisés.
Elle active aussi la langue malagasy dans Odoo ; le fichier de traduction du
module couvre les menus et les principaux champs, et sera enrichi avec les
autres écrans au fur et à mesure. Les libellés de filiation sont neutres. Les
pièces des conjoints étrangers marquées « requises » sont déterminées dossier
par dossier ; les CIN des témoins restent requises, mais aucun certificat de
résidence témoin n'est imposé par défaut. Cette version corrige aussi la
compatibilité des anciennes clés CIN lors de la modification d'un ticket
guichet et traduit l'écran mobile du guichet en malagasy et en français. Les
changements de statut restent limités aux actions de workflow prévues.
Si vous utilisez le script `odoo.sh`, passez le nom du module :
`./odoo.sh update etat_civil`. Sans ce nom, Odoo ne met pas le module à jour.
Redémarrez ensuite Odoo et rechargez la page avec `Ctrl+Shift+R`.

## Connexion Odoo

Le login utilisateur se fait via `/web/login`. Le paramètre `admin_passwd` de `odoo.conf` est le **mot de passe maître** de gestion des bases et n’est pas le mot de passe de connexion de l’utilisateur Odoo.

Pour réinitialiser l’utilisateur administrateur :

```bash
./odoo-bin shell -c /chemin/odoo.conf -d gestion_detat_civil
```

Puis :

```python
user = env.ref('base.user_admin')
user.write({'password': 'CHOISIR_UN_MOT_DE_PASSE_FORT'})
```

## Modules Odoo

Obligatoires : `base`, `web`, `mail`.

Optionnels selon le périmètre : `contacts`, `documents`, `auth_signup`, `l10n_mg` lorsqu’ils sont disponibles et nécessaires.

## Remarque sécurité

Les modifications CORS globales de `ir.http` ont été supprimées : comme l’interface est désormais Odoo native, modifier toutes les routes Odoo n’apporte aucun bénéfice et augmente le risque de régression. L’API existante peut rester disponible pour de futures intégrations externes.

## Changelog 2.0.1

- **Correctif critique** : le formulaire "Acte de naissance" référençait un champ `date_naissance` inexistant sur le modèle (attribut `related=` invalide en vue XML). Odoo rejetait cette vue et affichait à la place le formulaire générique par défaut (les tableaux bruts "Nom de modèle de document associé / ID / Partenaire", "Nom du document / Type d'activité…", "Date / Sujet / Auteur…" que l'on voit à l'écran viennent des champs techniques `message_follower_ids`, `activity_ids`, `message_ids` hérités de `mail.thread`). Un vrai champ `date_naissance_enfant` (related) a été ajouté au modèle et la vue corrigée.
- Suppression des fichiers morts/doublons jamais chargés par le manifest, qui rendaient le code confus : `wizard/` (doublon de `wizards/`), `security/groups.xml` (doublon de `security.xml`), `views/dashboard.xml` et `views/search_views.xml` (doublons non utilisés), `static/src/scss/etat_civil.scss` (obsolète, classes CSS ne correspondant plus au template), `models/ir_http.py` (fichier vide jamais importé).
- `views/registry_actions.xml` corrigé (il pointait vers un assistant d'annulation inexistant) et réintégré dans `__manifest__.py` : clôturer/rouvrir un registre est maintenant aussi possible en masse depuis le menu Actions de la vue liste.
- Ajout de confirmations (`confirm=`) sur les actions sensibles : archivage d'un acte, clôture/réouverture d'un registre.
