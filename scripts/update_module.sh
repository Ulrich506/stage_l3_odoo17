#!/bin/bash
# =============================================================================
# Script de mise à jour du module etat_civil — Odoo 18
# Usage : bash update_module.sh [nom_base_de_donnees]
# =============================================================================

set -e

ODOO_HOME="/opt/odoo/odoo"
ODOO_CONF="/home/ulrich/tous_les_projet/projet_stage_l3/backend/odoo.conf"
MODULE="etat_civil"

# --- Détection automatique du nom de BDD ---
if [ -n "$1" ]; then
    DB_NAME="$1"
else
    # Lire le nom de BDD depuis odoo.conf si présent
    DB_NAME=$(grep -E "^db_name\s*=" "$ODOO_CONF" 2>/dev/null | awk -F'=' '{print $2}' | xargs)
    if [ -z "$DB_NAME" ]; then
        echo "ERREUR: Impossible de détecter la base de données."
        echo "Usage: bash update_module.sh <nom_de_la_base>"
        exit 1
    fi
fi

echo "========================================================"
echo "  Mise à jour du module : $MODULE"
echo "  Base de données       : $DB_NAME"
echo "  Configuration Odoo    : $ODOO_CONF"
echo "========================================================"

# 1. Aller dans le répertoire Odoo
cd "$ODOO_HOME"

# 2. Mettre à jour le module (arrêt après initialisation)
python3 odoo-bin \
    --config="$ODOO_CONF" \
    -d "$DB_NAME" \
    -u "$MODULE" \
    --stop-after-init \
    --no-http

echo ""
echo "========================================================"
echo "  Module mis à jour avec succès !"
echo ""
echo "  IMPORTANT : Rechargez l'interface navigateur avec :"
echo "  Ctrl+Shift+R (Windows/Linux) ou Cmd+Shift+R (Mac)"
echo ""
echo "  Si les assets ne se chargent pas, allez dans :"
echo "  Paramètres > Technique > Interface > Actifs (Assets)"
echo "  et cliquez sur 'Régénérer tous les actifs'"
echo "========================================================"
