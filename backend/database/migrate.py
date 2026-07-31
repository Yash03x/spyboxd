#!/usr/bin/env python3
"""
Database utilities for local schema bootstrapping and SQLite -> PostgreSQL imports.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from sqlalchemy import Integer, MetaData, Table, create_engine, inspect, select, text
from sqlalchemy.engine import Engine

from .connection import DATABASE_URL, engine
from .models import Base

TABLE_COPY_ORDER = [
    "profiles",
    "profile_syncs",
    "profile_feed_states",
    "sync_datasets",
    "movies",
    "ratings",
    "reviews",
    "profile_films",
    "watch_events",
    "watchlist_items",
    "movie_lists",
    "movie_list_items",
    "profile_favorite_movies",
    "profile_follow_edges",
    "profile_source_activities",
    "profile_data_changes",
    "movie_enrichments",
    "movie_watch_providers",
    "scraping_jobs",
    "system_metrics",
]
LEGACY_SQLITE_PATH = Path(__file__).resolve().parents[2] / "data" / "letterboxd_analyzer.db"


def _load_table(engine_to_reflect: Engine, table_name: str) -> Table:
    metadata = MetaData()
    return Table(table_name, metadata, autoload_with=engine_to_reflect)


def _has_data(engine_to_check: Engine) -> bool:
    existing_tables = set(inspect(engine_to_check).get_table_names())
    with engine_to_check.connect() as connection:
        for table_name in TABLE_COPY_ORDER:
            if table_name not in Base.metadata.tables or table_name not in existing_tables:
                continue
            result = connection.execute(
                select(text("1")).select_from(Base.metadata.tables[table_name]).limit(1)
            ).first()
            if result is not None:
                return True
    return False


def _has_application_schema(engine_to_check: Engine) -> bool:
    existing_tables = set(inspect(engine_to_check).get_table_names())
    return bool(existing_tables.intersection(TABLE_COPY_ORDER))


def _truncate_target_tables(target_engine: Engine) -> None:
    with target_engine.begin() as connection:
        for table_name in reversed(TABLE_COPY_ORDER):
            if table_name in Base.metadata.tables:
                connection.execute(Base.metadata.tables[table_name].delete())


def _copy_table(source_engine: Engine, target_engine: Engine, table_name: str) -> int:
    source_table = _load_table(source_engine, table_name)
    target_table = Base.metadata.tables[table_name]
    source_columns = set(source_table.c.keys())
    transferable_columns = [
        column.name for column in target_table.columns if column.name in source_columns
    ]

    with source_engine.connect() as source_connection:
        rows = source_connection.execute(
            select(*(source_table.c[column] for column in transferable_columns))
        ).mappings().all()

    if not rows:
        return 0

    payload = [dict(row) for row in rows]
    with target_engine.begin() as target_connection:
        target_connection.execute(target_table.insert(), payload)

    return len(payload)


def _sync_postgres_sequences(target_engine: Engine) -> None:
    if target_engine.dialect.name != "postgresql":
        return

    with target_engine.begin() as connection:
        for table_name in TABLE_COPY_ORDER:
            table = Base.metadata.tables[table_name]
            pk_column = next(
                (
                    column
                    for column in table.columns
                    if column.primary_key and isinstance(column.type, Integer)
                ),
                None,
            )
            if pk_column is None:
                continue

            connection.execute(
                text(
                    f"""
                    SELECT setval(
                        pg_get_serial_sequence('{table_name}', '{pk_column.name}'),
                        COALESCE(MAX({pk_column.name}), 1),
                        MAX({pk_column.name}) IS NOT NULL
                    )
                    FROM {table_name}
                    """
                )
            )


def check_database() -> None:
    inspector = inspect(engine)
    print(f"Database URL: {DATABASE_URL}")
    print(f"Dialect: {engine.dialect.name}")
    print(f"Tables: {', '.join(inspector.get_table_names()) or '(none)'}")


def import_sqlite_to_current_database(source_path: str, truncate_target: bool = False) -> None:
    source_db_path = Path(source_path).expanduser().resolve()
    if not source_db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {source_db_path}")

    if engine.dialect.name != "postgresql":
        raise ValueError("Target DATABASE_URL must point to PostgreSQL before importing.")

    source_engine = create_engine(f"sqlite:///{source_db_path}", future=True)
    try:
        if not _has_application_schema(engine):
            raise ValueError(
                "Target database has no application tables. Run `alembic upgrade head` "
                "before importing data."
            )

        if truncate_target:
            _truncate_target_tables(engine)
        elif _has_data(engine):
            raise ValueError(
                "Target database already contains data. Re-run with --truncate-target "
                "if you want to replace it."
            )

        copied_rows = {}
        source_tables = set(inspect(source_engine).get_table_names())
        for table_name in TABLE_COPY_ORDER:
            if table_name not in source_tables:
                copied_rows[table_name] = 0
                continue
            copied_rows[table_name] = _copy_table(source_engine, engine, table_name)

        _sync_postgres_sequences(engine)

        print("SQLite import complete:")
        for table_name in TABLE_COPY_ORDER:
            print(f"  - {table_name}: {copied_rows[table_name]} rows")
    finally:
        source_engine.dispose()


def reset_database() -> bool:
    """Drop and recreate all tables (destructive)."""
    print("⚠️  WARNING: This will delete all data in the configured database.")
    confirm = input("Type 'YES' to confirm database reset: ")

    if confirm != "YES":
        print("❌ Database reset cancelled.")
        return False

    try:
        Base.metadata.drop_all(bind=engine)
        Base.metadata.create_all(bind=engine)
        print("✅ Database reset completed.")
        return True
    except Exception as exc:
        print(f"❌ Error resetting database: {exc}")
        return False


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Database maintenance helpers")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("check", help="Print the active database configuration")
    subparsers.add_parser("reset", help="Drop and recreate all tables")

    import_parser = subparsers.add_parser(
        "import-sqlite",
        help="Import data from the legacy SQLite database into the current DATABASE_URL",
    )
    import_parser.add_argument(
        "--source",
        default=str(LEGACY_SQLITE_PATH),
        help="Path to the source SQLite database",
    )
    import_parser.add_argument(
        "--truncate-target",
        action="store_true",
        help="Clear target tables before importing",
    )

    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 0
    if args.command == "check":
        check_database()
        return 0
    if args.command == "reset":
        return 0 if reset_database() else 1
    if args.command == "import-sqlite":
        import_sqlite_to_current_database(
            source_path=args.source,
            truncate_target=args.truncate_target,
        )
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
