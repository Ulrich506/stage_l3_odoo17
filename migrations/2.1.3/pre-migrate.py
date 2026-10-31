def migrate(cr, version):
    for table, old_column, new_column in (
        ("etat_civil_individu", "nin", "cin"),
        ("etat_civil_demande_guichet", "citoyen_nin", "citoyen_cin"),
    ):
        cr.execute(
            """
            SELECT column_name
              FROM information_schema.columns
             WHERE table_schema = current_schema()
               AND table_name = %s
               AND column_name IN (%s, %s)
            """,
            (table, old_column, new_column),
        )
        columns = {row[0] for row in cr.fetchall()}
        if old_column in columns and new_column not in columns:
            cr.execute(
                f'ALTER TABLE "{table}" RENAME COLUMN "{old_column}" TO "{new_column}"'
            )
        elif old_column in columns and new_column in columns:
            cr.execute(
                f"""
                SELECT COUNT(*)
                  FROM "{table}"
                 WHERE "{old_column}" IS NOT NULL
                   AND "{new_column}" IS NOT NULL
                   AND "{old_column}" != "{new_column}"
                """
            )
            if cr.fetchone()[0]:
                raise RuntimeError(
                    f"Conflicting {old_column}/{new_column} values in {table}; "
                    "manual review is required before migration."
                )
            cr.execute(
                f"""
                UPDATE "{table}"
                   SET "{new_column}" = COALESCE(NULLIF("{new_column}", ''), "{old_column}")
                 WHERE "{old_column}" IS NOT NULL
                """
            )
