/**
 * The landing page's product visual: a short sample call, played through the
 * console's real parts (the agent character and the transcript bubbles), so
 * what people see here is what they get after signing in.
 *
 * It is labelled as a sample and nobody is dialled. It pauses when scrolled
 * out of view or when the tab is hidden, has Pause / Play / Replay, and under
 * reduced motion shows the whole conversation at once with the agent still.
 * Screen readers get the full transcript as text instead of the animation.
 */

import { useEffect, useRef, useState } from "react";
import { m, useReducedMotion } from "framer-motion";
import { T } from "../../motion";
import { AgentAvatar, type AgentState } from "../AgentAvatar";
import { Bubble } from "../Transcript";
import { IconCheck, IconPause, IconPhone, IconPlay, IconRefresh, IconWrench } from "../icons";
import { Badge, Button, cx } from "../ui";

type Beat =
  | { kind: "ring" }
  | { kind: "agent" | "person" | "whisper"; text: string }
  | { kind: "tool"; text: string; source: string }
  | { kind: "outcome" };

interface Step {
  beat: Beat;
  pose: AgentState;
  status: string;
  /** How long this step stays before the next one, in ms. */
  hold: number;
}

const PERSON = "Ananya";

const SCRIPT: Step[] = [
  { beat: { kind: "ring" }, pose: "ringing", status: "Ringing", hold: 1300 },
  {
    beat: {
      kind: "agent",
      text: "Namaste Ananya ji, main Kaveri Dental se AI assistant bol rahi hoon. Aapki Thursday wali appointment ke baare mein call kiya tha.",
    },
    pose: "speaking",
    status: "Speaking",
    hold: 3600,
  },
  {
    beat: { kind: "person", text: "Haan ji. Thursday thoda mushkil hai, Friday ho sakta hai?" },
    pose: "listening",
    status: "Listening",
    hold: 2600,
  },
  {
    beat: { kind: "whisper", text: "Offer Friday morning first. She asked for mornings last time." },
    pose: "thinking",
    status: "Reading your whisper",
    hold: 2400,
  },
  {
    beat: { kind: "tool", text: "Checking free slots", source: "Clinic calendar" },
    pose: "thinking",
    status: "Checking the calendar",
    hold: 1800,
  },
  {
    beat: { kind: "agent", text: "Bilkul. Friday subah 11 baje ka slot khaali hai. Book kar doon?" },
    pose: "speaking",
    status: "Speaking",
    hold: 2800,
  },
  { beat: { kind: "person", text: "Haan, perfect. Thank you!" }, pose: "listening", status: "Listening", hold: 1800 },
  {
    beat: { kind: "agent", text: "Ho gaya. WhatsApp par confirmation bhej rahi hoon. Shukriya, Ananya ji." },
    pose: "speaking",
    status: "Speaking",
    hold: 2800,
  },
  { beat: { kind: "outcome" }, pose: "ended", status: "Call ended", hold: 0 },
];

const LAST = SCRIPT.length - 1;

export function HeroCall() {
  const reduce = useReducedMotion() === true;
  const [index, setIndex] = useState(() => (reduce ? LAST : 0));
  const [paused, setPaused] = useState(false);
  const [away, setAway] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Reduced motion: no playback, just the finished conversation.
  useEffect(() => {
    if (reduce) setIndex(LAST);
  }, [reduce]);

  // Stop when nobody can see it: scrolled away, or the tab is in the background.
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    let onScreen = true;
    const update = () => setAway(!onScreen || document.hidden);
    const observer = new IntersectionObserver(
      ([entry]) => {
        onScreen = entry.isIntersecting;
        update();
      },
      { threshold: 0.2 },
    );
    observer.observe(el);
    document.addEventListener("visibilitychange", update);
    return () => {
      observer.disconnect();
      document.removeEventListener("visibilitychange", update);
    };
  }, []);

  const done = index >= LAST;
  const running = !reduce && !paused && !away && !done;

  useEffect(() => {
    if (!running) return;
    const timer = window.setTimeout(() => setIndex((i) => Math.min(i + 1, LAST)), SCRIPT[index].hold);
    return () => window.clearTimeout(timer);
  }, [running, index]);

  const step = SCRIPT[index];
  const beats = SCRIPT.slice(0, index + 1)
    .map((s) => s.beat)
    .filter((b) => b.kind !== "ring");

  const control = done ? (
    <Button size="sm" variant="ghost" icon={<IconRefresh size={13} />} onClick={() => { setIndex(0); setPaused(false); }}>
      Replay
    </Button>
  ) : paused ? (
    <Button size="sm" variant="ghost" icon={<IconPlay size={13} />} onClick={() => setPaused(false)}>
      Play
    </Button>
  ) : (
    <Button size="sm" variant="ghost" icon={<IconPause size={13} />} onClick={() => setPaused(true)}>
      Pause
    </Button>
  );

  return (
    <div ref={ref} className="relative mx-auto w-full max-w-xl lg:max-w-none">
      <div aria-hidden className="flame-glow absolute -inset-x-10 -inset-y-12 -z-10 blur-2xl" />

      <figure className="relative overflow-hidden rounded-2xl border border-line bg-surface elev-3">
        <div className="flex items-center gap-4 border-b border-line px-4 py-4 sm:px-5">
          <AgentAvatar state={step.pose} size="md" className="shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
              <p className="text-sm font-semibold text-ink">Kaveri Dental</p>
              <Badge tone="neutral">Sample call</Badge>
            </div>
            <p className="mt-0.5 text-xs text-ink-muted">Appointment reminder, in Hinglish</p>
            <p className="mt-2 inline-flex items-center gap-1.5 text-xs font-medium text-ink-secondary" aria-hidden>
              <span
                className={cx(
                  "h-1.5 w-1.5 rounded-full",
                  done ? "bg-ink-muted" : paused || away ? "bg-warning" : "live-dot bg-good",
                )}
              />
              {step.status}
              {paused && !done && <span className="font-normal text-ink-muted">(paused)</span>}
            </p>
          </div>
        </div>

        {/* The animation is decorative for assistive tech; the list below it is the content. */}
        <div
          aria-hidden
          className="relative h-[20rem] overflow-hidden px-4 [mask-image:linear-gradient(to_bottom,transparent,#000_3.5rem)] sm:h-[21rem] sm:px-5"
        >
          {beats.length === 0 && (
            <div className="absolute inset-0 flex flex-col items-center justify-center gap-2 text-center">
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-good/10 text-good">
                <IconPhone size={18} />
              </span>
              <p className="text-sm font-medium text-ink">Calling {PERSON}</p>
              <p className="text-xs text-ink-muted">The transcript appears here, turn by turn.</p>
            </div>
          )}
          <ol className="flex h-full flex-col justify-end gap-4 pb-5">
            {beats.map((beat, i) => (
              <BeatRow key={i} beat={beat} animate={!reduce} />
            ))}
          </ol>
        </div>

        <figcaption className="flex items-center justify-between gap-3 border-t border-line bg-subtle/60 px-4 py-2.5 sm:px-5">
          <span className="text-xs text-ink-muted">Played in your browser. Nobody is being called.</span>
          {!reduce && control}
        </figcaption>
      </figure>

      <div className="sr-only">
        <p>Sample call from Kaveri Dental to {PERSON}, an appointment reminder in Hinglish.</p>
        <ol>
          {SCRIPT.map((s, i) => (
            <li key={i}>{describe(s.beat)}</li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function BeatRow({ beat, animate }: { beat: Beat; animate: boolean }) {
  const enter = animate ? { initial: { opacity: 0, y: 6 }, animate: { opacity: 1, y: 0 }, transition: T.base } : {};
  switch (beat.kind) {
    case "agent":
    case "person":
    case "whisper":
      return (
        <Bubble
          turn={{ key: beat.text, role: beat.kind === "agent" ? "assistant" : beat.kind === "person" ? "user" : "whisper", text: beat.text }}
          personName={PERSON}
          animate={animate}
        />
      );
    case "tool":
      return (
        <m.li {...enter} className="flex pl-[38px]">
          <span className="inline-flex max-w-full items-center gap-2 rounded-lg border border-line bg-subtle/60 px-2.5 py-1.5 text-xs">
            <IconWrench size={12} className="shrink-0 text-ink-muted" />
            <span className="font-medium text-ink-secondary">{beat.text}…</span>
            <span className="truncate text-ink-muted">{beat.source}</span>
            <IconCheck size={12} className="shrink-0 text-good" />
          </span>
        </m.li>
      );
    case "outcome":
      return (
        <m.li {...enter} className="flex flex-wrap justify-center gap-2 pt-1">
          <Badge tone="good" icon={<IconCheck size={11} />}>
            Moved to Friday, 11:00
          </Badge>
          <Badge tone="info">WhatsApp confirmation queued</Badge>
        </m.li>
      );
    default:
      return null;
  }
}

function describe(beat: Beat): string {
  switch (beat.kind) {
    case "ring":
      return "The phone rings.";
    case "agent":
      return `Agent: ${beat.text}`;
    case "person":
      return `${PERSON}: ${beat.text}`;
    case "whisper":
      return `Operator whispers to the agent, unheard by ${PERSON}: ${beat.text}`;
    case "tool":
      return `The agent checks the clinic calendar for free slots.`;
    case "outcome":
      return "Outcome: appointment moved to Friday at 11:00, and a WhatsApp confirmation is queued.";
  }
}
