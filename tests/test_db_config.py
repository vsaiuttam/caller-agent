"""Database URLs as hosts hand them out, and moving data between databases.

engine_config() is what lets DATABASE_URL be pasted straight from Render or
Supabase: libpq query flags become asyncpg arguments, Supabase gets TLS, and
its transaction pooler gets prepared statements it can survive. db_tool.copy()
is checked SQLite-to-SQLite so it runs without a server.

Runs standalone (`python tests/test_db_config.py`) or under pytest.
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

import db_tool  # noqa: E402
from src.voiceagent.storage import (  # noqa: E402
    Base,
    Campaign,
    Contact,
    Setting,
    Suppression,
    engine_config,
)

REF = "abcdefghijklmnopqrst"
POOLER = f"postgresql://postgres.{REF}:p%40ss@aws-0-ap-south-1.pooler.supabase.com"


def test_sqlite_url_passes_through() -> None:
    url, kwargs = engine_config("sqlite+aiosqlite:///./voiceagent.db")
    assert url == "sqlite+aiosqlite:///./voiceagent.db"
    assert "pool_size" not in kwargs and "connect_args" not in kwargs, kwargs


def test_render_url_gets_the_async_driver_and_no_forced_ssl() -> None:
    url, kwargs = engine_config("postgres://u:pw@dpg-x-a/voiceagent")
    assert url == "postgresql+asyncpg://u:pw@dpg-x-a/voiceagent", url
    assert kwargs["connect_args"] == {}, kwargs
    assert kwargs["pool_pre_ping"] is True


def test_sslmode_is_translated_not_passed_to_asyncpg() -> None:
    url, kwargs = engine_config("postgresql://u:pw@db.example.com:5432/app?sslmode=require&application_name=x")
    assert "sslmode" not in url and "application_name=x" in url, url
    assert kwargs["connect_args"]["ssl"] == "require"


def test_supabase_session_pooler_requires_ssl_and_keeps_statement_cache() -> None:
    url, kwargs = engine_config(f"{POOLER}:5432/postgres")
    assert url == f"postgresql+asyncpg://postgres.{REF}:p%40ss@aws-0-ap-south-1.pooler.supabase.com:5432/postgres", url
    args = kwargs["connect_args"]
    assert args["ssl"] == "require"
    assert "statement_cache_size" not in args, args


def test_supabase_transaction_pooler_disables_prepared_statement_reuse() -> None:
    url, kwargs = engine_config(f"{POOLER}:6543/postgres?pgbouncer=true")
    assert "pgbouncer" not in url, url
    args = kwargs["connect_args"]
    assert args["statement_cache_size"] == 0
    first, second = args["prepared_statement_name_func"](), args["prepared_statement_name_func"]()
    assert first != second, "each prepared statement needs its own name behind the pooler"


def test_supabase_direct_host_requires_ssl() -> None:
    _, kwargs = engine_config(f"postgresql://postgres:pw@db.{REF}.supabase.co:5432/postgres")
    assert kwargs["connect_args"] == {"ssl": "require"}, kwargs


def test_pool_stays_under_the_supabase_free_client_cap() -> None:
    _, kwargs = engine_config(f"{POOLER}:5432/postgres")
    assert kwargs["pool_size"] + kwargs["max_overflow"] <= 15, kwargs


def test_copy_moves_every_row_and_refuses_a_filled_target() -> None:
    async def scenario(source: str, target: str) -> None:
        engine = create_async_engine(source)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        async with async_sessionmaker(engine, class_=AsyncSession)() as s:
            campaign = Campaign(id=str(uuid.uuid4()), name="Copy me", goal="Check the copy")
            s.add(campaign)
            await s.flush()
            s.add_all([
                Contact(id=str(uuid.uuid4()), campaign_id=campaign.id, full_name=f"C{i}", phone_e164=f"+1555000{i:04d}")
                for i in range(3)
            ])
            s.add(Suppression(phone_e164="+15550009999", reason="opted out"))
            s.add(Setting(key="k", value={"v": 1}))
            await s.commit()
        await engine.dispose()

        await db_tool.copy(source, target, replace=False)

        engine = create_async_engine(target)
        async with engine.connect() as conn:
            counts = await db_tool._counts(conn)
            name = await conn.scalar(select(Campaign.name))
            phones = (await conn.execute(select(Contact.phone_e164))).scalars().all()
            max_id = await conn.scalar(select(func.max(Suppression.id)))
        await engine.dispose()
        assert counts["campaigns"] == 1 and counts["contacts"] == 3, counts
        assert counts["suppressions"] == 1 and counts["settings"] == 1, counts
        assert name == "Copy me" and len(set(phones)) == 3, (name, phones)
        assert max_id is not None

        try:
            await db_tool.copy(source, target, replace=False)
        except SystemExit as exc:
            assert "--replace" in str(exc), exc
        else:
            raise AssertionError("copy into a filled target should refuse without --replace")

        await db_tool.copy(source, target, replace=True)
        engine = create_async_engine(target)
        async with engine.connect() as conn:
            assert (await db_tool._counts(conn))["contacts"] == 3
        await engine.dispose()

        # --merge keeps the target's own rows and adds only what it lacks.
        engine = create_async_engine(target)
        async with async_sessionmaker(engine, class_=AsyncSession)() as s:
            campaign_id = await s.scalar(select(Campaign.id))
            s.add(Contact(id=str(uuid.uuid4()), campaign_id=campaign_id, full_name="Target only", phone_e164="+15550001111"))
            await s.commit()
        await engine.dispose()
        engine = create_async_engine(source)
        async with async_sessionmaker(engine, class_=AsyncSession)() as s:
            campaign_id = await s.scalar(select(Campaign.id))
            s.add(Contact(id=str(uuid.uuid4()), campaign_id=campaign_id, full_name="Source only", phone_e164="+15550002222"))
            await s.commit()
        await engine.dispose()

        await db_tool.copy(source, target, replace=False, merge=True)
        engine = create_async_engine(target)
        async with engine.connect() as conn:
            counts = await db_tool._counts(conn)
            names = set((await conn.execute(select(Contact.full_name))).scalars())
        await engine.dispose()
        assert counts["contacts"] == 5 and counts["campaigns"] == 1, counts
        assert {"Target only", "Source only"} <= names, names

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        asyncio.run(scenario(
            f"sqlite+aiosqlite:///{Path(tmp, 'source.db').as_posix()}",
            f"sqlite+aiosqlite:///{Path(tmp, 'target.db').as_posix()}",
        ))


def _run_all() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"pass  {test.__name__}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())
