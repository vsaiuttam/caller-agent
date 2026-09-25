/**
 * Motion tokens for framer-motion — the same numbers as the CSS tokens in
 * index.css (--dur-*, --ease-out). Keep them in step.
 *
 * Rule of thumb: 150ms for feedback (hover, press), 200ms for things that
 * appear, 300ms for things that travel (drawers, page content).
 */

import type { Transition } from "framer-motion";

export const DUR = { fast: 0.15, base: 0.2, slow: 0.3 } as const;

export const EASE_OUT: [number, number, number, number] = [0.22, 1, 0.36, 1];
export const EASE_IN_OUT: [number, number, number, number] = [0.65, 0, 0.35, 1];

export const T: Record<"fast" | "base" | "slow", Transition> = {
  fast: { duration: DUR.fast, ease: EASE_OUT },
  base: { duration: DUR.base, ease: EASE_OUT },
  slow: { duration: DUR.slow, ease: EASE_OUT },
};

/** Content entering the page: a short rise and fade. */
export const rise = {
  initial: { opacity: 0, y: 6 },
  animate: { opacity: 1, y: 0 },
  exit: { opacity: 0, y: 4 },
  transition: T.base,
} as const;
