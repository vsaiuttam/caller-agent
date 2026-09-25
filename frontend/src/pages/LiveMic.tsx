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

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  liveCallUrl,
  type LiveClientMessage,
  type LiveServerMessage,
  type SimulationResult,
} from "../api";
import { AgentAvatar, type AgentState } from "../components/AgentAvatar";
import CallResult, { FigureCard } from "../components/CallResult";
import { IconCheck, IconMic, IconMicOff, IconPhoneOff, IconSend, IconShield } from "../components/icons";
import { LiveTranscript, type DisplayTurn } from "../components/Transcript";
import {
  Badge,
  Button,
  Callout,
  Card,
  CardHeader,
  EmptyState,
  Field,
  Input,
  Skeleton,
  Switch,
  cx,
  dispositionLabel,
  toast,
} from "../components/ui";
import { useHealth } from "../data";
import { CampaignField, useTestLab } from "./TestLab";

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
  const { campaignId } = useTestLab();
  const { health } = useHealth();

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
          toast.success(`Rehearsal finished — ${dispositionLabel(message.result.outcome.disposition)}`);
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

  const displayTurns = useMemo<DisplayTurn[]>(() => {
    const list: DisplayTurn[] = turns.map((turn, index) => ({
      key: `m-${index}`,
      role: turn.role === "agent" ? "assistant" : "user",
      text: turn.text,
      latencyMs: turn.firstChunkMs ?? null,
      interrupted: turn.interrupted,
    }));
    if (partial) list.push({ key: "partial", role: "user", text: partial, partial: true });
    return list;
  }, [turns, partial]);

  const mood: AgentState = error && phase === "idle"
    ? "error"
    : phase === "connecting"
      ? "ringing"
      : phase === "extracting" || phase === "done" || closing
        ? "ended"
        : live
          ? speaking
            ? "speaking"
            : listening
              ? "listening"
              : "thinking"
          : "idle";

  return (
    <div className="grid gap-5 lg:grid-cols-[380px_minmax(0,1fr)] lg:items-start">
      {/* ---- Setup ---- */}
      <Card className="lg:sticky lg:top-20">
        <CardHeader title="Setup" subtitle="You are the person who picked up. Nobody is called." />
        <div className="space-y-5 p-5">
          <CampaignField disabled={!canStart} />

          <Field label="Your name on their list" hint="Substituted into {first_name}.">
            <Input value={contactName} onChange={(event) => setContactName(event.target.value)} disabled={!canStart} />
          </Field>

          <Field label="Microphone" group>
            <div className="space-y-1.5" role="radiogroup" aria-label="Microphone mode">
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
          </Field>

          <Switch
            checked={voiceOn}
            onChange={setVoiceOn}
            disabled={!CAN_SPEAK}
            label="Speak the agent's replies"
            description={
              CAN_SPEAK
                ? "Off makes it a text conversation — you read the replies instead."
                : "This browser has no speech synthesis, so replies are text only."
            }
          />
          <Switch
            checked={save}
            onChange={setSave}
            disabled={!canStart}
            label="Keep this call"
            description="Saves it to the call log, flagged as a test. Never counted in metrics."
          />

          {live || phase === "connecting" ? (
            <Button variant="danger" size="lg" className="w-full" onClick={() => hangUp("you hung up")} icon={<IconPhoneOff size={15} />}>
              Hang up
            </Button>
          ) : (
            <Button
              size="lg"
              className="w-full"
              onClick={start}
              disabled={!campaignId || busy}
              loading={phase === "extracting"}
              icon={<IconMic size={15} />}
            >
              {phase === "extracting" ? "Reading the transcript…" : phase === "done" ? "Start again" : "Start the call"}
            </Button>
          )}
          {!campaignId && canStart && <p className="-mt-2 text-center text-xs text-ink-muted">Pick a campaign to call about.</p>}
          {model && <p className="text-2xs text-ink-muted">On the call: {model}</p>}
        </div>
      </Card>

      {/* ---- The call ---- */}
      <div className="min-w-0 space-y-3">
        {health && !health.can_run_simulations && (
          <Callout tone="warning" title="No model provider is configured">
            There is nothing to talk to yet. Set a provider key on the server and restart it.
          </Callout>
        )}
        {!SPEECH && (
          <Callout tone="warning" title="This browser has no speech recognition">
            Chrome and Edge have it; Firefox and Safari don't. The call still runs — type your replies instead, and the agent
            still speaks if the browser can synthesise a voice.
          </Callout>
        )}
        {error && <Callout tone="critical" title="The call hit a problem">{error}</Callout>}

        {phase === "idle" && turns.length === 0 ? (
          <Card>
            <EmptyState
              title="Nothing dialled yet"
              hint="Pick a campaign and start the call. The agent opens with the campaign's greeting; answer however a real person would — including badly."
            />
          </Card>
        ) : (
          <Card className="overflow-hidden">
            <div className="flex flex-wrap items-center gap-4 px-5 py-4">
              <AgentAvatar state={mood} size="md" />
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-lg font-semibold tracking-tight text-ink">On the call</h2>
                  <MicState phase={phase} listening={listening} speaking={speaking} />
                </div>
                <p className="mt-1 text-sm text-ink-secondary" aria-live="polite">
                  {closing
                    ? "The agent said goodbye. Hang up to run extraction."
                    : phase === "connecting"
                      ? "Connecting…"
                      : phase === "extracting"
                        ? "Call ended — reading the transcript"
                        : phase === "done"
                          ? "Done — the outcome is below"
                          : "What the transcript records is what you actually heard."}
                </p>
              </div>
            </div>
            <div className="border-t border-line">
              <LiveTranscript
                turns={displayTurns}
                personName="You"
                typing={live && !speaking && !listening && !closing && turns.length > 0}
                empty="The agent's greeting will appear here."
                className="h-[min(50vh,460px)]"
              />
            </div>

            {(live || phase === "connecting") && (
              <form
                className="flex items-center gap-2 border-t border-line px-4 py-3 sm:px-5"
                onSubmit={(event) => {
                  event.preventDefault();
                  submitTyped();
                }}
              >
                <label className="min-w-0 flex-1">
                  <span className="sr-only">Type a reply</span>
                  <Input
                    value={typed}
                    onChange={(event) => setTyped(event.target.value)}
                    placeholder={SPEECH ? "…or type a reply" : "Type your reply and press Enter"}
                  />
                </label>
                <Button type="submit" variant="secondary" disabled={!live || !typed.trim()} icon={<IconSend size={14} />}>
                  Send
                </Button>
              </form>
            )}
          </Card>
        )}

        {phase === "extracting" && !result && (
          <Card className="px-5 py-4" aria-busy="true">
            <p className="text-sm font-medium text-ink">Reading the transcript…</p>
            <p className="mt-0.5 text-xs text-ink-muted">The extraction model runs at high effort, off the call path. A few seconds.</p>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              {[0, 1, 2].map((i) => (
                <Skeleton key={i} className="h-20 rounded-xl" />
              ))}
            </div>
          </Card>
        )}

        {result && (
          <CallResult
            result={result}
            personName="You"
            transcriptSubtitle="Only what the speaker confirmed it played is in here."
            outcomeSubtitle="The same model and prompt a real call would use, on what you just said."
            thirdFigure={
              <FigureCard
                label="Ended because"
                value={result.outcome.disposition.replace(/_/g, " ")}
                hint={result.ended_because}
                icon={<IconShield size={15} />}
              />
            }
            footnotes={[
              `On the call: ${result.conversation_model}`,
              `After: ${result.extraction_model}`,
              result.call_id ? "Saved to the call log" : "Not saved",
            ]}
          />
        )}
      </div>
    </div>
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
      role="radio"
      onClick={onSelect}
      disabled={disabled}
      aria-checked={selected}
      className={cx(
        "w-full rounded-lg border px-3.5 py-2.5 text-left transition-colors duration-150 disabled:opacity-60",
        selected ? "border-brand/50 bg-brand/8" : "border-line hover:border-line-strong hover:bg-subtle/60",
      )}
    >
      <span className="flex items-center gap-1.5 text-sm font-medium text-ink">
        {selected && <IconCheck size={13} className="text-brand" />}
        {title}
      </span>
      <span className="mt-0.5 block text-xs leading-relaxed text-ink-muted">{hint}</span>
    </button>
  );
}

/** Who has the floor right now. The one thing you need at a glance mid-call. */
function MicState({ phase, listening, speaking }: { phase: Phase; listening: boolean; speaking: boolean }) {
  if (phase !== "live") return null;
  if (speaking) {
    return (
      <Badge tone="brand" dot pulse>
        Agent speaking
      </Badge>
    );
  }
  if (listening) {
    return (
      <Badge tone="good" icon={<IconMic size={11} />}>
        Listening
      </Badge>
    );
  }
  return (
    <Badge tone="neutral" icon={<IconMicOff size={11} />}>
      Mic closed
    </Badge>
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
