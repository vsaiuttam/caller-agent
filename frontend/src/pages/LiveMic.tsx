/**
 * Take the call yourself.
 *
 * The simulator answers "does this campaign hold up against a difficult
 * person?" with a model playing the person. This answers a question no model
 * can: what the call is actually like to sit through. Speech recognition
 * mishears words a model would never produce, you trail off and start again,
 * and the pause before the agent replies is only uncomfortable when it is
 * your pause.
 *
 * This tab is the phone. The browser's speech recognition is the microphone,
 * `speechSynthesis` is the loudspeaker, and the server holds the model and the
 * transcript — the same seam the real call draws between Deepgram/Cartesia and
 * the call logic, so what you are testing here is the real thing.
 *
 * The rule that makes it honest: an agent turn is reported back as `spoken`
 * with *what the speaker actually played*. Cut the agent off mid-sentence and
 * only the part you heard reaches the transcript.
 *
 * Two microphone modes, because a laptop's own speakers defeat barge-in — the
 * recogniser hears the agent's voice and cuts it off on its own:
 *   - Take turns (default): the mic closes while the agent speaks.
 *   - Talk over it: the mic stays open and interrupting works. Headphones.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import {
  api,
  liveCallUrl,
  type LiveClientMessage,
  type LiveServerMessage,
  type SimulationResult,
} from "../api";
import {
  IconBolt,
  IconCheck,
  IconCoin,
  IconMic,
  IconMicOff,
  IconPhone,
  IconShield,
} from "../components/icons";
import OutcomeCard from "../components/OutcomeCard";
import { ScorecardResult } from "../components/Scorecard";
import {
  Button,
  Card,
  CardHeader,
  DispositionBadge,
  ErrorNote,
  Field,
  PageWrapper,
  Skeleton,
  inputClass,
} from "../components/ui";
import { useAsync } from "../hooks";

// ---------------------------------------------------------------------------
// Web Speech API. Not in TypeScript's DOM lib, and only the parts used here
// are declared — a fuller set of types would be fiction we'd have to maintain.
// ---------------------------------------------------------------------------

interface SpeechAlternative {
  transcript: string;
}
interface SpeechResult {
  0: SpeechAlternative;
  isFinal: boolean;
}
interface SpeechResultList {
  length: number;
  [index: number]: SpeechResult;
}
interface SpeechEvent {
  resultIndex: number;
  results: SpeechResultList;
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: SpeechEvent) => void) | null;
  onerror: ((event: { error: string }) => void) | null;
  onend: (() => void) | null;
}

type RecognitionCtor = new () => Recognition;

const SPEECH: RecognitionCtor | undefined = (
  window as unknown as {
    SpeechRecognition?: RecognitionCtor;
    webkitSpeechRecognition?: RecognitionCtor;
  }
).SpeechRecognition ??
  (window as unknown as { webkitSpeechRecognition?: RecognitionCtor })
    .webkitSpeechRecognition;

const CAN_SPEAK = typeof window !== "undefined" && "speechSynthesis" in window;

/** Campaign language → BCP-47 tag, for both recognition and the voice. */
const SPEECH_LANG: Record<string, string> = {
  en: "en-US",
  hi: "hi-IN",
  // Hinglish campaigns are mostly Hindi phonology with English nouns; the
  // Hindi recogniser handles that far better than the English one.
  "hi-en": "hi-IN",
  ur: "ur-PK",
};

// ---------------------------------------------------------------------------

type Phase = "idle" | "connecting" | "live" | "extracting" | "done";

interface LiveTurn {
  role: "agent" | "you";
  turn?: number;
  text: string;
  firstChunkMs?: number | null;
  interrupted?: boolean;
}

export default function LiveMic() {
  const campaigns = useAsync(() => api.campaigns(), []);
  const health = useAsync(() => api.health(), []);

  const [campaignId, setCampaignId] = useState("");
  const [contactName, setContactName] = useState("Alex Morgan");
  const [save, setSave] = useState(false);
  const [bargeIn, setBargeIn] = useState(false);
  const [voiceOn, setVoiceOn] = useState(CAN_SPEAK);

  const [phase, setPhase] = useState<Phase>("idle");
  const [turns, setTurns] = useState<LiveTurn[]>([]);
  const [partial, setPartial] = useState("");
  const [listening, setListening] = useState(false);
  const [speaking, setSpeaking] = useState(false);
  const [closing, setClosing] = useState(false);
  const [model, setModel] = useState("");
  const [result, setResult] = useState<SimulationResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [typed, setTyped] = useState("");

  // --- the machinery -------------------------------------------------------
  // Everything the speech callbacks touch lives in refs: they are registered
  // once per call and would otherwise close over the state of the render that
  // created them.

  const wsRef = useRef<WebSocket | null>(null);
  const recRef = useRef<Recognition | null>(null);

  const queueRef = useRef<string[]>([]); // chunks waiting to be said
  const utteranceRef = useRef<{ text: string; at: number } | null>(null);
  const playedRef = useRef(""); // confirmed played, this turn
  const turnActiveRef = useRef(false); // a turn is in the air
  const turnDoneRef = useRef(false); // the server finished generating
  const generationRef = useRef(0); // orphans callbacks from a cancelled turn

  const wantMicRef = useRef(false);
  const endedRef = useRef(false);
  // Mirrors of state that the socket and speech callbacks read. Those handlers
  // are installed once per call and would otherwise see the values from the
  // render that created them.
  const closingRef = useRef(false);
  const bargeRef = useRef(bargeIn);
  const voiceRef = useRef(voiceOn);
  const langRef = useRef("en-US");
  const transcriptRef = useRef<HTMLDivElement | null>(null);

  bargeRef.current = bargeIn;
  voiceRef.current = voiceOn;

  const send = useCallback((message: LiveClientMessage) => {
    const ws = wsRef.current;
    if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(message));
  }, []);

  // -- speaker --------------------------------------------------------------

  /** Report what was played and hand the floor back. */
  const finishTurn = useCallback(() => {
    const played = playedRef.current.trim();
    playedRef.current = "";
    turnActiveRef.current = false;
    turnDoneRef.current = false;
    queueRef.current = [];
    utteranceRef.current = null;
    setSpeaking(false);

    // Sent even when empty — the server treats an unconfirmed turn as never
    // heard and drops it, which is the safe direction to fail in.
    send({ type: "spoken", text: played });

    if (!bargeRef.current && !endedRef.current && !closingRef.current) startListening();
    // startListening is stable and declared below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [send]);

  /** Speak the next queued chunk, or close out the turn if there are none. */
  const pump = useCallback(() => {
    if (utteranceRef.current) return; // still talking

    const chunk = queueRef.current.shift();
    if (chunk === undefined) {
      if (turnDoneRef.current) finishTurn();
      return;
    }

    const played = () => {
      playedRef.current += (playedRef.current ? " " : "") + chunk;
    };

    // No voice available, or muted: the words are on screen, and reading them
    // is how the tester hears them. Confirming immediately keeps the model's
    // history correct either way.
    if (!voiceRef.current || !CAN_SPEAK) {
      played();
      pump();
      return;
    }

    const generation = generationRef.current;
    const utterance = new SpeechSynthesisUtterance(chunk);
    utterance.lang = langRef.current;
    const voice = pickVoice(langRef.current);
    if (voice) utterance.voice = voice;
    utterance.rate = 1.05;

    utteranceRef.current = { text: chunk, at: 0 };

    // Where the voice has actually got to. This is the number that makes
    // barge-in honest, so it is tracked even though nothing displays it.
    utterance.onboundary = (event: SpeechSynthesisEvent) => {
      if (generation === generationRef.current && utteranceRef.current) {
        utteranceRef.current.at = event.charIndex;
      }
    };

    const done = () => {
      if (generation !== generationRef.current) return; // cancelled; not ours
      played();
      utteranceRef.current = null;
      pump();
    };
    utterance.onend = done;
    utterance.onerror = done;

    window.speechSynthesis.speak(utterance);
  }, [finishTurn]);

  /** They started talking. Cut the agent off and report only what got out. */
  const interrupt = useCallback(() => {
    // Also fires when everything queued has played but the model is still
    // generating — there is nothing left to silence, but every further token
    // costs money to produce and will never be heard.
    if (!turnActiveRef.current) return;

    const inFlight = utteranceRef.current;
    const heard = inFlight ? inFlight.text.slice(0, inFlight.at) : "";
    const played = `${playedRef.current} ${heard}`.trim();

    generationRef.current += 1; // orphan the in-flight callbacks
    if (CAN_SPEAK) window.speechSynthesis.cancel();
    queueRef.current = [];
    utteranceRef.current = null;
    playedRef.current = "";
    turnActiveRef.current = false;
    turnDoneRef.current = false;
    setSpeaking(false);

    send({ type: "interrupt" });
    send({ type: "spoken", text: played });

    // Show the same thing the transcript now holds: what was heard, and that
    // the rest never arrived.
    setTurns((previous) => {
      const next = [...previous];
      for (let i = next.length - 1; i >= 0; i -= 1) {
        if (next[i].role === "agent") {
          next[i] = { ...next[i], text: played, interrupted: true };
          break;
        }
      }
      return next;
    });
  }, [send]);

  // -- microphone -----------------------------------------------------------

  const startListening = useCallback(() => {
    wantMicRef.current = true;
    const recogniser = recRef.current;
    if (!recogniser || endedRef.current) return;
    try {
      recogniser.start();
      setListening(true);
    } catch {
      /* already running — start() throws rather than no-opping */
    }
  }, []);

  const stopListening = useCallback(() => {
    wantMicRef.current = false;
    setListening(false);
    try {
      recRef.current?.stop();
    } catch {
      /* not running */
    }
  }, []);

  const buildRecogniser = useCallback(() => {
    if (!SPEECH) return null;

    const recogniser = new SPEECH();
    recogniser.lang = langRef.current;
    recogniser.continuous = true;
    recogniser.interimResults = true;

    recogniser.onresult = (event: SpeechEvent) => {
      let interim = "";
      let final = "";
      for (let i = event.resultIndex; i < event.results.length; i += 1) {
        const result = event.results[i];
        if (result.isFinal) final += result[0].transcript;
        else interim += result[0].transcript;
      }

      // The first sound of speech is the barge-in signal — waiting for a final
      // result would let the agent talk over them for another second or two.
      if ((interim.trim() || final.trim()) && bargeRef.current) interrupt();

      setPartial(interim);

      const utterance = final.trim();
      if (!utterance) return;

      setPartial("");
      send({ type: "utterance", text: utterance });
      // Taking turns: close the mic so the agent's own voice can't be
      // transcribed back at it through the laptop speakers.
      if (!bargeRef.current) stopListening();
    };

    recogniser.onerror = (event: { error: string }) => {
      if (event.error === "not-allowed" || event.error === "service-not-allowed") {
        setError(
          "The browser blocked microphone access. Allow it for this site and start the call again.",
        );
        endedRef.current = true;
      }
      // "no-speech" and "aborted" are routine; onend restarts.
    };

    recogniser.onend = () => {
      setListening(false);
      // Chrome ends recognition on its own after a pause. Restart while the
      // call still wants the mic open.
      if (wantMicRef.current && !endedRef.current) {
        try {
          recogniser.start();
          setListening(true);
        } catch {
          /* raced with a real stop */
        }
      }
    };

    return recogniser;
  }, [interrupt, send, stopListening]);

  // -- the call ------------------------------------------------------------

  const teardown = useCallback(() => {
    endedRef.current = true;
    wantMicRef.current = false;
    generationRef.current += 1;
    queueRef.current = [];
    utteranceRef.current = null;
    if (CAN_SPEAK) window.speechSynthesis.cancel();
    try {
      recRef.current?.abort();
    } catch {
      /* never started */
    }
    recRef.current = null;
    setListening(false);
    setSpeaking(false);
  }, []);

  const hangUp = useCallback(
    (reason: string) => {
      if (endedRef.current) return;
      // Hanging up mid-sentence still counts as hearing the first half of it,
      // and the extractor should read what you actually heard.
      interrupt();
      teardown();
      send({ type: "end", reason });
      setPhase("extracting");
    },
    [interrupt, send, teardown],
  );

  const start = useCallback(() => {
    setError(null);
    setResult(null);
    setTurns([]);
    setPartial("");
    setClosing(false);
    setPhase("connecting");

    endedRef.current = false;
    closingRef.current = false;
    playedRef.current = "";
    turnActiveRef.current = false;
    turnDoneRef.current = false;
    queueRef.current = [];
    utteranceRef.current = null;
    generationRef.current += 1;

    const socket = new WebSocket(liveCallUrl());
    wsRef.current = socket;

    socket.onopen = () => {
      socket.send(
        JSON.stringify({
          campaign_id: campaignId || null,
          contact_name: contactName,
          save,
        }),
      );
    };

    socket.onmessage = (frame: MessageEvent<string>) => {
      let message: LiveServerMessage;
      try {
        message = JSON.parse(frame.data) as LiveServerMessage;
      } catch {
        return;
      }

      switch (message.type) {
        case "ready": {
          langRef.current = SPEECH_LANG[message.language] ?? "en-US";
          setModel(message.conversation_model);
          setPhase("live");
          recRef.current = buildRecogniser();
          // Talking over the agent only works if the mic is already open.
          if (bargeRef.current) startListening();
          break;
        }

        case "speak": {
          queueRef.current.push(message.text);
          turnActiveRef.current = true;
          setSpeaking(true);
          setTurns((previous) => appendAgentChunk(previous, message.turn, message.text));
          pump();
          break;
        }

        case "turn_end": {
          turnDoneRef.current = true;
          if (message.first_chunk_ms !== null) {
            setTurns((previous) => tagLatency(previous, message.turn, message.first_chunk_ms));
          }
          pump();
          break;
        }

        case "heard": {
          setTurns((previous) => [...previous, { role: "you", text: message.text }]);
          break;
        }

        case "closing": {
          // The agent said goodbye. Stop listening, leave the transcript up,
          // and let them press the button — hanging up from here would cut off
          // audio still playing.
          closingRef.current = true;
          setClosing(true);
          stopListening();
          break;
        }

        case "extracting": {
          setPhase("extracting");
          break;
        }

        case "outcome": {
          setResult(message.result);
          setPhase("done");
          break;
        }

        case "error": {
          setError(message.message);
          if (message.fatal) {
            teardown();
            setPhase("idle");
          }
          break;
        }
      }
    };

    socket.onerror = () => {
      setError("The connection to the server failed.");
    };

    socket.onclose = () => {
      teardown();
      setPhase((previous) => (previous === "idle" ? "idle" : "done"));
    };
  }, [
    buildRecogniser,
    campaignId,
    contactName,
    pump,
    save,
    startListening,
    stopListening,
    teardown,
  ]);

  // Close the socket and silence the speaker when the page goes away — a
  // forgotten tab would otherwise hold a call open and keep spending.
  useEffect(
    () => () => {
      teardown();
      wsRef.current?.close();
    },
    [teardown],
  );

  useEffect(() => {
    const box = transcriptRef.current;
    if (box) box.scrollTop = box.scrollHeight;
  }, [turns, partial]);

  const live = phase === "live";
  const busy = phase === "connecting" || phase === "extracting";
  const canStart = phase === "idle" || phase === "done";

  const submitTyped = () => {
    const text = typed.trim();
    if (!text || !live) return;
    setTyped("");
    // Typing counts as talking over it: no-op unless a turn is in the air.
    interrupt();
    send({ type: "utterance", text });
  };

  return (
    <PageWrapper className="mx-auto max-w-[1180px] px-7 py-6">
      <header className="mb-6">
        <h1 className="flex items-center gap-2.5 text-2xl font-bold tracking-tight">
          <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand/15 text-brand">
            <IconMic size={18} />
          </span>
          Live mic
        </h1>
        <p className="mt-1.5 max-w-2xl text-sm text-ink-muted">
          Be the person who picked up. Your voice goes through the browser's
          speech recognition, the real conversation model answers, and the real
          extractor reads the transcript afterwards — only the phone line is
          fake.
        </p>
      </header>

      {health.data && !health.data.can_run_simulations && (
        <div className="mb-5">
          <ErrorNote message="No model provider is configured, so there is nothing to talk to. Set a provider key in .env and restart the server." />
        </div>
      )}

      {!SPEECH && (
        <div className="mb-5 rounded-lg border border-warning/35 bg-warning/8 px-3 py-2.5 text-xs leading-relaxed text-ink-secondary">
          <span className="font-medium text-warning">
            This browser has no speech recognition.
          </span>{" "}
          Chrome or Edge have it; Firefox and Safari do not. The call still runs
          — type your replies instead, and the agent still speaks if the browser
          can synthesise a voice.
        </div>
      )}

      <div className="grid gap-5 lg:grid-cols-[360px_1fr] lg:items-start">
        {/* ---- Setup ---- */}
        <Card>
          <CardHeader title="Setup" subtitle="Nobody is called. Nothing is dispatched." />
          <div className="space-y-4 p-5">
            <Field
              label="Campaign"
              hint="Its goal, greeting, constraints, language, and model choice are used as-is."
            >
              {campaigns.loading ? (
                <Skeleton className="mt-1 h-9 w-full" />
              ) : (
                <select
                  value={campaignId}
                  onChange={(event) => setCampaignId(event.target.value)}
                  disabled={!canStart}
                  className={inputClass}
                >
                  <option value="">Choose a campaign…</option>
                  {(campaigns.data ?? []).map((campaign) => (
                    <option key={campaign.id} value={campaign.id}>
                      {campaign.name}
                    </option>
                  ))}
                </select>
              )}
            </Field>

            <Field label="Your name on their list" hint="Substituted into {first_name}.">
              <input
                value={contactName}
                onChange={(event) => setContactName(event.target.value)}
                disabled={!canStart}
                className={inputClass}
              />
            </Field>

            <div>
              <span className="text-xs font-medium text-ink-secondary">Microphone</span>
              <div className="mt-1.5 space-y-1.5">
                <ModeOption
                  selected={!bargeIn}
                  onSelect={() => setBargeIn(false)}
                  disabled={!canStart}
                  title="Take turns"
                  hint="The mic closes while the agent talks. Safe on laptop speakers."
                />
                <ModeOption
                  selected={bargeIn}
                  onSelect={() => setBargeIn(true)}
                  disabled={!canStart}
                  title="Talk over it"
                  hint="The mic stays open, so interrupting works. Headphones — on speakers it will cut itself off."
                />
              </div>
            </div>

            <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-white/10 px-3 py-2.5">
              <input
                type="checkbox"
                checked={voiceOn}
                onChange={(event) => setVoiceOn(event.target.checked)}
                disabled={!CAN_SPEAK}
                className="mt-0.5 accent-[var(--color-brand)]"
              />
              <span className="text-xs">
                <span className="font-medium">Speak the agent's replies</span>
                <span className="mt-0.5 block leading-relaxed text-ink-muted">
                  {CAN_SPEAK
                    ? "Off makes it a text conversation — you read the replies instead."
                    : "This browser has no speech synthesis, so replies are text only."}
                </span>
              </span>
            </label>

            <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-white/10 px-3 py-2.5">
              <input
                type="checkbox"
                checked={save}
                onChange={(event) => setSave(event.target.checked)}
                disabled={!canStart}
                className="mt-0.5 accent-[var(--color-brand)]"
              />
              <span className="text-xs">
                <span className="font-medium">Keep this call</span>
                <span className="mt-0.5 block leading-relaxed text-ink-muted">
                  Saves it to the calls list, flagged as a simulation. Never
                  counted in the dashboard, connect rate, or spend.
                </span>
              </span>
            </label>

            {live || phase === "connecting" ? (
              <Button variant="danger" onClick={() => hangUp("you hung up")}>
                <IconPhone size={13} />
                Hang up
              </Button>
            ) : (
              <Button onClick={start} disabled={!campaignId || busy}>
                <IconMic size={13} />
                {phase === "extracting" ? "Extracting…" : "Call me"}
              </Button>
            )}

            {!campaignId && canStart && (
              <p className="text-xs text-ink-muted">Pick a campaign to call about.</p>
            )}
            {model && <p className="text-[11px] text-ink-muted">On the call: {model}</p>}
          </div>
        </Card>

        {/* ---- The call ---- */}
        <div className="space-y-4">
          {error && <ErrorNote message={error} />}

          {phase === "idle" && turns.length === 0 && (
            <Card>
              <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
                <span className="text-ink-muted/40">
                  <IconMic size={34} />
                </span>
                <p className="mt-3 text-sm font-medium">Nothing dialled yet</p>
                <p className="mt-1 max-w-sm text-xs leading-relaxed text-ink-muted">
                  Pick a campaign and press call. The agent opens with the
                  campaign's greeting; answer it however a real person would —
                  including badly.
                </p>
              </div>
            </Card>
          )}

          {(live || busy || turns.length > 0) && (
            <Card>
              <CardHeader
                title="On the call"
                subtitle={
                  closing
                    ? "The agent has said goodbye. Hang up to run extraction."
                    : "What the transcript records is what you actually heard."
                }
                action={<CallState phase={phase} listening={listening} speaking={speaking} />}
              />

              <div ref={transcriptRef} className="max-h-[46vh] space-y-3 overflow-y-auto p-5">
                {turns.map((turn, index) => (
                  <div
                    key={index}
                    className={`flex flex-col ${turn.role === "agent" ? "items-start" : "items-end"}`}
                  >
                    <div
                      className={`max-w-[80%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                        turn.role === "agent"
                          ? "rounded-tl-md bg-white/5"
                          : "rounded-tr-md bg-brand/15 text-ink"
                      }`}
                    >
                      {turn.text || <span className="text-ink-muted">…</span>}
                    </div>
                    <div className="mt-1 flex items-center gap-2 px-1 text-[11px] text-ink-muted">
                      <span>{turn.role === "agent" ? "Agent" : "You"}</span>
                      {turn.firstChunkMs != null && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span
                            className={`tnum ${turn.firstChunkMs >= 800 ? "text-warning" : ""}`}
                          >
                            {turn.firstChunkMs} ms to first audio
                          </span>
                        </>
                      )}
                      {turn.interrupted && (
                        <>
                          <span aria-hidden="true">·</span>
                          <span className="text-warning">cut off — rest never played</span>
                        </>
                      )}
                    </div>
                  </div>
                ))}

                {partial && (
                  <div className="flex flex-col items-end">
                    <div className="max-w-[80%] rounded-2xl rounded-tr-md border border-dashed border-white/10 px-3.5 py-2.5 text-sm leading-relaxed text-ink-muted">
                      {partial}
                    </div>
                    <span className="mt-1 px-1 text-[11px] text-ink-muted">hearing…</span>
                  </div>
                )}
              </div>

              {(live || phase === "connecting") && (
                <div className="flex items-center gap-2 border-t border-white/10 px-5 py-3">
                  <input
                    value={typed}
                    onChange={(event) => setTyped(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter") submitTyped();
                    }}
                    placeholder={
                      SPEECH ? "…or type a reply" : "Type your reply and press enter"
                    }
                    className="flex-1 rounded-lg border border-white/10 bg-surface px-3 py-2 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/15"
                  />
                  <Button variant="secondary" size="sm" onClick={submitTyped} disabled={!live}>
                    Send
                  </Button>
                </div>
              )}
            </Card>
          )}

          {phase === "extracting" && !result && (
            <Card className="p-5">
              <p className="text-sm font-medium">Reading the transcript…</p>
              <p className="mt-1 text-xs text-ink-muted">
                The extraction model runs at high effort, off the call path.
                A few seconds.
              </p>
            </Card>
          )}

          {result && <Result result={result} />}
        </div>
      </div>
    </PageWrapper>
  );
}

// ---------------------------------------------------------------------------

function ModeOption({
  selected,
  onSelect,
  disabled,
  title,
  hint,
}: {
  selected: boolean;
  onSelect: () => void;
  disabled: boolean;
  title: string;
  hint: string;
}) {
  return (
    <button
      type="button"
      onClick={onSelect}
      disabled={disabled}
      aria-pressed={selected}
      className={`w-full rounded-lg border px-3 py-2 text-left transition disabled:opacity-60 ${
        selected ? "border-brand bg-brand/10" : "border-white/10 hover:border-ink-muted/40"
      }`}
    >
      <span className="flex items-center gap-1.5 text-xs font-medium">
        {selected && (
          <span className="text-brand">
            <IconCheck size={12} />
          </span>
        )}
        {title}
      </span>
      <span className="mt-0.5 block text-[11px] leading-relaxed text-ink-muted">{hint}</span>
    </button>
  );
}

/** Who has the floor right now. The one thing you need at a glance mid-call. */
function CallState({
  phase,
  listening,
  speaking,
}: {
  phase: Phase;
  listening: boolean;
  speaking: boolean;
}) {
  if (phase === "connecting") {
    return <span className="text-xs text-ink-muted">Connecting…</span>;
  }
  if (phase === "extracting") {
    return <span className="text-xs text-ink-muted">Call ended</span>;
  }
  if (speaking) {
    return (
      <span className="flex items-center gap-1.5 rounded-md bg-brand/15 px-2 py-0.5 text-xs font-medium text-brand">
        <span className="live-dot inline-block h-1.5 w-1.5 rounded-full bg-brand" />
        Agent speaking
      </span>
    );
  }
  if (listening) {
    return (
      <span className="flex items-center gap-1.5 rounded-md bg-good/12 px-2 py-0.5 text-xs font-medium text-good">
        <IconMic size={12} />
        Listening
      </span>
    );
  }
  return (
    <span className="flex items-center gap-1.5 rounded-md bg-line px-2 py-0.5 text-xs text-ink-secondary">
      <IconMicOff size={12} />
      Mic closed
    </span>
  );
}

function Result({ result }: { result: SimulationResult }) {
  const latency = result.median_first_chunk_ms;

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-3">
        <Figure
          label="Median first audio"
          value={latency === null ? "—" : `${latency} ms`}
          hint={
            latency === null
              ? "No agent turns to measure"
              : latency < 800
                ? "Feels immediate on a call"
                : "You felt that pause — try a faster model or lower effort"
          }
          tone={latency !== null && latency >= 800 ? "warning" : "neutral"}
          icon={<IconBolt size={15} />}
        />
        <Figure
          label="Cost of this call"
          value={`$${result.usage.cost_usd.toFixed(4)}`}
          hint={`${result.usage.input_tokens.toLocaleString()} in / ${result.usage.output_tokens.toLocaleString()} out`}
          icon={<IconCoin size={15} />}
        />
        <Figure
          label="Ended because"
          value={result.outcome.disposition.replace("_", " ")}
          hint={result.ended_because}
          icon={<IconShield size={15} />}
        />
      </div>

      <Card>
        <CardHeader
          title="Transcript"
          subtitle="Only what the speaker confirmed it played is in here."
          action={<DispositionBadge value={result.outcome.disposition} />}
        />
        <div className="space-y-3 p-5">
          {result.turns.map((turn, index) => (
            <div
              key={index}
              className={`flex flex-col ${turn.role === "assistant" ? "items-start" : "items-end"}`}
            >
              <div
                className={`max-w-[80%] rounded-2xl px-3.5 py-2.5 text-sm leading-relaxed ${
                  turn.role === "assistant"
                    ? "rounded-tl-md bg-white/5"
                    : "rounded-tr-md bg-brand/15 text-ink"
                }`}
              >
                {turn.text}
              </div>
              <div className="mt-1 flex items-center gap-2 px-1 text-[11px] text-ink-muted">
                <span>{turn.role === "assistant" ? "Agent" : "You"}</span>
                {turn.first_chunk_ms !== null && (
                  <>
                    <span aria-hidden="true">·</span>
                    <span className={`tnum ${turn.first_chunk_ms >= 800 ? "text-warning" : ""}`}>
                      {turn.first_chunk_ms} ms to first audio
                    </span>
                  </>
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>

      <ScorecardResult
        scores={result.outcome.scores}
        qualification={result.qualification}
      />

      <OutcomeCard
        outcome={result.outcome}
        subtitle="The same model and prompt a real call would use, on what you just said."
        footnotes={[
          `On the call: ${result.conversation_model}`,
          `After: ${result.extraction_model}`,
          result.call_id ? "Saved to the calls list" : "Not saved",
        ]}
      />
    </>
  );
}

function Figure({
  label,
  value,
  hint,
  icon,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint: string;
  icon: React.ReactNode;
  tone?: "neutral" | "warning";
}) {
  return (
    <Card className={`px-4 py-3.5 ${tone === "warning" ? "border-warning/45" : ""}`}>
      <div className="flex items-start justify-between">
        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-muted">{label}</p>
        <span className={tone === "warning" ? "text-warning" : "text-ink-muted/70"}>{icon}</span>
      </div>
      <p className="mt-1.5 tnum text-xl font-semibold capitalize leading-none">{value}</p>
      <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">{hint}</p>
    </Card>
  );
}

// ---------------------------------------------------------------------------

/** Chunks stream mid-turn, so they land in the bubble that's already open. */
function appendAgentChunk(turns: LiveTurn[], turn: number, text: string): LiveTurn[] {
  const last = turns[turns.length - 1];
  if (last && last.role === "agent" && last.turn === turn && !last.interrupted) {
    const merged = { ...last, text: `${last.text} ${text}`.trim() };
    return [...turns.slice(0, -1), merged];
  }
  return [...turns, { role: "agent", turn, text }];
}

function tagLatency(turns: LiveTurn[], turn: number, ms: number | null): LiveTurn[] {
  return turns.map((entry) =>
    entry.role === "agent" && entry.turn === turn ? { ...entry, firstChunkMs: ms } : entry,
  );
}

/** Closest voice for the call's language, or the browser's default. */
function pickVoice(lang: string): SpeechSynthesisVoice | null {
  if (!CAN_SPEAK) return null;
  const voices = window.speechSynthesis.getVoices();
  const wanted = lang.toLowerCase();
  const prefix = wanted.slice(0, 2);
  return (
    voices.find((voice) => voice.lang.replace("_", "-").toLowerCase() === wanted) ??
    voices.find((voice) => voice.lang.toLowerCase().startsWith(prefix)) ??
    null
  );
}
