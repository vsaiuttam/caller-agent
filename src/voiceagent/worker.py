"""Call worker entrypoint.

Runs the campaign dispatch loop. Separate process from the API so a slow or
crashed worker never takes the dashboard down with it, and so you can scale
the two independently — at volume you'll want several workers and one API.

    python -m voiceagent.worker

Set TELEPHONY=mock to run the whole loop against a scripted caller with no
phone line. That path exercises everything except the audio stack, which makes
it the right way to test prompt changes.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from .integrations.clients import DbSuppressionList, build_calendar, build_records
from .orchestrator.runner import CampaignRunner
from .providers import active, make_client, missing_key_message
from .storage import SessionLocal, engine, init_db
from .voice.pipeline import CallPipeline

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)
logger = logging.getLogger("voiceagent.worker")


def build_telephony():
    mode = os.getenv("TELEPHONY", "mock").lower()

    if mode == "livekit":
        from .voice.livekit_adapter import LiveKitTelephony

        logger.info("Telephony: LiveKit (live calls)")
        return LiveKitTelephony()

    if mode == "twilio":
        from .voice.twilio_adapter import TwilioTelephony

        logger.info("Telephony: Twilio (live PSTN calls)")
        return TwilioTelephony()

    if mode == "telnyx":
        from .voice.telnyx_adapter import TelnyxTelephony

        logger.info("Telephony: Telnyx (live PSTN calls)")
        return TelnyxTelephony()

    from .integrations.mocks import MockTelephony

    logger.warning("Telephony: MOCK — no real calls will be placed")
    return MockTelephony(
        answer_rate=float(os.getenv("MOCK_ANSWER_RATE", "0.8")),
        interrupting=os.getenv("MOCK_INTERRUPT", "").lower() in {"1", "true", "yes"},
    )


async def main() -> None:
    await init_db()

    provider = active()
    if provider is None:
        logger.error(missing_key_message())
        return

    client = make_client(provider)
    logger.info("Model provider: %s", provider.label)

    pipeline = CallPipeline(
        SessionLocal,
        client,
        build_telephony(),
        calendar=build_calendar(),
        records=build_records(),
        suppression=DbSuppressionList(SessionLocal),
    )

    runner = CampaignRunner(SessionLocal, pipeline.place_call)

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, runner.stop)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler for SIGTERM; the
            # KeyboardInterrupt path below covers Ctrl-C there.
            pass

    logger.info("Worker ready")
    try:
        await runner.run_forever()
    finally:
        # run_forever() drains in-flight calls first, so by here it's safe to
        # tear down the pool. Without this the process hangs on exit.
        await client.close()
        await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted")
