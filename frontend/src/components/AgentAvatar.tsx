/**
 * Vani (वाणी, "voice") — the Samvaad agent, the product's face.
 *
 * A calm, composed mark rather than a cartoon: a dark orb with a thin
 * headset, two capsule eyes and a voice waveform where a mouth would be.
 * The brand colour lives in the rim light, the mic and the waveform. Every
 * state is a pose of the same parts, so switching state is a smooth morph:
 *
 *   idle       a slow breath in the halo; the waveform rests as a flat line
 *   ringing    the halo pulses with the ring, eyes widen slightly
 *   listening  eyes turn toward the earpiece, which glows; halo ripples
 *   thinking   eyes look up, an arc orbits the halo, the waveform scans
 *   speaking   the waveform moves with the voice, sound arcs leave the mic side
 *   ended      eyes soften into arcs, the waveform settles into a smile
 *   error      eyes narrow, the waveform goes flat, an alert badge appears
 *
 * Under prefers-reduced-motion every state is a still pose that still reads.
 * Drawn on a 120-unit grid.
 */

import { useEffect, useId, useState } from "react";
import { AnimatePresence, m, useReducedMotion, type TargetAndTransition, type Transition } from "framer-motion";
import { BRAND } from "../brand";

export type AgentState = "idle" | "ringing" | "listening" | "thinking" | "speaking" | "ended" | "error";

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

// --- Palette and geometry -------------------------------------------------------

const CORE_TOP = "#2A2438";
const CORE_BOTTOM = "#15121D";
const EYE = "#F6EEE8";
const HEADSET = "#3B3550";
const ACCENT = "#FF8A3D";
const ACCENT_SOFT = "#FFB37A";
const LISTEN = "#38BDF8";
const ALERT = "#E5484D";

const C = 60; // centre
const R = 34; // orb radius

/** Five waveform bars across the lower face. */
const BAR_X = [49, 54.5, 60, 65.5, 71];
const BAR_W = 3;
const BAR_Y = 73;

/** Bar heights per pose; `lift` raises each bar's centre (the smile). */
const BARS: Record<string, { h: number[]; lift?: number[] }> = {
  rest: { h: [2.4, 2.4, 2.4, 2.4, 2.4] },
  listen: { h: [2.4, 3.6, 4.6, 3.6, 2.4] },
  smile: { h: [2.6, 2.6, 2.6, 2.6, 2.6], lift: [-2.6, -0.6, 0, -0.6, -2.6] },
  flat: { h: [1.8, 1.8, 1.8, 1.8, 1.8] },
  ringing: { h: [3, 5, 6.5, 5, 3] },
  speak: { h: [6, 11, 8, 12, 5] },
};

/** Talking cycles, one row per bar, offset so the voice looks uneven and real. */
const TALK: number[][] = [
  [3, 7, 4, 8, 3, 5, 3],
  [5, 12, 6, 10, 4, 11, 5],
  [7, 9, 13, 6, 11, 8, 7],
  [4, 11, 7, 12, 5, 9, 4],
  [3, 5, 8, 4, 7, 3, 3],
];

const SOUND_ARCS = ["M98 52 Q103 60 98 68", "M104 47 Q111.5 60 104 73", "M110 42 Q120 60 110 78"];

const loop = (duration: number, extra: Transition = {}): Transition => ({
  duration,
  repeat: Infinity,
  ease: "easeInOut",
  ...extra,
});

const STILL: Transition = { duration: 0 };
const MORPH: Transition = { duration: 0.32, ease: [0.22, 1, 0.36, 1] };

interface Pose {
  animate: TargetAndTransition;
  transition: Transition;
}

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
  const blink = useBlink(!still && state !== "ended" && state !== "error");
  const px = PX[size];
  const small = size === "sm";

  const eyes = eyeMotion(state, still);
  const halo = haloMotion(state, still);

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
        <radialGradient id={`${id}-core`} cx="0.38" cy="0.3" r="0.85">
          <stop offset="0" stopColor={CORE_TOP} />
          <stop offset="1" stopColor={CORE_BOTTOM} />
        </radialGradient>
        <linearGradient id={`${id}-rim`} x1="26" y1="26" x2="94" y2="94" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor={ACCENT_SOFT} />
          <stop offset="0.5" stopColor={ACCENT} />
          <stop offset="1" stopColor={ACCENT} stopOpacity="0.15" />
        </linearGradient>
        <linearGradient id={`${id}-bar`} x1="0" y1="60" x2="0" y2="86" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor={ACCENT_SOFT} />
          <stop offset="1" stopColor={ACCENT} />
        </linearGradient>
      </defs>

      {/* Halo: breathes, pulses or ripples by state */}
      <m.circle
        cx={C}
        cy={C}
        r={R + 9}
        fill="none"
        stroke={state === "listening" ? LISTEN : state === "error" ? ALERT : ACCENT}
        strokeWidth="1.4"
        style={{ originX: 0.5, originY: 0.5 }}
        initial={false}
        animate={halo.animate}
        transition={halo.transition}
      />

      {/* Listening: ripples off the halo */}
      <AnimatePresence>
        {state === "listening" &&
          !small &&
          [0, 1].map((i) => (
            <m.circle
              key={`ripple-${i}`}
              cx={C}
              cy={C}
              r={R + 9}
              fill="none"
              stroke={LISTEN}
              strokeWidth="1.2"
              style={{ originX: 0.5, originY: 0.5 }}
              initial={{ opacity: 0, scale: 1 }}
              animate={still ? { opacity: 0.3 - i * 0.12, scale: 1.1 + i * 0.1 } : { opacity: [0.5, 0], scale: [1, 1.28] }}
              exit={{ opacity: 0 }}
              transition={still ? STILL : loop(2, { ease: "easeOut", delay: i * 1 })}
            />
          ))}
      </AnimatePresence>

      {/* Thinking: an arc orbits the halo */}
      <AnimatePresence>
        {state === "thinking" && (
          <m.circle
            key="orbit"
            cx={C}
            cy={C}
            r={R + 9}
            fill="none"
            stroke={ACCENT}
            strokeWidth="2.6"
            strokeLinecap="round"
            strokeDasharray="18 300"
            style={{ originX: 0.5, originY: 0.5 }}
            initial={{ opacity: 0, rotate: 0 }}
            animate={still ? { opacity: 1, rotate: -60 } : { opacity: 1, rotate: 360 }}
            exit={{ opacity: 0 }}
            transition={still ? STILL : { rotate: { duration: 1.6, repeat: Infinity, ease: "linear" }, opacity: { duration: 0.2 } }}
          />
        )}
      </AnimatePresence>

      {/* The orb and everything on it */}
      <m.g
        style={{ originX: 0.5, originY: 0.5 }}
        initial={false}
        animate={bodyMotion(state, still).animate}
        transition={bodyMotion(state, still).transition}
      >
        {/* Headset band, behind the orb's top edge */}
        <path d="M27 58 C27 37 42 23 60 23 C78 23 93 37 93 58" fill="none" stroke={HEADSET} strokeWidth="3.4" strokeLinecap="round" />

        <circle cx={C} cy={C} r={R} fill={`url(#${id}-core)`} />
        <circle cx={C} cy={C} r={R - 0.8} fill="none" stroke={`url(#${id}-rim)`} strokeWidth="1.6" />
        {/* Soft top light */}
        <ellipse cx="50" cy="38" rx="14" ry="6" fill="#fff" opacity="0.06" transform="rotate(-20 50 38)" />

        {/* Earpieces */}
        <rect x="22" y="50" width="8" height="17" rx="4" fill={HEADSET} />
        <rect x="90" y="50" width="8" height="17" rx="4" fill={HEADSET} />
        <m.rect
          x="92.4"
          y="53.5"
          width="3.2"
          height="10"
          rx="1.6"
          initial={false}
          animate={{ fill: state === "listening" ? LISTEN : "#5A536F", opacity: state === "listening" ? 1 : 0.8 }}
          transition={MORPH}
        />

        {/* Mic boom from the left earpiece */}
        <path d="M26 66 C27 76 34 81 42 80.5" fill="none" stroke={HEADSET} strokeWidth="2.4" strokeLinecap="round" />
        <circle cx="44" cy="80.2" r="3.2" fill={HEADSET} />
        <m.circle
          cx="44"
          cy="80.2"
          r="1.5"
          fill={ACCENT}
          initial={false}
          animate={
            state === "speaking" && !still
              ? { opacity: [0.5, 1, 0.5], scale: [1, 1.3, 1] }
              : { opacity: state === "speaking" ? 1 : 0.55, scale: 1 }
          }
          transition={state === "speaking" && !still ? loop(0.8) : MORPH}
        />

        {/* Eyes: capsules (most states) */}
        <m.g initial={false} animate={eyes.animate} transition={eyes.transition}>
          <m.g
            style={{ transformBox: "fill-box", transformOrigin: "center" }}
            initial={false}
            animate={{
              opacity: state === "ended" ? 0 : 1,
              scaleY: blink ? 0.1 : state === "error" ? 0.55 : state === "ringing" ? 1.12 : 1,
            }}
            transition={{ duration: blink ? 0.07 : 0.18 }}
          >
            <rect x="47" y="49.5" width="5" height="11" rx="2.5" fill={EYE} />
            <rect x="68" y="49.5" width="5" height="11" rx="2.5" fill={EYE} />
          </m.g>
        </m.g>

        {/* Eyes: soft arcs (ended) */}
        <m.g initial={false} animate={{ opacity: state === "ended" ? 1 : 0 }} transition={MORPH}>
          <path d="M46 56 Q49.5 51.5 53 56" fill="none" stroke={EYE} strokeWidth="2.6" strokeLinecap="round" />
          <path d="M67 56 Q70.5 51.5 74 56" fill="none" stroke={EYE} strokeWidth="2.6" strokeLinecap="round" />
        </m.g>

        {/* Waveform */}
        {BAR_X.map((x, i) => {
          const bar = barMotion(state, still, i);
          return (
            <m.rect
              key={i}
              x={x - BAR_W / 2}
              width={BAR_W}
              rx={BAR_W / 2}
              fill={state === "error" ? "#8F8AA3" : `url(#${id}-bar)`}
              initial={false}
              animate={bar.animate}
              transition={bar.transition}
            />
          );
        })}
      </m.g>

      {/* Speaking: sound arcs leave the right side */}
      <AnimatePresence>
        {state === "speaking" &&
          !small &&
          SOUND_ARCS.map((d, i) => (
            <m.path
              key={`arc-${i}`}
              d={d}
              fill="none"
              stroke={ACCENT}
              strokeWidth="2"
              strokeLinecap="round"
              initial={{ opacity: 0, x: -2 }}
              animate={still ? { opacity: 0.8 - i * 0.25, x: 0 } : { opacity: [0, 0.9, 0], x: [-2, 2] }}
              exit={{ opacity: 0 }}
              transition={still ? STILL : loop(1.3, { ease: "easeOut", delay: i * 0.2 })}
            />
          ))}
      </AnimatePresence>

      {/* Error: alert badge */}
      <AnimatePresence>
        {state === "error" && (
          <m.g
            key="alert"
            initial={{ opacity: 0, scale: 0.3 }}
            animate={{ opacity: 1, scale: 1 }}
            exit={{ opacity: 0, scale: 0.3 }}
            transition={still ? STILL : { type: "spring", stiffness: 500, damping: 22 }}
          >
            <circle cx="91" cy="31" r="8" fill={ALERT} stroke="#fff" strokeWidth="2" />
            <path d="M91 27 V32" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" />
            <circle cx="91" cy="35.2" r="1.25" fill="#fff" />
          </m.g>
        )}
      </AnimatePresence>
    </svg>
  );
}

// --- Motion per state -------------------------------------------------------------

function bodyMotion(state: AgentState, still: boolean): Pose {
  if (still) {
    return { animate: { rotate: state === "listening" ? -3 : 0, x: 0, y: 0 }, transition: STILL };
  }
  switch (state) {
    case "ringing":
      return {
        animate: { rotate: [0, -3, 3, -2, 2, 0, 0], x: 0, y: 0 },
        transition: loop(1.4, { times: [0, 0.08, 0.16, 0.24, 0.32, 0.4, 1] }),
      };
    case "listening":
      return { animate: { rotate: -3, x: 0, y: [0, -0.8, 0] }, transition: { rotate: MORPH, y: loop(3) } };
    case "error":
      return {
        animate: { rotate: 0, x: [0, -2, 2, -1, 0], y: 0 },
        transition: { rotate: MORPH, x: { duration: 0.4, ease: "easeInOut" } },
      };
    default:
      return { animate: { rotate: 0, x: 0, y: [0, -1, 0] }, transition: { rotate: MORPH, y: loop(4) } };
  }
}

function haloMotion(state: AgentState, still: boolean): Pose {
  const base = state === "listening" ? 0.55 : state === "error" ? 0.6 : 0.28;
  if (still) return { animate: { opacity: base, scale: 1 }, transition: STILL };
  switch (state) {
    case "ringing":
      return { animate: { opacity: [0.25, 0.8, 0.25], scale: [1, 1.06, 1] }, transition: loop(0.7) };
    case "speaking":
      return { animate: { opacity: [0.3, 0.55, 0.3], scale: [1, 1.025, 1] }, transition: loop(1.1) };
    case "thinking":
      return { animate: { opacity: 0.18, scale: 1 }, transition: MORPH };
    case "idle":
      return { animate: { opacity: [0.18, 0.36, 0.18], scale: [1, 1.03, 1] }, transition: loop(4) };
    default:
      return { animate: { opacity: base, scale: 1 }, transition: MORPH };
  }
}

function eyeMotion(state: AgentState, still: boolean): Pose {
  if (state === "thinking") {
    return still
      ? { animate: { x: 1.5, y: -2 }, transition: STILL }
      : { animate: { x: [0, 1.8, 1.8, -1, 0], y: [0, -2, -2, -1, 0] }, transition: loop(3.6) };
  }
  return { animate: { x: state === "listening" ? 2 : 0, y: 0 }, transition: still ? STILL : MORPH };
}

function barAt(height: number, lift = 0): TargetAndTransition {
  return { height, y: BAR_Y - height / 2 + lift };
}

function barMotion(state: AgentState, still: boolean, i: number): Pose {
  if (state === "speaking" && !still) {
    const hs = TALK[i];
    return {
      animate: { height: hs, y: hs.map((h) => BAR_Y - h / 2) },
      transition: loop(1.05, { delay: i * 0.04 }),
    };
  }
  if (state === "thinking" && !still) {
    // A pulse scans left to right.
    return {
      animate: { height: [2.4, 6, 2.4, 2.4], y: [BAR_Y - 1.2, BAR_Y - 3, BAR_Y - 1.2, BAR_Y - 1.2] },
      transition: loop(1.2, { delay: i * 0.12, times: [0, 0.2, 0.4, 1] }),
    };
  }
  const pose =
    state === "speaking"
      ? BARS.speak
      : state === "listening"
        ? BARS.listen
        : state === "ended"
          ? BARS.smile
          : state === "error"
            ? BARS.flat
            : state === "ringing"
              ? BARS.ringing
              : BARS.rest;
  return { animate: barAt(pose.h[i], pose.lift?.[i] ?? 0), transition: still ? STILL : MORPH };
}

/** Blink every few seconds, at slightly irregular intervals. */
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
        }, 120);
      }, 3200 + Math.random() * 3600);
    };
    schedule();
    return () => window.clearTimeout(timer);
  }, [enabled]);
  return blink;
}
