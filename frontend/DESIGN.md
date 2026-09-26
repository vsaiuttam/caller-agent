---
version: 2
name: Samvaad
description: >
  Samvaad (संवाद, "conversation") is an AI voice-agent calling console. Warm
  stone neutrals, one saffron accent, Geist type, and the product's own
  components as its imagery. Calm and trustworthy on the marketing surface,
  dense and legible in the console. This file is the source of truth; the
  tokens below are implemented in src/index.css (@theme + [data-theme="dark"]).

colors:
  light:
    plane: "#f6f5f2"          # page background
    surface: "#ffffff"        # cards, panels
    raised: "#ffffff"         # popovers, dialogs, toasts
    subtle: "#f1efeb"         # hover fills, wells, chips
    subtle-strong: "#e9e6e0"  # pressed / selected fills
    line: "#e5e2dc"           # decorative hairlines
    line-strong: "#d3cfc7"    # hover borders, button outlines
    line-control: "#8f887e"   # input / switch boundaries (>= 3:1)
    ink: "#1c1a17"
    ink-secondary: "#55514a"
    ink-muted: "#655f56"
    brand: "#b03b0b"          # saffron: the only accent
    brand-hover: "#983208"
    on-brand: "#ffffff"
    flame-1: "#ffa24c"        # logo gradient; decoration only
    flame-2: "#e8531f"
    good: "#13723a"
    warning: "#8a5300"
    serious: "#be123c"
    critical: "#b91c1c"
    on-critical: "#ffffff"
    info: "#0b6780"
  dark:
    plane: "#0e0d0c"
    surface: "#171614"
    raised: "#1f1d1b"
    subtle: "#22201d"
    subtle-strong: "#2c2a26"
    line: "#2a2825"
    line-strong: "#3b3834"
    line-control: "#736d64"
    ink: "#f2efea"
    ink-secondary: "#bab4aa"
    ink-muted: "#9a938a"
    brand: "#fb8a3c"
    brand-hover: "#fda05e"
    on-brand: "#1a0d04"
    good: "#5bd08b"
    warning: "#e9bf55"
    serious: "#fb7185"
    critical: "#f87171"
    on-critical: "#1f0707"
    info: "#5cc8dd"

typography:
  family: "Geist (sans), Geist Mono (code), Noto Sans Devanagari (Hindi fallback)"
  display-xl: { size: "clamp(2.5rem, 5vw + 1rem, 4rem)", weight: 600, lineHeight: 1.04, tracking: "-0.035em" }
  display-lg: { size: "clamp(2rem, 2.5vw + 1rem, 2.75rem)", weight: 600, lineHeight: 1.1, tracking: "-0.03em" }
  display-md: { size: "1.75rem", weight: 600, lineHeight: 1.2, tracking: "-0.02em" }
  title: { size: "1.25rem-1.5rem", weight: 600, lineHeight: 1.25, tracking: "-0.01em" }
  body-lg: { size: "1.125rem", weight: 400, lineHeight: 1.6 }
  body: { size: "1rem (marketing) / 0.875rem (console)", weight: 400, lineHeight: 1.5 }
  caption: { size: "0.75rem", weight: 400-500, lineHeight: 1.5 }
  micro: { size: "0.6875rem", weight: 500, use: "chips, table heads, meta only" }

spacing: { base: 4px, console: [8, 12, 16, 24, 32], marketing-section: "64px mobile / 96px desktop" }

rounded:
  sm: 6px     # chips inside controls, kbd
  md: 8px     # buttons, inputs, menu items
  lg: 10px    # small cards, callouts
  xl: 14px    # cards, panels
  2xl: 18px   # dialogs, hero visual, marketing panels
  full: 9999px # badges, status pills, avatars

elevation:
  elev-1: "resting cards (hairline + 1-2px warm shadow)"
  elev-2: "hover, popovers"
  elev-3: "dialogs, toasts, the hero call card"

motion:
  fast: 150ms    # hover, press
  base: 200ms    # things that appear
  slow: 300ms    # things that travel (drawers)
  reveal: 500ms  # marketing scroll reveals, once
  ease-out: "cubic-bezier(0.22, 1, 0.36, 1)"

z-index: { header: 30, drawer-dialog: 60, palette: 65, toast: 70, skip-link: 90 }
---

# Samvaad design system

## Design read

> Reading this as: a product landing page and sign-in for operations teams who
> run AI phone campaigns (India-first, multilingual), with a warm, trust-first,
> product-led language, leaning toward Tailwind v4 CSS-variable tokens, Geist,
> one saffron accent, and the product's own components as the imagery.

**Mode:** redesign, preserve (design-taste §11). The brand (saffron bubble mark,
warm stone neutrals, Geist, the agent character) is starting material, not a
suggestion. We evolve it; we do not replace it with a generic blue SaaS look.

**Dials** (design-taste §1):

| Surface | Variance | Motion | Density | Why |
| --- | --- | --- | --- | --- |
| Landing `/` | 6 | 5 | 4 | A landing page (7-9) for a product that calls real people (trust-first, 3-4). One motivated live demo, scroll reveals, hover feedback. |
| Login `/login` | 4 | 4 | 3 | One job. The agent reacts; nothing else moves. |
| Console `/app/*` | 3 | 3 | 7 | Dense operational UI; out of design-taste's scope (§13), governed by ui-ux-pro-max. |

## Decisions (and which skill drove them)

Where the skills disagreed, this is the call we made.

1. **Saffron stays the single accent; no trust-blue primary.** ui-ux-pro-max's
   design-system run proposed blue + teal + an orange CTA. That is three hues
   and a second identity. design-taste §4.2 (one accent, colour-consistency
   lock) and §11.C (extract the existing brand first) win. The ui-ux-pro-max
   conversion advice survives: its CTA colour was orange too.
2. **Light brand darkened `#c2410c` → `#b03b0b`.** The old value measured
   4.01-4.48:1 as text on its own 10-12% tints (badges, active chips): under
   AA. The new one is 4.64:1 or better on every surface and tint, and white on
   it is 6.04:1. Same hue, so the identity holds. (ui-ux-pro-max
   `color-accessible-pairs`.)
3. **Geist stays; Plus Jakarta Sans rejected.** design-taste §4.1 lists Geist
   as a preferred sans and discourages default swaps; redesign-existing-projects
   swaps fonts only when they are defaults. One family; hierarchy comes from
   size, weight and tracking (the principle behind both design references).
4. **No glassmorphism as a style.** ui-ux-pro-max's own `blur-purpose` rule
   (blur signals a layer, not decoration) and design-taste §5 ("inappropriate
   for dashboards") agree. Blur appears only on sticky bars and scrims, with a
   solid fallback under `prefers-reduced-transparency`.
5. **Atmosphere comes from the mark.** The logo's gradient (`flame-1` →
   `flame-2`) appears as a soft radial light behind the hero visual and the
   closing band, never as a button, text or card fill. Principle borrowed from
   the voice-AI reference (design-references): colour as atmosphere, one
   action colour. No colours, copy or layout taken from it.
6. **The product is the hero image.** The hero plays a labelled *sample call*
   through the real `AgentAvatar` and the real transcript `Bubble` component.
   design-taste §4.8 prefers photography, but the brief forbids external or
   stock images, and §4.8 allows "a real component preview". banner-design:
   CSS-built visual, one primary CTA, critical content inside the safe zone.
   ui-ux-pro-max `auto-rotation-controls`: it has Pause/Play, stops when
   off-screen or the tab is hidden, and renders its final state, still, under
   reduced motion.
7. **Honest copy only.** No customer logos, testimonials, metrics or pricing.
   The demo is labelled as a sample. Compliance claims describe only what the
   code does (AI greeting, opt-out suppression, `ADMIN_PASSWORD`). design-taste
   §4.9 (no invented numbers), ui-ux-pro-max ("label live only when it is").
8. **Marketing typography rules:** sentence case, `text-wrap: balance` on
   headings, at most one small label per three sections, zero em or en dashes
   on the landing, login and footers. design-taste §4.7 / §9.G, and the
   conversational-SaaS reference's sentence-case eyebrows.
9. **Control boundaries are 3:1.** Hairlines (`line`, `line-strong`) are
   decorative and stay quiet. Anything that marks where a control is (input and
   select borders, the off state of a switch) uses `line-control`, 3.5:1 in
   both themes (WCAG 1.4.11; ui-ux-pro-max pro-rules "border visibility").
10. **16px inputs on phones.** Inputs are `text-base` below 640px so iOS never
    zooms on focus, and 40px tall there. (ui-ux-pro-max `readable-font-size`,
    `touch-friendly-input`.)
11. **One label per intent.** Every sign-in call to action reads "Sign in to the
    console" (shortened to "Sign in" only in the phone-width header).
    design-taste §4.5.
12. **Icons:** keep the project's single hand-drawn set (24-unit grid, 1.75
    stroke, round caps). design-taste §3.C discourages hand-rolled icons but also
    demands one family per project; redesign-existing-projects says work with
    the existing stack. Adding a library now would mix two families. No emoji
    anywhere in the UI.
13. **Dark-mode status colours softened.** The Tailwind-400 greens, yellows and
    cyans read as neon on near-black. Desaturated to 53-77% saturation while
    staying above 7:1 (redesign "oversaturated accents", ui-ux-pro-max
    `color-dark-mode`).
14. **Footer without a link farm.** Three short groups plus the brand column; no
    Terms or Privacy links because those pages do not exist
    (redesign-existing-projects "footer link farm", brief: link nothing fake).

## Colour

Colour is semantic. Components never use a raw hex value; they say
`bg-surface`, `text-ink-muted`, `border-line-control`, `bg-brand/10`.

### Roles

| Token | Means | Never |
| --- | --- | --- |
| `brand` | The primary action, the current place (active nav, tab underline, focus ring), live activity ("In progress") | Status meaning; large backgrounds |
| `good` | Success, connected, completed, strong score | Decoration |
| `warning` | Needs attention soon: pending review, partial, demo mode | Errors |
| `serious` | A negative outcome that isn't a failure: declined, weak score | System errors |
| `critical` | Failure, destructive action, validation error, unreachable | Anything the user can ignore |
| `info` | The system or an operator speaking: whispers, after-call tools, notes | Actions |
| `flame-1/2` | The mark and marketing atmosphere | Text, buttons, cards |

Every status colour ships with a text label or an icon. Colour is never the
only signal.

### Contrast (measured, WCAG 2.x relative luminance)

Text needs 4.5:1; control boundaries and focus indicators need 3:1.

| Light | on plane | on surface | on subtle | on own 10% tint (surface) | on own 12% tint (plane) |
| --- | --- | --- | --- | --- | --- |
| ink | 15.93 | 17.36 | 15.12 | 14.19 | 12.51 |
| ink-secondary | 7.24 | 7.89 | 6.87 | 6.78 | 6.05 |
| ink-muted | 5.79 | 6.32 | 5.50 | 5.50 | 4.93 |
| brand | 5.54 | 6.04 | 5.26 | 5.19 | 4.64 |
| good | 5.51 | 6.01 | 5.23 | 5.20 | 4.66 |
| warning | 5.81 | 6.33 | 5.51 | 5.47 | 4.90 |
| serious | 5.76 | 6.29 | 5.47 | 5.29 | 4.70 |
| critical | 5.93 | 6.47 | 5.63 | 5.46 | 4.86 |
| info | 5.90 | 6.43 | 5.60 | 5.55 | 4.96 |

| Dark | on plane | on surface | on subtle | on own 10% tint (surface) | on own 12% tint (plane) |
| --- | --- | --- | --- | --- | --- |
| ink | 16.93 | 15.77 | 14.17 | 12.21 | 12.81 |
| ink-secondary | 9.43 | 8.78 | 7.89 | 7.35 | 7.80 |
| ink-muted | 6.39 | 5.95 | 5.35 | 5.20 | 5.53 |
| brand | 8.14 | 7.58 | 6.81 | 6.51 | 6.90 |
| good | 10.02 | 9.33 | 8.39 | 7.82 | 8.27 |
| warning | 11.14 | 10.37 | 9.32 | 8.54 | 9.03 |
| serious | 7.21 | 6.72 | 6.04 | 5.86 | 6.22 |
| critical | 7.02 | 6.54 | 5.87 | 5.71 | 6.07 |
| info | 9.95 | 9.27 | 8.33 | 7.76 | 8.22 |

| Pair | Light | Dark |
| --- | --- | --- |
| on-brand on brand (primary button) | 6.04 | 7.98 |
| on-brand on brand-hover | 7.51 | 9.40 |
| on-critical on critical (danger button) | 6.47 | 6.95 |
| line-control on surface (input border) | 3.51 | 3.53 |
| line-control on plane | 3.22 | 3.79 |
| brand focus ring on plane / surface | 5.54 / 6.04 | 8.14 / 7.58 |
| placeholder (ink-muted) on surface | 6.32 | 5.95 |

Before this pass: light brand text on tints 4.01-4.48, light info on a plane
tint 4.18, placeholders 3.69 (light) and 4.07 (dark), input borders 1.55. All
fixed by the tokens above.

## Typography

- **Geist** for everything; **Geist Mono** for code, env vars and ids; tabular
  figures (`tnum`) for anything that ticks or aligns. Hindi falls back to Noto
  Sans Devanagari, loaded only when Devanagari is on screen; Urdu uses the
  system's Arabic-script face with `dir="rtl"` on the element.
- Display type: weight 600, negative tracking that grows with size (-0.02em to
  -0.035em), line-height 1.04-1.2, `text-wrap: balance`. Never bold (700+)
  display, never gradient text.
- Body: 16px / 1.6 on the marketing surface, 14px / 1.5 in the console (a
  dense tool, read on desktop). Paragraphs cap at ~65 characters.
- Weights: 400 body, 500 labels and buttons, 600 titles. Micro text (11px) is
  for chips, table heads and meta only, never for sentences.

## Space, layout and breakpoints

- 4px base. Console gaps 8/12/16/24; card padding 16-20px. Marketing sections
  64px (mobile) and 96px (desktop) apart; the last section before the footer
  gets a little more at the bottom.
- Containers: marketing `max-w-6xl` with 16/24/32px gutters; console pages
  `max-w-3xl | 6xl | 1400px` by page type.
- Test widths: **375, 768, 1024, 1440**. No horizontal page scroll at any of
  them; wide tables scroll inside their own container. Multi-column marketing
  layouts collapse to one column below 768px, declared in the same component.
- `min-h-[100dvh]`, never `h-screen`. Sticky header offsets anchors with
  `scroll-margin-top`.

## Shape

One documented rule (design-taste §4.4): **controls 8px, cards 14px, dialogs
and marketing panels 18px, badges and status pills fully round.** Inner
elements are tighter than their containers.

## Elevation

Warm-tinted shadows (the ink hue, never pure black in light mode), one light
source from above. A card is a hairline plus `elev-1`; hover or a popover adds
`elev-2`; dialogs, toasts and the hero call card use `elev-3`. In dark mode
borders do most of the separating and shadows go deeper.

## Motion

| Token | Duration | Use |
| --- | --- | --- |
| fast | 150ms | hover, press, colour changes |
| base | 200ms | things appearing (popovers, toasts, list rows) |
| slow | 300ms | things travelling (drawers, theme crossfade) |
| reveal | 500ms | marketing sections entering the viewport, once |

Ease-out (`cubic-bezier(0.22, 1, 0.36, 1)`) arriving; exits run at about two
thirds of the enter time. Only `transform` and `opacity` animate. Every
animation says something: a state change, feedback, or the order of a story.
Infinite loops are reserved for real live state (a live dot, the agent's
current pose) and the hero sample call, which can be paused.

**Reduced motion:** CSS animations and transitions collapse to instant;
framer-motion runs with `reducedMotion="user"`; the agent holds still poses; the
hero shows the whole sample call at once with no playback.

## Components (rules, not a catalogue)

- **Buttons:** primary = saffron fill, one per view; secondary = surface with a
  hairline; ghost and subtle for tertiary actions; danger = critical fill.
  Press feedback `translate-y-px`; disabled at 50% with `not-allowed`. Labels
  never wrap on desktop. 36px tall on desktop, 40px on phones.
- **Inputs:** label above, helper or error below (errors use `role="alert"`
  and the critical colour plus an icon), `line-control` border, brand focus
  ring. Passwords have a Show/Hide toggle with `aria-pressed` and allow paste
  and password managers.
- **Focus:** one treatment everywhere, a 2px brand outline offset by 2px on
  `:focus-visible`.
- **Pointer:** everything clickable shows `cursor: pointer`.
- **States:** every data view has a skeleton that matches its layout, a
  composed empty state (the agent character plus the next action) and an
  inline error with Retry. Toasts only for transient confirmations.
- **Badges:** pill, 20px, tinted background with a same-hue border, label text
  in the tone colour (passes on its tint in both themes).

## Surfaces

### Landing `/`

Sticky header (64px, anchors from 1024px) → hero (split: copy left, sample
call right) → features (bento, six cells, mixed spans, varied backgrounds) →
how it works (a four-verb track: Design, Rehearse, Call, Review) → languages
(four greetings in four scripts, message-shaped) → trust (split panel: three
promises the code keeps) → closing band (the agent, one CTA) → footer. Seven
sections, six different layout families.

### Login `/login`

Same header (no CTA), a two-panel card (the reacting agent and the promise on
the left from 1024px; the form on the right), then the marketing footer.
States: checking (skeleton), locked (password form, wrong-password error,
429 lockout with a countdown, loading), open (Enter the console, plus a note
that `ADMIN_PASSWORD` locks it), unreachable (Retry, or continue anyway),
signed in (straight to `next`).

### Console `/app/*`

Collapsible sidebar (drawer on phones), a 56px top bar with breadcrumbs,
search, system health, theme and account, and a slim footer at the end of
every page: version and build, health, keyboard shortcuts, docs, repository.

### Footers

- **Marketing:** brand column (mark, tagline, the meaning of संवाद, the four
  languages), then Product (in-page anchors), Console (routes that exist) and
  Project (the GitHub repository and README sections). Copyright from
  `src/brand.ts`. No legal pages, because none exist.
- **Console:** one line that wraps on phones.

## Routes

`/` landing and `/login` are public. The console lives under `/app`. Every v1
path (`/dashboard`, `/campaigns/...`, `/calls`, `/review`, `/live`,
`/test-lab/...`, `/simulator`, `/templates`, `/models`, `/settings`,
`/suppressions`) redirects to its `/app` twin, query string and hash
included. With auth on, an unauthenticated visit to `/app/*` goes to
`/login?next=<the path you asked for>`; `next` only accepts `/app` paths.

## What we don't do

Blue-purple AI gradients, glass cards, neon glows, three identical feature
cards, fake logos or numbers, scroll cues, version labels in the hero,
emoji icons, pure black or pure white text on pure backgrounds, colour as the
only signal, placeholder-only labels, disabled zoom.
