"""The API process dials running campaigns.

On Render only the API runs, and Twilio's call webhooks land on it, so the
campaign dispatch loop runs inside the API's lifespan unless
DIALER_IN_API=false. Before this, campaigns set to Running never dialled.

Runs standalone (`python tests/test_dialer.py`) or under pytest.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.voiceagent import worker  # noqa: E402
from src.voiceagent.api import app as app_module  # noqa: E402


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
