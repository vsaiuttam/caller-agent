"""The API process dials running campaigns.

On Render only the API runs, and Twilio's call webhooks land on it, so the
campaign dispatch loop runs inside the API's lifespan unless
DIALER_IN_API=false. Before this, campaigns set to Running never dialled.

On startup the dialler also puts contacts stuck IN_PROGRESS with no live call
for more than 10 minutes back to PENDING (docs/v3-spec.md §2.4): a redeploy
that interrupts a call must not strand its contact forever.

Runs standalone (`python tests/test_dialer.py`) or under pytest.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_api_v2 import _temp_db  # noqa: E402

from src.voiceagent import storage, worker  # noqa: E402
from src.voiceagent.api import app as app_module  # noqa: E402
from src.voiceagent.orchestrator import runner as runner_module  # noqa: E402
from src.voiceagent.storage import CallStatus, ContactStatus  # noqa: E402


class FakeRunner:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.stopped = False
        self._stop = asyncio.Event()

    async def run_forever(self) -> None:
        self.started.set()
        await self._stop.wait()

    def stop(self) -> None:
        self.stopped = True
        self._stop.set()


class FakeClient:
    closed = False

    async def close(self) -> None:
        self.closed = True


def _lifespan_with(env: str | None, built) -> tuple[FakeRunner | None, bool]:
    """Run the app's lifespan with build_runner patched; report what happened."""
    saved_env, saved_build = os.environ.get("DIALER_IN_API"), worker.build_runner
    saved_load = app_module.auth.load_accounts
    if env is None:
        os.environ.pop("DIALER_IN_API", None)
    else:
        os.environ["DIALER_IN_API"] = env
    calls = []
    worker.build_runner = lambda: calls.append(1) or built

    async def no_accounts() -> None:
        return None

    app_module.auth.load_accounts = no_accounts

    async def scenario() -> bool:
        async with app_module.lifespan(app_module.app):
            runner = built[0] if built else None
            if runner is not None and env != "false":
                await asyncio.wait_for(runner.started.wait(), timeout=2)
        return bool(calls)

    try:
        attempted = asyncio.run(scenario())
    finally:
        worker.build_runner = saved_build
        app_module.auth.load_accounts = saved_load
        if saved_env is None:
            os.environ.pop("DIALER_IN_API", None)
        else:
            os.environ["DIALER_IN_API"] = saved_env
    return (built[0] if built else None), attempted


def test_the_api_runs_the_dialler_by_default_and_stops_it_on_shutdown() -> None:
    runner, client = FakeRunner(), FakeClient()
    ran, attempted = _lifespan_with(None, (runner, client))
    assert attempted, "the API never tried to start the dialler"
    assert ran.started.is_set(), "the dispatch loop never started"
    assert ran.stopped, "shutdown didn't stop the dispatch loop"
    assert client.closed, "shutdown didn't close the model client"


def test_dialer_in_api_false_leaves_dialling_to_a_separate_worker() -> None:
    runner = FakeRunner()
    _, attempted = _lifespan_with("false", (runner, FakeClient()))
    assert not attempted, "DIALER_IN_API=false still built a dialler"
    assert not runner.started.is_set()


def test_no_model_provider_means_no_dialler_but_the_api_still_starts() -> None:
    _, attempted = _lifespan_with(None, None)
    assert attempted


# ---------------------------------------------------------------------------
# Stale IN_PROGRESS recovery
# ---------------------------------------------------------------------------


async def _seed_stuck(sessions, now: datetime) -> None:
    """Contacts as a redeploy leaves them.

    stale-call:    IN_PROGRESS, its call started 30 minutes ago and never ended
    stale-no-call: IN_PROGRESS, created an hour ago, no call row (died before dialling)
    fresh:         IN_PROGRESS, its call started 2 minutes ago (may still be live)
    done:          COMPLETED long ago (not stuck)
    """
    async with sessions() as db:
        db.add(storage.Campaign(id="camp-1", name="Smile Dental", goal="Confirm Tuesday."))
        for contact_id, status, created in (
            ("stale-call", ContactStatus.IN_PROGRESS, now - timedelta(hours=1)),
            ("stale-no-call", ContactStatus.IN_PROGRESS, now - timedelta(hours=1)),
            ("fresh", ContactStatus.IN_PROGRESS, now - timedelta(hours=1)),
            ("done", ContactStatus.COMPLETED, now - timedelta(hours=1)),
        ):
            db.add(storage.Contact(
                id=contact_id, campaign_id="camp-1", full_name="Asha Rao",
                phone_e164="+15555550100", status=status, created_at=created,
            ))
        for call_id, contact_id, started, status in (
            ("call-stale", "stale-call", now - timedelta(minutes=30), CallStatus.CONNECTED),
            ("call-fresh", "fresh", now - timedelta(minutes=2), CallStatus.CONNECTED),
            ("call-done", "done", now - timedelta(minutes=50), CallStatus.COMPLETED),
        ):
            db.add(storage.Call(id=call_id, contact_id=contact_id, campaign_id="camp-1",
                                status=status, started_at=started))
        await db.commit()


async def _statuses(sessions) -> dict[str, ContactStatus]:
    async with sessions() as db:
        rows = (await db.execute(storage.Contact.__table__.select())).all()
    return {row.id: ContactStatus(row.status) if not isinstance(row.status, ContactStatus) else row.status
            for row in rows}


EXPECTED_AFTER_RECOVERY = {
    "stale-call": ContactStatus.PENDING,
    "stale-no-call": ContactStatus.PENDING,
    "fresh": ContactStatus.IN_PROGRESS,
    "done": ContactStatus.COMPLETED,
}


def test_contacts_count_as_stale_after_ten_minutes() -> None:
    assert runner_module.STALE_AFTER == timedelta(minutes=10), runner_module.STALE_AFTER


def test_stale_in_progress_contacts_go_back_to_pending() -> None:
    async def scenario():
        engine, sessions = await _temp_db()
        try:
            now = datetime.now(timezone.utc)
            await _seed_stuck(sessions, now)
            recovered = await runner_module.recover_stale_contacts(sessions, now=now)
            return recovered, await _statuses(sessions)
        finally:
            await engine.dispose()

    recovered, statuses = asyncio.run(scenario())
    assert statuses == EXPECTED_AFTER_RECOVERY, statuses
    assert recovered == 2, recovered


def test_recovery_logs_how_many_contacts_it_reset() -> None:
    records: list[logging.LogRecord] = []

    class Collect(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    async def scenario():
        engine, sessions = await _temp_db()
        try:
            now = datetime.now(timezone.utc)
            await _seed_stuck(sessions, now)
            return await runner_module.recover_stale_contacts(sessions, now=now)
        finally:
            await engine.dispose()

    handler = Collect(logging.INFO)
    logger = logging.getLogger(runner_module.__name__)
    saved_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        recovered = asyncio.run(scenario())
    finally:
        logger.removeHandler(handler)
        logger.setLevel(saved_level)
    messages = [r.getMessage() for r in records]
    assert any(str(recovered) in m.split() or f" {recovered} " in f" {m} " for m in messages), messages


def test_the_dialler_recovers_stale_contacts_when_it_starts() -> None:
    async def scenario():
        engine, sessions = await _temp_db()
        try:
            await _seed_stuck(sessions, datetime.now(timezone.utc))
            placed = []

            async def place_call(contact, campaign) -> None:
                placed.append(contact.id)

            dialler = runner_module.CampaignRunner(sessions, place_call)
            task = asyncio.create_task(dialler.run_forever())
            try:
                loop = asyncio.get_running_loop()
                deadline = loop.time() + 3
                while loop.time() < deadline:
                    if (await _statuses(sessions))["stale-call"] == ContactStatus.PENDING:
                        break
                    await asyncio.sleep(0.05)
            finally:
                dialler.stop()
                await asyncio.wait_for(task, 5)
            return await _statuses(sessions), placed
        finally:
            await engine.dispose()

    statuses, placed = asyncio.run(scenario())
    assert statuses == EXPECTED_AFTER_RECOVERY, statuses
    assert placed == [], "no campaign is running, so nothing should be dialled"


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
