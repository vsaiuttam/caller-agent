"""The Twilio reply path — the part of a call a person actually waits on.

Drives the real webhook app over ASGI with a fake model standing in for the
LLM and a fake synthesizer standing in for Sarvam, so there is no Twilio
account, no network, and no API key involved. Runs standalone
(`python tests/test_twilio.py`) or under pytest.
"""

from __future__ import annotations

import asyncio
import sys
import time
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

from src.voiceagent.voice import twilio_adapter as tw  # noqa: E402
from src.voiceagent.voice.sarvam_voice import _pcm_to_wav, wav_seconds  # noqa: E402
from src.voiceagent.voice.session import CallSession  # noqa: E402


class FakeLLM:
    """Yields each reply's chunks with a pause between them, like a stream."""

    def __init__(self, replies: list[list[str]], *, gap: float = 0.0) -> None:
        self._replies = replies
        self._gap = gap
        self.yielded_at: dict[str, float] = {}

    def record(self, turn) -> None:
        pass

    async def generate(self):
        for i, chunk in enumerate(self._replies.pop(0) if self._replies else ["Goodbye."]):
            if i:
                await asyncio.sleep(self._gap)
            self.yielded_at[chunk] = time.perf_counter()
            yield chunk


class FakeTwilioClient:
    def __init__(self) -> None:
        self.hangups: list[str] = []

    def calls(self, sid: str):
        client = self

        class _Call:
            def update(self, **_):
                client.hangups.append(sid)

        return _Call()


def _open_call(room: str):
    state = tw._CallState()
    tw._active_calls[room] = state
    control = tw.TwilioControl(state, FakeTwilioClient())
    return state, tw.TwilioListener(state), tw.TwilioSpeaker(state), control


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=tw._build_webhook_app()), base_url="http://test"
    )


def _wav(seconds: float) -> bytes:
    return _pcm_to_wav(b"\x00\x00" * int(8000 * seconds), sample_rate=8000, channels=1, sample_width=2)


@contextmanager
def _voice(provider: str, synthesize=None):
    """Pin the voice provider — the package loads .env, which may say sarvam."""
    real = tw.VOICE_PROVIDER, tw._synthesize_sarvam
    tw.VOICE_PROVIDER = provider
    if synthesize is not None:
        tw._synthesize_sarvam = synthesize
    try:
        yield
    finally:
        tw.VOICE_PROVIDER, tw._synthesize_sarvam = real
        tw._audio_store.clear()


# ---------------------------------------------------------------------------


def test_the_reply_comes_back_on_the_same_webhook() -> None:
    """A ready reply is returned at once, whole, with no heartbeat pause.

    The old handler waited 2s and then answered with a fixed 3s <Pause>, so
    any turn slower than 2s kept the caller in silence for the rest of it.
    """

    async def scenario() -> None:
        room = "t-same-webhook"
        state, listener, speaker, control = _open_call(room)
        llm = FakeLLM([["Great.", "Does Tuesday at three work?"], ["Perfect. Goodbye."]])
        session = CallSession(
            llm=llm,  # type: ignore[arg-type]
            listener=listener,
            speaker=speaker,
            control=control,
            greeting="Hi Asha, it's the clinic.",
            max_duration_seconds=10,
        )
        run = asyncio.create_task(session.run())

        async with _http() as http:
            r = await http.post(f"/twilio/voice/{room}", data={"CallSid": "CA1"})
            assert "Hi Asha" in r.text and "<Gather" in r.text, r.text

            started = time.perf_counter()
            r = await http.post(f"/twilio/gather/{room}", data={"SpeechResult": "Yes."})
            assert time.perf_counter() - started < 1.0
            assert "Great." in r.text and "Does Tuesday at three work?" in r.text, r.text
            assert "<Pause" not in r.text, r.text

            # The goodbye plays in full and Twilio hangs up after it, rather
            # than our REST hangup cutting it off mid-word.
            r = await http.post(f"/twilio/gather/{room}", data={"SpeechResult": "Sure."})
            assert "Perfect. Goodbye." in r.text, r.text
            assert r.text.endswith("<Hangup/></Response>") and "<Gather" not in r.text, r.text

            await http.post(f"/twilio/status/{room}", data={"CallStatus": "completed"})

        transcript = await asyncio.wait_for(run, timeout=5)
        assert [t.role for t in transcript] == ["assistant", "user", "assistant", "user", "assistant"]
        assert transcript[2].latency_ms is not None
        assert control._client.hangups == [], "the call was hung up over the goodbye"

    with _voice("twilio"):
        asyncio.run(scenario())


def test_speech_is_synthesized_per_sentence_while_the_model_writes() -> None:
    """Sentence one's audio is being made before sentence two exists.

    Also: the greeting synthesized while the phone rang is not synthesized a
    second time, and each sentence is served as its own <Play>.
    """
    synthesized: list[tuple[str, float]] = []

    async def fake_synthesize(text: str) -> bytes:
        synthesized.append((text, time.perf_counter()))
        await asyncio.sleep(0.02)
        return _wav(1.0)

    async def scenario() -> None:
        tw.prefetch_speech("Hello from the clinic.")  # while the phone rings
        room = "t-pipelined"
        state, listener, speaker, control = _open_call(room)
        llm = FakeLLM([["First sentence.", "Second sentence."]], gap=0.2)
        session = CallSession(
            llm=llm,  # type: ignore[arg-type]
            listener=listener,
            speaker=speaker,
            control=control,
            greeting="Hello from the clinic.",
            max_duration_seconds=10,
        )
        run = asyncio.create_task(session.run())

        async with _http() as http:
            r = await http.post(f"/twilio/voice/{room}", data={"CallSid": "CA2"})
            assert r.text.count("<Play>") == 1, r.text

            r = await http.post(f"/twilio/gather/{room}", data={"SpeechResult": "Go on."})
            assert r.text.count("<Play>") == 2 and "<Say" not in r.text, r.text
            first_started = dict(synthesized)["First sentence."]
            assert first_started < llm.yielded_at["Second sentence."]

            # Two one-second clips, plus the fetch allowance, still to play.
            assert 1.9 < speaker.playback_remaining() <= 2.5

            audio_path = r.text.split("<Play>")[1].split("</Play>")[0]
            audio = await http.get(audio_path.replace(tw._webhook_base(), ""))
            assert audio.status_code == 200, audio.status_code
            assert audio.headers["content-type"] == "audio/wav"
            assert abs(wav_seconds(audio.content) - 1.0) < 0.01

            await http.post(f"/twilio/status/{room}", data={"CallStatus": "completed"})

        await asyncio.wait_for(run, timeout=5)
        greetings = [text for text, _ in synthesized if text == "Hello from the clinic."]
        assert len(greetings) == 1, synthesized

    with _voice("sarvam", fake_synthesize):
        asyncio.run(scenario())


def test_a_reply_the_caller_talked_over_is_not_played_to_them() -> None:
    """New speech makes any still-queued reply stale.

    Returning it would answer this utterance with the previous turn's reply,
    and every turn after would be one behind.
    """

    async def scenario() -> str:
        room = "t-stale"
        state, *_ = _open_call(room)
        state.response_queue.put_nowait(
            tw._Reply(segments=[("Sorry — are you still there?", None)], seconds=1.0)
        )

        async def session_answers() -> None:
            heard = await state.speech_queue.get()
            await state.response_queue.put(
                tw._Reply(segments=[(f"You said {heard}", None)], seconds=1.0)
            )

        answering = asyncio.create_task(session_answers())
        async with _http() as http:
            r = await http.post(f"/twilio/gather/{room}", data={"SpeechResult": "I'm here"})
        await answering
        return r.text

    twiml = asyncio.run(scenario())
    assert "You said I&apos;m here" in twiml, twiml
    assert "still there" not in twiml, twiml


def test_stale_reply_cleanup_keeps_the_goodbye_and_the_end_signal() -> None:
    async def scenario() -> list:
        state = tw._CallState()
        stale = tw._Reply(segments=[("stale", None)], seconds=1.0)
        goodbye = tw._Reply(segments=[("Goodbye.", None)], seconds=1.0, final=True)
        for item in (stale, goodbye, None):
            state.response_queue.put_nowait(item)
        tw._drop_stale_replies(state)
        return [state.response_queue.get_nowait() for _ in range(state.response_queue.qsize())]

    kept = asyncio.run(scenario())
    assert len(kept) == 2 and kept[0].final and kept[1] is None, kept


# ---------------------------------------------------------------------------


def _run_all() -> int:
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
