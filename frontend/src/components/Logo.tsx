/**
 * The Samvaad mark: a speech bubble whose tail flicks out like a sound wave,
 * with a three-bar waveform inside. Drawn on a 32-unit grid so every edge
 * lands on a half pixel at 16px — it stays crisp as a favicon.
 *
 * The fill is its own saffron gradient and the glyph is white, so the mark
 * reads the same on light and dark surfaces without a theme switch.
 * public/favicon.svg is the same drawing; keep them in step.
 */

import { useId } from "react";
import { BRAND } from "../brand";

export const LOGO_BUBBLE_PATH =
  "M14 3H21A9 9 0 0 1 30 12V14A9 9 0 0 1 21 23H14.5C12 23 10.6 24.2 9.2 25.8C7.8 27.4 6.2 29 3.6 29.4C5 27.4 5 25 5 21V12A9 9 0 0 1 14 3Z";

/** Waveform bars: [centre x, height]. Short–tall–medium reads as speech. */
const BARS: Array<[number, number]> = [
  [12.5, 6],
  [17.5, 11],
  [22.5, 7],
];

export function LogoMark({
  size = 24,
  className = "",
  title,
}: {
  size?: number;
  className?: string;
  /** Omit when the mark sits next to the wordmark (it's decorative then). */
  title?: string;
}) {
  const id = useId().replace(/[^a-zA-Z0-9]/g, "");
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      className={className}
      role={title ? "img" : undefined}
      aria-hidden={title ? undefined : true}
      aria-label={title}
    >
      <defs>
        <linearGradient id={`${id}-g`} x1="28" y1="3" x2="5" y2="29" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#FFA24C" />
          <stop offset="1" stopColor="#E8531F" />
        </linearGradient>
      </defs>
      <path d={LOGO_BUBBLE_PATH} fill={`url(#${id}-g)`} />
      {BARS.map(([cx, h]) => (
        <rect key={cx} x={cx - 1.5} y={13 - h / 2} width="3" height={h} rx="1.5" fill="#fff" />
      ))}
    </svg>
  );
}

export function Logo({
  size = 28,
  showName = true,
  className = "",
}: {
  size?: number;
  showName?: boolean;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2.5 ${className}`}>
      <LogoMark size={size} title={showName ? undefined : BRAND.name} />
      {showName && (
        <span className="text-[15px] font-semibold leading-none tracking-tight text-ink">
          {BRAND.name}
        </span>
      )}
    </span>
  );
}
