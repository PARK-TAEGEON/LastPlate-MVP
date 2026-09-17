"""Atomic user_version migrations. Take a backup before opening a production v1 DB."""
from .schema import (SCHEMA_VERSION, TABLES, SOURCE_TYPES, provenance_columns, schema_statements,
                     policy_statements, current_model_forbidden_sql, inventory_source_conflict_sql)


class MigrationError(RuntimeError):
    """Migration cannot proceed without repairing the original database."""


def _v1_to_v2(connection):
    # Do not silently alter historical measurements to fit the new CHECK.
    invalid = connection.execute('''SELECT prediction_id FROM predictions
        WHERE lower_bound IS NOT NULL AND upper_bound IS NOT NULL
          AND NOT (lower_bound <= predicted_diners AND predicted_diners <= upper_bound)
        ORDER BY rowid LIMIT 10''').fetchall()
    if invalid:
        raise MigrationError("Out-of-interval v1 predictions; repair from source before retrying: "
                             + ", ".join(row[0] for row in invalid))
    # Preserve custom indexes/triggers on the table that must be rebuilt.
    extras = connection.execute("SELECT sql FROM sqlite_master WHERE tbl_name='predictions' "
                                "AND type IN ('index','trigger') AND sql IS NOT NULL").fetchall()
    for table in TABLES:
        for definition in provenance_columns().values():
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")
    connection.execute("ALTER TABLE operation_plans ADD COLUMN idempotency_key TEXT")
    connection.execute("CREATE UNIQUE INDEX operation_plan_retry ON operation_plans(prediction_id,idempotency_key)")

    # SQLite cannot add a table CHECK in place. Keep rowids for deterministic ties.
    statement = next(s for s in schema_statements() if s.startswith("CREATE TABLE IF NOT EXISTS predictions "))
    connection.execute(statement.replace("IF NOT EXISTS predictions ", "predictions_v2 ", 1))
    # Copy only columns that existed at this migration stage; later additions are nullable.
    columns = ",".join(row[1] for row in connection.execute("PRAGMA table_info(predictions)"))
    connection.execute(f"INSERT INTO predictions_v2(rowid,{columns}) SELECT rowid,{columns} FROM predictions")
    connection.execute("DROP TABLE predictions")
    connection.execute("ALTER TABLE predictions_v2 RENAME TO predictions")
    for (sql,) in extras:
        connection.execute(sql)
    # Existing rows deliberately remain UNKNOWN / 0 / UNVALIDATED, including old demos.
    # This prevents guessing provenance from names or free-form notes.


def _v2_to_v3(connection):
    bad_models = connection.execute("SELECT model_version FROM model_versions m WHERE "
                                    + current_model_forbidden_sql("m") + " ORDER BY rowid LIMIT 10").fetchall()
    if bad_models:
        raise MigrationError("Unsafe current model; review and archive before migration: "
                             + ", ".join(row[0] for row in bad_models))
    # Recover explicit reserved legacy source codes only where canonical provenance is unknown.
    # This is not a status approval; record_status is preserved.
    sources = ",".join(repr(v) for v in SOURCE_TYPES)
    connection.execute(f'''UPDATE inventory_snapshots
        SET source_type=UPPER(TRIM(source)),
            is_demo=CASE WHEN UPPER(TRIM(source))='DEMO' THEN 1 ELSE is_demo END
        WHERE source_type='UNKNOWN' AND UPPER(TRIM(source)) IN ({sources})''')
    conflicts = connection.execute("SELECT inventory_id FROM inventory_snapshots i WHERE "
                                    + inventory_source_conflict_sql("i") + " ORDER BY rowid LIMIT 10").fetchall()
    if conflicts:
        raise MigrationError("Conflicting inventory source; review before migration: "
                             + ", ".join(row[0] for row in conflicts))
    for statement in policy_statements():
        connection.execute(statement)


def _v3_to_v4(connection):
    from .schema_v4 import CONTRACT_COLUMNS, v4_statements
    reserved = ("feature_schemas", "model_deployments", "actual_correction_context", "actual_corrections")
    conflicts = connection.execute("SELECT name FROM sqlite_master WHERE name IN (?,?,?,?)", reserved).fetchall()
    if conflicts:
        raise MigrationError("Reserved v4 table already exists: " + ", ".join(row[0] for row in conflicts))
    present = {row[1] for row in connection.execute("PRAGMA table_info(predictions)")}
    for name, definition in CONTRACT_COLUMNS.items():
        if name not in present:
            connection.execute(f"ALTER TABLE predictions ADD COLUMN {name} {definition}")
    for statement in v4_statements(TABLES["actual_results"][1]):
        connection.execute(statement)


def _v4_to_v5(connection):
    from .schema_v5 import v5_statements
    conflicts = connection.execute("SELECT name FROM sqlite_master WHERE name IN ('training_runs','training_manifest_rows','integration_actor_events')").fetchall()
    if conflicts:
        raise MigrationError("Reserved v5 object already exists: " + ", ".join(row[0] for row in conflicts))
    for statement in v5_statements():
        connection.execute(statement)


MIGRATIONS = {1: _v1_to_v2, 2: _v2_to_v3, 3: _v3_to_v4, 4: _v4_to_v5}


def migrate(connection):
    """Initialize or migrate older supported schemas to v5 atomically; restore FK enforcement."""
    if connection.in_transaction:
        raise MigrationError("Migration requires a connection without an active transaction")
    # Required for SQLite's documented table rebuild procedure; outside transaction.
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        if version < 0 or version > SCHEMA_VERSION:
            raise MigrationError(f"Unsupported schema version: {version}")
        if version == 0:
            tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
            if tables:
                raise MigrationError("Unversioned nonempty database; refusing to guess schema")
            for statement in schema_statements():
                connection.execute(statement)
            version = SCHEMA_VERSION
        while version < SCHEMA_VERSION:
            MIGRATIONS[version](connection)
            version += 1
        if connection.execute("PRAGMA foreign_key_check").fetchone() is not None:
            raise MigrationError("Foreign key violations; migration rolled back")
        connection.execute(f"PRAGMA user_version={version}")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys=ON")
