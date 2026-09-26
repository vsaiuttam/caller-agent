"""Set up, check, and move the database — e.g. from Render Postgres to Supabase.

    python db_tool.py check URL
        Connects, creates any missing tables/columns, switches on row level
        security, and prints each table with its row count and RLS state.

    python db_tool.py copy SOURCE_URL TARGET_URL [--replace | --merge]
        Creates the schema on TARGET, then copies every row of every app table
        from SOURCE, parents before children, in one transaction: either all of
        it lands or none of it does. Refuses a target that already has rows
        unless told what to do with them: --replace empties the target's app
        tables first; --merge keeps them and adds only the source rows whose
        primary key the target doesn't have yet.

URLs are taken as the host gives them (postgres://…, postgresql://…?sslmode=…,
Supabase pooler URLs); the same translation the app uses applies. Quote them in
the shell — passwords often contain characters it would otherwise eat.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import Integer, func, inspect, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from src.voiceagent.storage import (
    Base,
    _add_missing_columns,
    _enable_row_level_security,
    engine_config,
)

TABLES = Base.metadata.sorted_tables  # parents before children
BATCH = 500


def _engine(url: str):
    url, kwargs = engine_config(url)
    kwargs.pop("pool_size", None)
    kwargs.pop("max_overflow", None)
    return create_async_engine(url, **kwargs)


def _describe(url: str) -> str:
    """The URL without its password, for printing."""
    from sqlalchemy.engine import make_url

    return make_url(engine_config(url)[0]).render_as_string(hide_password=True)


async def _prepare(engine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)
        await conn.run_sync(_enable_row_level_security)


async def _counts(conn) -> dict[str, int]:
    return {t.name: await conn.scalar(select(func.count()).select_from(t)) for t in TABLES}


async def check(url: str) -> None:
    engine = _engine(url)
    try:
        print(f"Connecting to {_describe(url)}")
        await _prepare(engine)
        async with engine.connect() as conn:
            version = await conn.scalar(text("SELECT version()")) if conn.dialect.name == "postgresql" else "sqlite"
            print(f"Server: {str(version).split(' on ')[0]}\n")
            counts = await _counts(conn)
            rls: dict[str, bool] = {}
            if conn.dialect.name == "postgresql":
                rows = await conn.execute(text(
                    "SELECT c.relname, c.relrowsecurity FROM pg_class c "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = current_schema() AND c.relkind = 'r'"
                ))
                rls = dict(rows.all())
        print(f"{'table':<14}{'rows':>8}  RLS")
        for name, n in counts.items():
            state = {True: "on", False: "OFF"}.get(rls.get(name), "n/a")
            print(f"{name:<14}{n:>8}  {state}")
    finally:
        await engine.dispose()


async def copy(source: str, target: str, replace: bool, merge: bool = False) -> None:
    src, dst = _engine(source), _engine(target)
    try:
        print(f"From {_describe(source)}\nTo   {_describe(target)}\n")
        await _prepare(dst)

        async with dst.connect() as conn:
            occupied = {k: v for k, v in (await _counts(conn)).items() if v}
        if occupied and not (replace or merge):
            sys.exit(f"Target already has rows ({occupied}). Re-run with --merge to add to them, "
                     "or --replace to empty it first.")

        async with src.connect() as s, dst.begin() as d:
            present = await s.run_sync(lambda c: {
                name: {col["name"] for col in inspect(c).get_columns(name)}
                for name in inspect(c).get_table_names()
            })
            if replace:
                for table in reversed(TABLES):
                    await d.execute(table.delete())

            for table in TABLES:
                if table.name not in present:
                    print(f"{table.name:<14} not in source, skipped")
                    continue
                # Older sources may lack newer columns; those take the target's defaults.
                columns = [c for c in table.columns if c.name in present[table.name]]
                rows = [dict(r) for r in (await s.execute(select(*columns))).mappings()]
                total = len(rows)
                if merge:
                    keys = [c.name for c in table.primary_key.columns]
                    have = {tuple(r) for r in (await d.execute(select(*table.primary_key.columns))).all()}
                    rows = [r for r in rows if tuple(r[k] for k in keys) not in have]
                for i in range(0, len(rows), BATCH):
                    await d.execute(table.insert(), rows[i:i + BATCH])
                skipped = f"  ({total - len(rows)} already there)" if merge else ""
                print(f"{table.name:<14}{len(rows):>8} rows{skipped}")

            if d.dialect.name == "postgresql":
                # Copied rows carry their ids; move serial counters past them.
                for table in TABLES:
                    for col in table.primary_key.columns:
                        if isinstance(col.type, Integer) and col.autoincrement in (True, "auto"):
                            await d.execute(text(
                                f"SELECT setval(pg_get_serial_sequence('\"{table.name}\"', '{col.name}'), "
                                f'COALESCE(MAX("{col.name}"), 0) + 1, false) FROM "{table.name}"'
                            ))
        print("\nDone.")
    finally:
        await src.dispose()
        await dst.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p_check = sub.add_parser("check", help="create/verify the schema and show table status")
    p_check.add_argument("url")
    p_copy = sub.add_parser("copy", help="copy all rows from one database to another")
    p_copy.add_argument("source")
    p_copy.add_argument("target")
    mode = p_copy.add_mutually_exclusive_group()
    mode.add_argument("--replace", action="store_true", help="empty the target's app tables first")
    mode.add_argument("--merge", action="store_true", help="keep the target's rows; add only missing ones")
    args = parser.parse_args()

    if args.command == "check":
        asyncio.run(check(args.url))
    else:
        asyncio.run(copy(args.source, args.target, args.replace, args.merge))


if __name__ == "__main__":
    main()
