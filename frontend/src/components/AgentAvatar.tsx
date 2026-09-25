/**
 * The Samvaad agent — the product's face.
 *
 * A round speech-bubble character (the same bubble as the logo, tail and
 * all) wearing a call-centre headset. Every state is a pose built from the
 * same parts, so switching state is a smooth morph rather than a swap:
 *
 *   idle       breathes, blinks now and then
 *   ringing    wiggles with the ring, eyebrows up, little "o" mouth
 *   listening  tilts toward the ear cup, which pulses rings
 *   thinking   eyes drift up and away, thought dots rise
 *   speaking   mouth talks, sound waves ripple off the bubble's tail
 *   ended      happy eyes, a grin and a goodbye wave
 *   error      worried brows, a frown, an alert badge
 *
 * Under prefers-reduced-motion every state is a still pose that still reads
 * (open mouth + waves for speaking, rings drawn for listening, and so on).
 *
 * Drawn on a 120-unit grid; mouth and brow shapes share one path structure so
 * framer-motion can interpolate between them.
 */

import { useEffect, useId, useState } from "react";
import {
  AnimatePresence,
  m,
  useReducedMotion,
  type TargetAndTransition,
  type Transition,
} from "framer-motion";
import { BRAND } from "../brand";

export type AgentState =
  | "idle"
  | "ringing"
  | "listening"
  | "thinking"
  | "speaking"
  | "ended"
  | "error";

export type AvatarSize = "sm" | "md" | "lg";

const PX: Record<AvatarSize, number> = { sm: 40, md: 88, lg: 168 };

const STATE_LABEL: Record<AgentState, string> = {
  idle: "ready",
  ringing: "ringing",
  listening: "listening",
  thinking: "thinking",
  speaking: "speaking",
  ended: "call ended",
  error: "something went wrong",
};

// --- Shapes -------------------------------------------------------------------

const BODY =
  "M60 24C38 24 24 38 24 58C24 78 38 92 60 92C67 92 73 90.6 78 88L90 94L86.5 82.5C92.5 76.5 96 68 96 58C96 38 82 24 60 24Z";

/** All: M x y Q cx cy x y Q cx cy x y Z — upper lip then lower lip. */
const MOUTH = {
  smile: "M52 67 Q60 69.5 68 67 Q60 77 52 67 Z",
  listen: "M54.5 68 Q60 69.2 65.5 68 Q60 72.6 54.5 68 Z",
  oh: "M56 68 Q60 62.5 64 68 Q60 74.5 56 68 Z",
  hmm: "M55 70 Q60 68.2 66 68.8 Q60.5 71.2 55 70 Z",
  talkOpen: "M53.5 66.5 Q60 62.5 66.5 66.5 Q60 78 53.5 66.5 Z",
  talkMid: "M53 67.5 Q60 65.5 67 67.5 Q60 74 53 67.5 Z",
  talkClosed: "M54 68.5 Q60 68 66 68.5 Q60 71 54 68.5 Z",
  grin: "M50 66 Q60 69 70 66 Q60 80 50 66 Z",
  frown: "M53 73 Q60 66 67 73 Q60 70 53 73 Z",
} as const;

/** [left, right], all: M x y Q cx cy x y. */
const BROWS = {
  rest: ["M43 45.5 Q47.5 43.5 52 45.5", "M68 45.5 Q72.5 43.5 77 45.5"],
  excited: ["M43 44.5 Q47.5 40.5 52 43.5", "M68 43.5 Q72.5 40.5 77 44.5"],
  thinking: ["M43 46 Q47.5 44.5 52 45.5", "M68 42.5 Q72.5 39.5 77 41.5"],
  worried: ["M42.5 47 Q47 46 52 43.5", "M68 43.5 Q73 46 77.5 47"],
} as const;

const SOUND_WAVES = [
  "M97 86.5 Q101.5 93 97 99.5",
  "M102.5 82 Q109.5 93 102.5 104",
  "M108 77.5 Q117.5 93 108 108.5",
];

const THOUGHT_DOTS: Array<[number, number, number]> = [
  [88, 16, 2],
  [95, 10.5, 2.8],
  [103.5, 6, 3.6],
];

const RING_MARKS = [
  "M20 30 L14.5 25.5",
  "M16.5 38.5 L10 37",
  "M100 30 L105.5 25.5",
  "M103.5 38.5 L110 37",
];

const INK = "#3A1D12";
const HEADSET = "#2B2833";
const HEADSET_PAD = "#4A4656";
const MIC_GLOW = "#2DD4BF";

const loop = (duration: number, extra: Transition = {}): Transition => ({
  duration,
  repeat: Infinity,
  ease: "easeInOut",
  ...extra,
});

const STILL: Transition = { duration: 0 };
const MORPH: Transition = { duration: 0.28, ease: [0.22, 1, 0.36, 1] };

// --- Component ------------------------------------------------------------------

export function AgentAvatar({
  state = "idle",
  size = "md",
  className = "",
  label = BRAND.agentName,
  animated = true,
}: {
  state?: AgentState;
  size?: AvatarSize;
  className?: string;
  label?: string;
  /** Force the still pose, e.g. in a long list of avatars. */
  animated?: boolean;
}) {
  const prefersReduced = useReducedMotion();
  const still = prefersReduced === true || !animated;
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  const blink = useBlink(!still && state !== "ended");
  const px = PX[size];

  const body = bodyMotion(state, still);
  const mouth = mouthMotion(state, still);
  const brows =
    state === "error"
      ? BROWS.worried
      : state === "thinking"
        ? BROWS.thinking
        : state === "ringing"
          ? BROWS.excited
          : BROWS.rest;
  const browsVisible = state === "error" || state === "thinking" || state === "ringing";

  const eyeDrift: Pose =
    state === "thinking"
      ? still
        ? { animate: { x: 2.2, y: -2.2 }, transition: STILL }
        : {
            animate: { x: [0, 2.2, 2.2, -1.2, 0], y: [0, -2.2, -2.2, -1, 0] },
            transition: loop(3.6),
          }
      : { animate: { x: state === "listening" ? 1.4 : 0, y: 0 }, transition: MORPH };

  return (
    <svg
      width={px}
      height={px}
      viewBox="0 0 120 120"
      role="img"
      aria-label={`${label}: ${STATE_LABEL[state]}`}
      className={`shrink-0 overflow-visible ${className}`}
    >
      <defs>
        <linearGradient id={`${id}-body`} x1="30" y1="24" x2="92" y2="94" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#FFC58F" />
          <stop offset="0.55" stopColor="#FF9A52" />
          <stop offset="1" stopColor="#EF6F2A" />
        </linearGradient>
      </defs>

      {/* Ground shadow */}
      <m.ellipse
        cx="60"
        cy="110"
        rx="24"
        ry="3.5"
        fill="currentColor"
        className="text-ink"
        initial={false}
        animate={{ opacity: 0.1, scaleX: state === "ringing" && !still ? [1, 0.92, 1] : 1 }}
        transition={state === "ringing" && !still ? loop(0.6) : MORPH}
      />

      {/* Listening: rings pulse out of the right ear cup (behind the head) */}
      <AnimatePresence>
        {state === "listening" &&
          [0, 1, 2].map((i) => (
            <m.circle
              key={`ring-${i}`}
              cx="98.5"
              cy="57"
              r="10"
              fill="none"
              stroke="var(--color-info)"
              strokeWidth="1.6"
              initial={{ opacity: 0, scale: 0.8 }}
              animate={
                still
                  ? { opacity: 0.55 - i * 0.18, scale: 1 + i * 0.45 }
                  : { opacity: [0.7, 0], scale: [0.8, 2] }
              }
              exit={{ opacity: 0 }}
              transition={still ? STILL : loop(1.8, { ease: "easeOut", delay: i * 0.6 })}
            />
          ))}
      </AnimatePresence>

      {/* The character — everything that moves together */}
      <m.g
        style={{ originX: 0.5, originY: 1 }}
        initial={false}
        animate={body.animate}
        transition={body.transition}
      >
        <path d={BODY} fill={`url(#${id}-body)`} />
        {/* Sheen */}
        <ellipse cx="45" cy="37" rx="11" ry="5.5" fill="#fff" opacity="0.3" transform="rotate(-28 45 37)" />

        {/* Headset band */}
        <path
          d="M25 57 C25 35 40.5 20 60 20 C79.5 20 95 35 95 57"
          fill="none"
          stroke={HEADSET}
          strokeWidth="4.5"
          strokeLinecap="round"
        />

        {/* Cheeks */}
        <m.g initial={false} animate={{ opacity: state === "ended" || state === "ringing" ? 0.5 : 0.28 }} transition={MORPH}>
          <ellipse cx="40.5" cy="64.5" rx="5" ry="3" fill="#FF5C5C" />
          <ellipse cx="79.5" cy="64.5" rx="5" ry="3" fill="#FF5C5C" />
        </m.g>

        {/* Brows */}
        {brows.map((d, i) => (
          <m.path
            key={i}
            fill="none"
            stroke={INK}
            strokeWidth="2.4"
            strokeLinecap="round"
            initial={false}
            animate={{ d, opacity: browsVisible ? 1 : 0 }}
            transition={MORPH}
          />
        ))}

        {/* Eyes: open (most states) */}
        <m.g initial={false} animate={eyeDrift.animate} transition={eyeDrift.transition}>
          <m.g
            initial={false}
            animate={{
              opacity: state === "ended" ? 0 : 1,
              scaleY: blink ? 0.12 : state === "error" ? 0.82 : state === "ringing" ? 1.08 : 1,
            }}
            transition={{ duration: blink ? 0.07 : 0.16 }}
          >
            <ellipse cx="48" cy="55" rx="4.4" ry="5.6" fill={INK} />
            <ellipse cx="72" cy="55" rx="4.4" ry="5.6" fill={INK} />
            <circle cx="49.6" cy="52.8" r="1.5" fill="#fff" />
            <circle cx="73.6" cy="52.8" r="1.5" fill="#fff" />
          </m.g>
        </m.g>

        {/* Eyes: happy arcs (ended) */}
        <m.g initial={false} animate={{ opacity: state === "ended" ? 1 : 0 }} transition={MORPH}>
          <path d="M43.5 56.5 Q48 50.5 52.5 56.5" fill="none" stroke={INK} strokeWidth="2.8" strokeLinecap="round" />
          <path d="M67.5 56.5 Q72 50.5 76.5 56.5" fill="none" stroke={INK} strokeWidth="2.8" strokeLinecap="round" />
        </m.g>

        {/* Mouth */}
        <m.path fill={INK} initial={false} animate={mouth.animate} transition={mouth.transition} />

        {/* Ear cups */}
        <rect x="15.5" y="46" width="12" height="22" rx="5.5" fill={HEADSET} />
        <rect x="92.5" y="46" width="12" height="22" rx="5.5" fill={HEADSET} />
        <rect x="18.5" y="49.5" width="6" height="15" rx="3" fill={HEADSET_PAD} />
        <m.rect
          x="95.5"
          y="49.5"
          width="6"
          height="15"
          rx="3"
          initial={false}
          animate={{ fill: state === "listening" ? "#22D3EE" : HEADSET_PAD }}
          transition={MORPH}
        />

        {/* Mic boom */}
        <path d="M21.5 67 C22.5 79 32 84.5 42 81.8" fill="none" stroke={HEADSET} strokeWidth="3" strokeLinecap="round" />
        <circle cx="44.5" cy="81" r="3.8" fill={HEADSET} />
        <m.circle
          cx="44.5"
          cy="81"
          r="1.9"
          fill={MIC_GLOW}
          initial={false}
          animate={
            state === "speaking" && !still
              ? { opacity: [0.5, 1, 0.5], scale: [1, 1.35, 1] }
              : { opacity: state === "speaking" ? 1 : 0.45, scale: 1 }
          }
          transition={state === "speaking" && !still ? loop(0.7) : MORPH}
        />
      </m.g>

      {/* Speaking: waves ripple off the bubble's tail */}
      <AnimatePresence>
        {state === "speaking" &&
          SOUND_WAVES.map((d, i) => (
            <m.path
              key={`wave-${i}`}
              d={d}
              fill="none"
              stroke="var(--color-brand)"
              strokeWidth="2.6"
              strokeLinecap="round"
              initial={{ opacity: 0, x: -3 }}
              animate={still ? { opacity: 0.9 - i * 0.25, x: 0 } : { opacity: [0, 1, 0], x: [-3, 2] }}
              exit={{ opacity: 0 }}
              transition={still ? STILL : loop(1.2, { ease: "easeOut", delay: i * 0.18 })}
            />
          ))}
      </AnimatePresence>

      {/* Thinking: dots rise */}
      <AnimatePresence>
        {state === "thinking" &&
          THOUGHT_DOTS.map(([cx, cy, r], i) => (
            <m.circle
              key={`dot-${i}`}
              cx={cx}
              cy={cy}
              r={r}
              fill="currentColor"
              className="text-ink-muted"
              initial={{ opacity: 0, y: 3 }}
              animate={still ? { opacity: 0.8, y: 0 } : { opacity: [0.25, 1, 0.25], y: [0, -1.5, 0] }}
              exit={{ opacity: 0 }}
              transition={still ? STILL : loop(1.4, { delay: i * 0.22 })}
            />
          ))}
      </AnimatePresence>

      {/* Ringing: little vibration marks */}
      <AnimatePresence>
        {state === "ringing" &&
          RING_MARKS.map((d, i) => (
            <m.path
              key={`ring-mark-${i}`}
              d={d}
              fill="none"
              stroke="var(--color-brand)"
              strokeWidth="2.6"
              strokeLinecap="round"
              initial={{ opacity: 0 }}
              animate={still ? { opacity: 1 } : { opacity: [0, 1, 0] }}
              exit={{ opacity: 0 }}
              transition={still ? STILL : loop(0.6, { delay: (i % 2) * 0.1 })}
            />
          ))}
      </AnimatePresence>

      {/* Ended: a wave goodbye */}
      <AnimatePresence>
        {state === "ended" && (
          <m.g
            key="hand"
            style={{ originX: 0.5, originY: 1 }}
            initial={{ opacity: 0, scale: 0.4 }}
            animate={
              still
                ? { opacity: 1, scale: 1, rotate: -10 }
                : { opacity: 1, scale: 1, rotate: [0, 20, -12, 20, -12, 14, 0] }
            }
            exit={{ opacity: 0, scale: 0.4 }}
            transition={
              still
                ? STILL
                : {
                    opacity: { duration: 0.2 },
                    scale: { type: "spring", stiffness: 420, damping: 18 },
                    rotate: { duration: 1.6, ease: "easeInOut", delay: 0.15 },
                  }
            }
          >
            <ellipse cx="15" cy="35.5" rx="6.2" ry="7" fill={`url(#${id}-body)`} />
            <ellipse cx="9.8" cy="38.5" rx="2.4" ry="3.4" fill={`url(#${id}-body)`} transform="rotate(-32 9.8 38.5)" />
            <path d="M12.5 30.5 v3.5 M15.5 29.5 v4 M18.5 30.5 v3.5" stroke="#E46325" strokeWidth="1.1" strokeLinecap="round" opacity="0.6" />
          </m.g>
        )}
      </AnimatePresence>

      {/* Error: alert badge */}
      <AnimatePresence>
        {state === "error" && (
          <m.g
            key="alert"
            initial={{ opacity: 0, scale: 0.3 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.3 }}
            transition={still ? STILL : { type: "spring", stiffness: 500, damping: 20 }}
          >
            <circle cx="99" cy="27" r="8.5" fill="#E5484D" stroke="#fff" strokeWidth="2" />
            <path d="M99 22.5 V28" stroke="#fff" strokeWidth="2.4" strokeLinecap="round" />
            <circle cx="99" cy="31.5" r="1.35" fill="#fff" />
          </m.g>
        )}
      </AnimatePresence>
    </svg>
  );
}

// --- Motion per state -------------------------------------------------------------

interface Pose {
  animate: TargetAndTransition;
  transition: Transition;
}

function bodyMotion(state: AgentState, still: boolean): Pose {
  if (still) {
    const rotate = state === "listening" ? -4 : state === "thinking" ? 3 : state === "error" ? -2 : 0;
    return { animate: { rotate, y: 0, x: 0, scale: 1 }, transition: STILL };
  }
  switch (state) {
    case "ringing":
      return {
        animate: { rotate: [0, -6, 6, -5, 5, -3, 0, 0], y: 0, x: 0, scale: 1 },
        transition: loop(1.3, { times: [0, 0.08, 0.16, 0.24, 0.32, 0.4, 0.48, 1] }),
      };
    case "listening":
      return {
        animate: { rotate: -4, y: [0, -1, 0], x: 0, scale: 1 },
        transition: { rotate: MORPH, y: loop(2.8) },
      };
    case "thinking":
      return {
        animate: { rotate: 3, y: [0, -1.2, 0], x: 0, scale: 1 },
        transition: { rotate: MORPH, y: loop(3.2) },
      };
    case "speaking":
      return {
        animate: { rotate: 0, y: [0, -1.4, 0, -0.7, 0], x: 0, scale: 1 },
        transition: { rotate: MORPH, y: loop(0.95) },
      };
    case "ended":
      return {
        animate: { rotate: 0, y: [0, -4, 0], x: 0, scale: 1 },
        transition: { rotate: MORPH, y: { duration: 0.55, repeat: 1, ease: "easeOut" } },
      };
    case "error":
      return {
        animate: { rotate: -2, x: [0, -2.5, 2.5, -1.5, 1, 0], y: 0, scale: 1 },
        transition: { rotate: MORPH, x: { duration: 0.45, ease: "easeInOut" } },
      };
    case "idle":
    default:
      return {
        animate: { rotate: 0, x: 0, y: [0, -1.5, 0], scale: [1, 1.018, 1] },
        transition: { rotate: MORPH, y: loop(3.4), scale: loop(3.4) },
      };
  }
}

function mouthMotion(state: AgentState, still: boolean): Pose {
  if (state === "speaking" && !still) {
    return {
      animate: {
        d: [MOUTH.talkMid, MOUTH.talkOpen, MOUTH.talkClosed, MOUTH.talkOpen, MOUTH.talkMid, MOUTH.talkClosed, MOUTH.talkMid],
      },
      transition: loop(1.1),
    };
  }
  const shape: Record<AgentState, string> = {
    idle: MOUTH.smile,
    ringing: MOUTH.oh,
    listening: MOUTH.listen,
    thinking: MOUTH.hmm,
    speaking: MOUTH.talkOpen,
    ended: MOUTH.grin,
    error: MOUTH.frown,
  };
  return { animate: { d: shape[state] }, transition: still ? STILL : MORPH };
}

/** Blink every few seconds, at slightly irregular intervals so it feels alive. */
function useBlink(enabled: boolean): boolean {
  const [blink, setBlink] = useState(false);
  useEffect(() => {
    if (!enabled) {
      setBlink(false);
      return;
    }
    let timer: number;
    const schedule = () => {
      timer = window.setTimeout(() => {
        setBlink(true);
        timer = window.setTimeout(() => {
          setBlink(false);
          schedule();
        }, 130);
      }, 2400 + Math.random() * 3200);
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, [enabled]);
  return blink;
}
