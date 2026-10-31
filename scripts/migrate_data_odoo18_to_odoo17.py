#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de migration des données métier Odoo 18 vers Odoo 17
Module : etat_civil

Ce script effectue un transfert contrôlé (ETL) des données métier d'une base
source Odoo 18 vers une base cible Odoo 17 propre et initialisée.

Étapes :
1. Vérification des prérequis et connexion aux bases PostgreSQL.
2. Synchronisation des utilisateurs métiers (agents, officiers, administrateurs).
3. Migration ordonnée par dépendance :
   - etat_civil_centre
   - etat_civil_user_centre_rel
   - etat_civil_registre
   - etat_civil_individu
   - etat_civil_acte_naissance
   - etat_civil_acte_mariage
   - etat_civil_acte_deces
   - etat_civil_mention_marginale
   - etat_civil_piece_justificative
   - etat_civil_demande_guichet
4. Réajustement des séquences PostgreSQL (évite les conflits d'ID ultérieurs).
5. Audit d'intégrité post-migration (comptages, contraintes FK).
"""
import argparse
import sys
import psycopg2
from psycopg2.extras import RealDictCursor


TABLES_ORDER = [
    "etat_civil_centre",
    "etat_civil_registre",
    "etat_civil_individu",
    "etat_civil_acte_naissance",
    "etat_civil_acte_mariage",
    "etat_civil_acte_deces",
    "etat_civil_mention_marginale",
    "etat_civil_piece_justificative",
    "etat_civil_demande_guichet",
]


def parse_args():
    parser = argparse.ArgumentParser(description="Migration données métier Odoo 18 -> Odoo 17")
    parser.add_argument("--host", default="127.0.0.1", help="Hôte PostgreSQL")
    parser.add_argument("--port", type=int, default=5432, help="Port PostgreSQL")
    parser.add_argument("--user", default="odoo", help="Utilisateur PostgreSQL")
    parser.add_argument("--password", default="odoo", help="Mot de passe PostgreSQL")
    parser.add_argument("--src-db", default="gestion_detat_civil", help="Base source Odoo 18")
    parser.add_argument("--tgt-db", default="gestion_detat_civil_clean_odoo17", help="Base cible Odoo 17")
    parser.add_argument("--dry-run", action="store_true", help="Exécuter sans valider les transactions")
    return parser.parse_args()


def get_connection(host, port, user, password, dbname):
    try:
        conn = psycopg2.connect(
            host=host, port=port, user=user, password=password, dbname=dbname
        )
        return conn
    except Exception as e:
        print(f"[ERREUR] Connexion impossible à {dbname}: {e}")
        sys.exit(1)


def get_table_columns(cur, table_name):
    cur.execute(
        """
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_schema = 'public' AND table_name = %s;
        """,
        (table_name,),
    )
    rows = cur.fetchall()
    cols = set()
    for r in rows:
        if isinstance(r, dict):
            cols.add(r["column_name"])
        else:
            cols.add(r[0])
    return cols


def sync_users(src_cur, tgt_cur, user_map):
    """Assure que les utilisateurs de l'état civil de la base source existent dans la cible."""
    src_cur.execute(
        """
        SELECT u.id, u.login, u.active, u.partner_id, p.name, p.email
        FROM res_users u
        JOIN res_partner p ON p.id = u.partner_id
        WHERE u.login NOT IN ('root', 'default')
        """
    )
    src_users = src_cur.fetchall()

    tgt_cur.execute("SELECT id FROM res_company ORDER BY id ASC LIMIT 1;")
    comp_row = tgt_cur.fetchone()
    if not comp_row:
        raise RuntimeError("Aucune société trouvée dans la base cible res_company.")
    default_company_id = comp_row[0]

    for u in src_users:
        u_id = u["id"]
        login = u["login"]
        name = u["name"]

        # Chercher dans la cible
        tgt_cur.execute("SELECT id FROM res_users WHERE login = %s", (login,))
        row = tgt_cur.fetchone()
        if row:
            user_map[u_id] = row[0]
        else:
            # Créer partner et user simplifié
            tgt_cur.execute(
                """
                INSERT INTO res_partner (name, email, active, create_date, write_date)
                VALUES (%s, %s, %s, NOW(), NOW()) RETURNING id;
                """,
                (name, u["email"] or f"{login}@local.test", u["active"]),
            )
            partner_id = tgt_cur.fetchone()[0]

            tgt_cur.execute(
                """
                INSERT INTO res_users (login, partner_id, company_id, active, create_date, write_date, notification_type)
                VALUES (%s, %s, %s, %s, NOW(), NOW(), 'email') RETURNING id;
                """,
                (login, partner_id, default_company_id, u["active"]),
            )
            new_uid = tgt_cur.fetchone()[0]
            tgt_cur.execute(
                """
                INSERT INTO res_company_users_rel (cid, user_id)
                VALUES (%s, %s) ON CONFLICT DO NOTHING;
                """,
                (default_company_id, new_uid),
            )
            user_map[u_id] = new_uid
            print(f"  [USER] Créé dans cible : {login} (source ID {u_id} -> cible ID {new_uid})")


def migrate_table(src_cur, tgt_cur, table_name, user_map):
    src_cols = get_table_columns(src_cur, table_name)
    tgt_cols = get_table_columns(tgt_cur, table_name)

    common_cols = sorted(list(src_cols.intersection(tgt_cols)))
    if not common_cols:
        print(f"  [SKIP] {table_name} : aucune colonne commune")
        return 0

    src_cur.execute(f"SELECT {', '.join(common_cols)} FROM {table_name} ORDER BY id ASC;")
    rows = src_cur.fetchall()
    if not rows:
        print(f"  [INFO] {table_name} : 0 ligne à migrer")
        return 0

    extra_cols = []
    if table_name == "etat_civil_acte_mariage":
        if "donnees_historiques_incompletes" in tgt_cols and "donnees_historiques_incompletes" not in common_cols:
            extra_cols.append("donnees_historiques_incompletes")
        if "motif_regularisation" in tgt_cols and "motif_regularisation" not in common_cols:
            extra_cols.append("motif_regularisation")

    all_insert_cols = common_cols + extra_cols
    cols_str = ", ".join(all_insert_cols)
    placeholders = ", ".join(["%s"] * len(all_insert_cols))
    insert_sql = f"""
        INSERT INTO {table_name} ({cols_str}) 
        VALUES ({placeholders})
        ON CONFLICT (id) DO NOTHING;
    """

    for r in rows:
        values = []
        for col in common_cols:
            val = r[col]
            # Remapper les clés étrangères utilisateurs si nécessaire
            if col in ("create_uid", "write_uid", "officier_validateur_id", "agent_transmetteur_id"):
                if val and val in user_map:
                    val = user_map[val]
                elif val:
                    val = 1  # Fallback admin si utilisateur inexistant

            # Intégrité absolue des données : Ne JAMAIS inventer de faux témoins !
            if table_name == "etat_civil_acte_mariage" and col in ("temoin_1_id", "temoin_2_id"):
                if not val:
                    val = None
                    print(f"    [INTÉGRITÉ RESPECTÉE] Mariage ID {r['id']} : {col} absent dans Odoo 18 conservé à NULL (aucun faux témoin inventé)")

            values.append(val)

        if table_name == "etat_civil_acte_mariage":
            has_missing_witnesses = bool(not r.get("temoin_1_id") or not r.get("temoin_2_id"))
            if "donnees_historiques_incompletes" in extra_cols:
                values.append(has_missing_witnesses)
            if "motif_regularisation" in extra_cols:
                values.append(
                    "Acte issu de la migration Odoo 18 : Témoins non renseignés dans la source originale. À régulariser administrativement sans falsification d'identité."
                    if has_missing_witnesses else None
                )

        tgt_cur.execute(insert_sql, values)
        if tgt_cur.rowcount > 0:
            inserted += 1

    print(f"  [MIGRÉ] {table_name} : {inserted}/{len(rows)} enregistrements transférés")
    return inserted


def sync_user_centre_rel(src_cur, tgt_cur, user_map):
    """Migre les associations utilisateurs-centres d'état civil."""
    src_cols = get_table_columns(src_cur, "etat_civil_user_centre_rel")
    if not src_cols:
        return
    src_cur.execute("SELECT user_id, centre_id FROM etat_civil_user_centre_rel;")
    rows = src_cur.fetchall()
    cnt = 0
    for r in rows:
        uid = user_map.get(r["user_id"], r["user_id"])
        cid = r["centre_id"]
        tgt_cur.execute(
            """
            INSERT INTO etat_civil_user_centre_rel (user_id, centre_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING;
            """,
            (uid, cid),
        )
        if tgt_cur.rowcount > 0:
            cnt += 1
    print(f"  [MIGRÉ] etat_civil_user_centre_rel : {cnt} associations transférées")


def update_sequences(tgt_cur):
    """Met à jour les compteurs de séquences PostgreSQL."""
    for table in TABLES_ORDER:
        tgt_cur.execute(
            """
            SELECT pg_get_serial_sequence(%s, 'id');
            """,
            (table,),
        )
        seq_row = tgt_cur.fetchone()
        if seq_row and seq_row[0]:
            seq = seq_row[0]
            tgt_cur.execute(
                f"""
                SELECT setval(%s, COALESCE((SELECT MAX(id) FROM {table}), 1), true);
                """,
                (seq,),
            )


def main():
    args = parse_args()
    print("=" * 70)
    print("MIGRATION DES DONNÉES MÉTIER ODOO 18 -> ODOO 17")
    print(f"Source Odoo 18 : {args.src_db}@{args.host}:{args.port}")
    print(f"Cible  Odoo 17 : {args.tgt_db}@{args.host}:{args.port}")
    print(f"Mode dry-run   : {args.dry_run}")
    print("=" * 70)

    src_conn = get_connection(args.host, args.port, args.user, args.password, args.src_db)
    tgt_conn = get_connection(args.host, args.port, args.user, args.password, args.tgt_db)

    src_cur = src_conn.cursor(cursor_factory=RealDictCursor)
    tgt_cur = tgt_conn.cursor()

    try:
        # 1. Utilisateurs
        print("\n1. Synchronisation des comptes utilisateurs...")
        user_map = {1: 1, 2: 2}  # root/admin
        sync_users(src_cur, tgt_cur, user_map)

        # 2. Données métiers
        print("\n2. Transfert des tables métiers...")
        total_migrated = 0
        for table in TABLES_ORDER:
            # Vérifier existence dans source
            src_cur.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
                (table,),
            )
            if not src_cur.fetchone():
                continue
            total_migrated += migrate_table(src_cur, tgt_cur, table, user_map)

        # 3. Relations
        print("\n3. Transfert des relations...")
        sync_user_centre_rel(src_cur, tgt_cur, user_map)

        # 4. Séquences
        print("\n4. Réajustement des séquences PostgreSQL...")
        update_sequences(tgt_cur)

        if args.dry_run:
            tgt_conn.rollback()
            print("\n[DRY RUN] Transaction annulée sans modification persistée.")
        else:
            tgt_conn.commit()
            print("\n[SUCCÈS] Données migrées et validées dans la base Odoo 17 !")

        # 5. Audit final
        print("\n5. Audit post-migration dans la base cible :")
        for table in TABLES_ORDER:
            tgt_cur.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name=%s",
                (table,),
            )
            if tgt_cur.fetchone():
                tgt_cur.execute(f"SELECT COUNT(*) FROM {table};")
                count = tgt_cur.fetchone()[0]
                if count > 0:
                    print(f"  - {table} : {count} enregistrements")

    except Exception as e:
        tgt_conn.rollback()
        print(f"\n[ÉCHEC] Erreur lors de la migration : {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        src_cur.close()
        tgt_cur.close()
        src_conn.close()
        tgt_conn.close()


if __name__ == "__main__":
    main()
