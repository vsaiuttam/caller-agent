/**
 * The marketing page at `/`. Public, lazy-loaded, and honest: no customer
 * logos, testimonials, metrics or prices, and the product visual is a
 * labelled sample. Structure and rules: frontend/DESIGN.md → Surfaces.
 *
 *   hero (split) → features (bento) → how it works (track) → languages
 *   (conversation) → trust (panel) → closing band → footer
 */

import { useEffect, type ReactNode } from "react";
import { m } from "framer-motion";
import { useLocation } from "react-router-dom";
import { BRAND } from "../brand";
import { EASE_OUT } from "../motion";
import { LOGIN } from "../routes";
import { AgentAvatar } from "../components/AgentAvatar";
import { HeroCall } from "../components/site/HeroCall";
import { SiteFooter } from "../components/site/SiteFooter";
import { SiteHeader, SkipLink } from "../components/site/SiteHeader";
import { Bubble } from "../components/Transcript";
import {
  IconArrowRight,
  IconBlock,
  IconCampaign,
  IconCheck,
  IconClock,
  IconClose,
  IconCoin,
  IconExternal,
  IconFlask,
  IconLive,
  IconLock,
  IconMic,
  IconPlug,
  IconReview,
  IconSend,
  IconSparkle,
  IconWrench,
} from "../components/icons";
import { Badge, ButtonLink, FollowupBadge, buttonClass, cx } from "../components/ui";

const container = "mx-auto w-full max-w-6xl px-4 sm:px-6 lg:px-8";

export default function Landing() {
  const location = useLocation();

  // Arriving at /#features from another page: the section exists only once
  // this chunk has rendered, so the browser's own jump missed it.
  useEffect(() => {
    if (!location.hash) return;
    document.getElementById(decodeURIComponent(location.hash.slice(1)))?.scrollIntoView();
  }, [location.hash]);

  return (
    <div className="flex min-h-[100dvh] flex-col">
      <SkipLink />
      <SiteHeader anchors />
      <main id="main" tabIndex={-1} className="flex-1 outline-none">
        <Hero />
        <Features />
        <HowItWorks />
        <Languages />
        <Trust />
        <ClosingBand />
      </main>
      <SiteFooter onLanding />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Shared bits
// ---------------------------------------------------------------------------

/** Enters once as it scrolls into view. Reduced motion keeps only the fade. */
function Reveal({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  return (
    <m.div
      className={className}
      initial={{ opacity: 0, y: 16 }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, amount: 0.15 }}
      transition={{ duration: 0.5, ease: EASE_OUT, delay }}
    >
      {children}
    </m.div>
  );
}

function SectionHeading({ id, title, lead, center = false }: { id: string; title: string; lead: string; center?: boolean }) {
  return (
    <div className={cx("max-w-2xl", center && "mx-auto text-center")}>
      <h2 id={id} className="text-display-lg font-semibold text-ink">
        {title}
      </h2>
      <p className="mt-4 text-base leading-relaxed text-ink-secondary sm:text-lg">{lead}</p>
    </div>
  );
}

function ExternalLink({ href, children, className }: { href: string; children: ReactNode; className?: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className={cx(
        "inline-flex items-center gap-1.5 rounded-sm font-medium text-brand underline-offset-4 transition-colors hover:underline",
        className,
      )}
    >
      {children}
      <IconExternal size={13} />
      <span className="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

// ---------------------------------------------------------------------------
// Hero
// ---------------------------------------------------------------------------

function Hero() {
  const enter = (delay: number) => ({
    initial: { opacity: 0, y: 12 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.5, ease: EASE_OUT, delay },
  });
  return (
    <section aria-labelledby="hero-title" className="relative overflow-hidden">
      <div className={cx(container, "grid items-center gap-12 pb-16 pt-12 sm:pt-16 lg:grid-cols-[1.02fr_1fr] lg:gap-14 lg:pb-24 lg:pt-20")}>
        <div className="max-w-xl">
          <m.p {...enter(0)} className="text-sm font-medium text-brand">
            Outbound AI phone calls
          </m.p>
          <m.h1 {...enter(0.05)} id="hero-title" className="mt-4 text-display-xl font-semibold text-ink">
            {BRAND.tagline}
          </m.h1>
          <m.p {...enter(0.1)} className="mt-6 max-w-[34rem] text-lg leading-relaxed text-ink-secondary">
            Plan a calling campaign, rehearse it against tough callers, then watch every conversation live and step
            in when it matters.
          </m.p>
          <m.div {...enter(0.15)} className="mt-8 flex flex-wrap items-center gap-3">
            <ButtonLink to={LOGIN} size="lg" iconRight={<IconArrowRight size={15} />}>
              Sign in to the console
            </ButtonLink>
            <a href="#how-it-works" className={buttonClass("secondary", "lg")}>
              See how it works
            </a>
          </m.div>
        </div>
        <m.div {...enter(0.2)}>
          <HeroCall />
        </m.div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Features (bento)
// ---------------------------------------------------------------------------

function Cell({
  icon,
  title,
  children,
  visual,
  className,
}: {
  icon: ReactNode;
  title: string;
  children: ReactNode;
  visual?: ReactNode;
  className?: string;
}) {
  return (
    <article className={cx("flex h-full flex-col rounded-2xl border border-line p-6 sm:p-7", className)}>
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand/10 text-brand" aria-hidden>
        {icon}
      </span>
      <h3 className="mt-5 text-lg font-semibold tracking-tight text-ink">{title}</h3>
      <p className="mt-2 max-w-[60ch] text-sm leading-relaxed text-ink-secondary">{children}</p>
      {visual && <div className="mt-auto pt-6">{visual}</div>}
    </article>
  );
}

function Features() {
  return (
    <section id="features" aria-labelledby="features-title" className="anchor-offset py-16 lg:py-24">
      <div className={container}>
        <Reveal>
          <SectionHeading
            id="features-title"
            title="From the first ring to the follow-up"
            lead="The agent holds the conversation. You stay in charge of it, and every outcome is written down."
          />
        </Reveal>

        <div className="mt-12 grid gap-4 md:grid-cols-2 lg:grid-cols-6">
          <Reveal className="md:col-span-2 lg:col-span-4">
            <Cell
              icon={<IconLive size={18} />}
              title="Watch every call live, and whisper"
              className="relative overflow-hidden bg-surface"
              visual={
                <div className="relative">
                  <div aria-hidden className="flame-glow absolute -right-16 -top-24 h-64 w-96 opacity-70" />
                  <ol className="relative space-y-3" aria-label="Example of a whisper">
                    <Bubble turn={{ key: "w", role: "whisper", text: "Offer the 10% discount." }} personName="Caller" animate={false} />
                    <Bubble
                      turn={{ key: "a", role: "assistant", text: "Since you've been with us a while, I can take 10% off that for you." }}
                      personName="Caller"
                      animate={false}
                    />
                  </ol>
                </div>
              }
            >
              Every turn streams into the console as it's spoken, with the agent's reply time. Whisper an instruction
              the caller never hears, or end the call with a proper goodbye.
            </Cell>
          </Reveal>

          <Reveal className="lg:col-span-2" delay={0.05}>
            <Cell
              icon={<IconMic size={18} />}
              title="Four languages, one agent"
              className="bg-subtle"
              visual={
                <ul className="grid grid-cols-2 gap-2" aria-label="Hello, in each language">
                  {[
                    { text: "Hello", lang: "en", dir: "ltr" },
                    { text: "नमस्ते", lang: "hi", dir: "ltr" },
                    { text: "السلام علیکم", lang: "ur", dir: "rtl" },
                    { text: "Namaste ji", lang: "hi-Latn", dir: "ltr" },
                  ].map((g) => (
                    <li
                      key={g.lang}
                      lang={g.lang}
                      dir={g.dir}
                      className="rounded-lg border border-line bg-surface px-3 py-2.5 text-center text-[15px] font-medium text-ink"
                    >
                      {g.text}
                    </li>
                  ))}
                </ul>
              }
            >
              English, Hindi, Urdu and Hinglish, spoken the way people talk on the phone, with everyday English words
              left in.
            </Cell>
          </Reveal>

          <Reveal className="lg:col-span-2">
            <Cell
              icon={<IconPlug size={18} />}
              title="Connected apps, over MCP"
              className="bg-surface"
              visual={
                <ul className="space-y-2" aria-label="Tools the agent can use">
                  {[
                    ["Looking up the contact", "CRM"],
                    ["Finding free slots", "Calendar"],
                    ["Logging the outcome", "Helpdesk"],
                  ].map(([what, where]) => (
                    <li
                      key={what}
                      className="flex items-center gap-2 rounded-lg border border-line bg-subtle/60 px-2.5 py-1.5 text-xs"
                    >
                      <IconWrench size={12} className="shrink-0 text-ink-muted" aria-hidden />
                      <span className="font-medium text-ink-secondary">{what}</span>
                      <span className="text-ink-muted">{where}</span>
                      <IconCheck size={12} className="ml-auto shrink-0 text-good" aria-hidden />
                    </li>
                  ))}
                </ul>
              }
            >
              Connect your CRM, calendar or helpdesk. The agent looks things up mid-call and writes the outcome back
              afterwards. A built-in demo CRM needs no account.
            </Cell>
          </Reveal>

          <Reveal className="lg:col-span-2" delay={0.05}>
            <Cell
              icon={<IconSend size={18} />}
              title="Follow-ups that know when to stop"
              className="bg-surface"
              visual={
                <div>
                  <p className="rounded-2xl rounded-bl-md bg-subtle px-3.5 py-3 text-sm leading-relaxed text-ink">
                    Thanks for your time, Ananya. You're booked for Friday at 11:00.
                  </p>
                  <div className="mt-2 flex">
                    <FollowupBadge channel="whatsapp" status="delivered" />
                  </div>
                </div>
              }
            >
              A thank-you by SMS or WhatsApp with the booking, or a missed-call note. Never after an opt-out or a wrong
              number.
            </Cell>
          </Reveal>

          <Reveal className="lg:col-span-2" delay={0.1}>
            <Cell
              icon={<IconReview size={18} />}
              title="Scored against your criteria"
              className="bg-surface"
              visual={
                <div>
                  <ul className="space-y-2 text-sm" aria-label="Example scorecard">
                    {[
                      { text: "Confirmed the new date", met: true },
                      { text: "Asked about insurance", met: true },
                      { text: "Mentioned the payment plan", met: false },
                    ].map((c) => (
                      <li key={c.text} className="flex items-center gap-2">
                        {c.met ? (
                          <IconCheck size={14} className="shrink-0 text-good" aria-hidden />
                        ) : (
                          <IconClose size={14} className="shrink-0 text-ink-muted" aria-hidden />
                        )}
                        <span className={c.met ? "text-ink" : "text-ink-muted"}>{c.text}</span>
                        <span className="sr-only">{c.met ? "(met)" : "(not met)"}</span>
                      </li>
                    ))}
                  </ul>
                  <div className="mt-3">
                    <Badge tone="good">Strong lead</Badge>
                  </div>
                </div>
              }
            >
              Each call is scored on the scorecard you write, and the overview shows outcomes and what they cost.
              Anything the model wasn't sure about waits for a person.
            </Cell>
          </Reveal>

          <Reveal className="md:col-span-2 lg:col-span-6">
            <article className="rounded-2xl border border-line bg-brand/[0.05] p-6 sm:p-7">
              <div className="flex flex-col gap-6 lg:flex-row lg:items-start lg:gap-12">
                <div className="lg:w-72 lg:shrink-0">
                  <h3 className="text-lg font-semibold tracking-tight text-ink">Guardrails built in</h3>
                  <p className="mt-2 text-sm leading-relaxed text-ink-secondary">
                    The limits that keep a campaign polite and on budget are part of every campaign, not an add-on.
                  </p>
                </div>
                <ul className="grid flex-1 gap-x-8 gap-y-5 sm:grid-cols-2">
                  {[
                    { icon: <IconClock size={16} />, text: "Calls only inside each contact's calling hours, in their time zone." },
                    { icon: <IconBlock size={16} />, text: "Your do-not-call list is checked before every dial." },
                    { icon: <IconCoin size={16} />, text: "A spend cap pauses the campaign when it's reached." },
                    { icon: <IconFlask size={16} />, text: "Rehearsals and test calls stay out of every metric." },
                  ].map((g) => (
                    <li key={g.text} className="flex gap-3 text-sm leading-relaxed text-ink-secondary">
                      <span className="mt-0.5 shrink-0 text-brand" aria-hidden>
                        {g.icon}
                      </span>
                      {g.text}
                    </li>
                  ))}
                </ul>
              </div>
            </article>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// How it works (track)
// ---------------------------------------------------------------------------

const STEPS = [
  {
    verb: "Design",
    icon: <IconSparkle size={18} />,
    text: "Start from a template or describe the goal. Choose languages, a scorecard and the tools the agent may use.",
  },
  {
    verb: "Rehearse",
    icon: <IconFlask size={18} />,
    text: "Run it against simulated callers who are busy, skeptical or want out. Or take the call yourself on the browser mic.",
  },
  {
    verb: "Call",
    icon: <IconCampaign size={18} />,
    text: "Dial your list inside calling hours. Watch each call live, whisper, or end it.",
  },
  {
    verb: "Review",
    icon: <IconReview size={18} />,
    text: "Read transcripts, scores and follow-up receipts. Anything uncertain waits for a person.",
  },
];

function HowItWorks() {
  return (
    <section id="how-it-works" aria-labelledby="how-title" className="anchor-offset border-y border-line bg-surface py-16 lg:py-24">
      <div className={container}>
        <Reveal>
          <SectionHeading
            id="how-title"
            title="How a campaign goes live"
            lead="Rehearse before anyone real is called. Every step happens in the same console."
          />
        </Reveal>

        <ol className="mt-12 grid gap-8 md:grid-cols-4 md:gap-6">
          {STEPS.map((step, i) => (
            <li
              key={step.verb}
              className={cx(
                "relative",
                // The connector: down to the next step on phones, across on wider screens.
                i < STEPS.length - 1 &&
                  "after:absolute after:left-5 after:top-11 after:h-[calc(100%-1rem)] after:w-px after:bg-line-strong md:after:left-12 md:after:top-5 md:after:h-px md:after:w-[calc(100%-3.5rem+1.5rem)]",
              )}
            >
              <Reveal delay={i * 0.06} className="flex gap-4 md:block">
                <span className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-full border border-line bg-plane text-brand elev-1">
                  {step.icon}
                </span>
                <div className="md:mt-5">
                  <h3 className="text-base font-semibold text-ink">{step.verb}</h3>
                  <p className="mt-1.5 text-sm leading-relaxed text-ink-secondary">{step.text}</p>
                </div>
              </Reveal>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Languages (a conversation)
// ---------------------------------------------------------------------------

const GREETINGS = [
  {
    code: "en",
    dir: "ltr",
    native: "English",
    name: null,
    text: "Hi Ananya, this is an AI assistant calling from Kaveri Dental about your upcoming appointment. Do you have a moment?",
  },
  {
    code: "hi",
    dir: "ltr",
    native: "हिन्दी",
    name: "Hindi",
    text: "नमस्ते अनन्या जी, मैं Kaveri Dental से AI असिस्टेंट बोल रही हूँ, आपकी appointment के बारे में। क्या आप एक मिनट बात कर सकते हैं?",
  },
  {
    code: "ur",
    dir: "rtl",
    native: "اردو",
    name: "Urdu",
    text: "السلام علیکم عائشہ صاحبہ، میں Kaveri Dental سے AI اسسٹنٹ بول رہی ہوں، آپ کی اپائنٹمنٹ کے بارے میں۔ کیا آپ ایک منٹ بات کر سکتی ہیں؟",
  },
  {
    code: "hi-Latn",
    dir: "ltr",
    native: "Hinglish",
    name: null,
    text: "Hi Rohan, main Kaveri Dental se AI assistant bol rahi hoon, aapki appointment ke baare mein. Ek minute baat kar sakte hain?",
  },
] as const;

function Languages() {
  return (
    <section id="languages" aria-labelledby="languages-title" className="anchor-offset py-16 lg:py-24">
      <div className={container}>
        <Reveal>
          <SectionHeading
            id="languages-title"
            center
            title="Speaks the way your customers do"
            lead="Templates ship with a greeting in all four languages, and the agent's goodbyes, silence checks and voicemail lines are written for each."
          />
        </Reveal>

        <ul className="mt-12 grid gap-x-4 gap-y-6 sm:grid-cols-2 lg:grid-cols-4 lg:items-start">
          {GREETINGS.map((g, i) => (
            <li key={g.code} className={cx(i % 2 === 1 && "lg:mt-12")}>
              <Reveal delay={i * 0.06}>
                <p className="mb-2 flex items-baseline gap-2 px-1">
                  <span lang={g.code} dir={g.dir} className="text-base font-semibold text-ink">
                    {g.native}
                  </span>
                  {g.name && <span className="text-xs text-ink-muted">{g.name}</span>}
                </p>
                <blockquote
                  lang={g.code}
                  dir={g.dir}
                  className={cx(
                    "rounded-2xl border border-line bg-surface px-4 py-3.5 text-[15px] leading-relaxed text-ink elev-1",
                    g.dir === "rtl" ? "rounded-tr-md" : "rounded-tl-md",
                  )}
                >
                  {g.text}
                </blockquote>
              </Reveal>
            </li>
          ))}
        </ul>
        <p className="mt-8 text-center text-xs text-ink-muted">
          The appointment-reminder template's greeting, with a sample clinic and names filled in.
        </p>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Trust
// ---------------------------------------------------------------------------

const PROMISES = [
  {
    icon: <IconMic size={18} />,
    title: "It says it's an AI",
    text: "Every template greets the person as an AI assistant, and the agent says so plainly if asked.",
  },
  {
    icon: <IconBlock size={18} />,
    title: "An opt-out is final",
    text: "Honoured on the spot, keyed on the phone number, across every campaign. Re-importing the number won't undo it.",
  },
  {
    icon: <IconLock size={18} />,
    title: "Locked when you say so",
    text: "Set ADMIN_PASSWORD and every page and API route needs a sign-in. Until then, the console warns that it's open.",
  },
];

function Trust() {
  return (
    <section id="trust" aria-labelledby="trust-title" className="anchor-offset pb-16 lg:pb-24">
      <div className={container}>
        <Reveal>
          <div className="grid gap-10 rounded-2xl border border-line bg-surface p-6 elev-1 sm:p-10 lg:grid-cols-[1fr_1.15fr] lg:gap-16 lg:p-12">
            <div>
              <h2 id="trust-title" className="text-display-lg font-semibold text-ink">
                Honest with the people you call
              </h2>
              <p className="mt-4 text-base leading-relaxed text-ink-secondary">
                Automated calling is regulated, and the rules differ by place. These safeguards are built in. Consent
                records and local policy are yours to set.
              </p>
              <ExternalLink href={BRAND.complianceUrl} className="mt-6 text-sm">
                Read the notes on dialling real numbers
              </ExternalLink>
            </div>
            <ul className="divide-y divide-line">
              {PROMISES.map((p) => (
                <li key={p.title} className="flex gap-4 py-5 first:pt-0 last:pb-0">
                  <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand/10 text-brand" aria-hidden>
                    {p.icon}
                  </span>
                  <div>
                    <h3 className="text-base font-semibold text-ink">{p.title}</h3>
                    <p className="mt-1 text-sm leading-relaxed text-ink-secondary">
                      {p.text.split("ADMIN_PASSWORD").flatMap((part, i) =>
                        i === 0
                          ? [part]
                          : [
                              <code key={i} className="rounded bg-subtle px-1 py-0.5 font-mono text-[0.8125rem] text-ink">
                                ADMIN_PASSWORD
                              </code>,
                              part,
                            ],
                      )}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        </Reveal>
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------
// Closing band
// ---------------------------------------------------------------------------

function ClosingBand() {
  return (
    <section aria-labelledby="cta-title" className="relative overflow-hidden border-t border-line pb-24 pt-20 lg:pb-32 lg:pt-24">
      <div aria-hidden className="flame-glow absolute inset-0" />
      <Reveal className="relative">
        <div className="mx-auto flex max-w-2xl flex-col items-center px-4 text-center sm:px-6">
          <AgentAvatar state="idle" size="md" label={`The ${BRAND.agentName}`} />
          <h2 id="cta-title" className="mt-6 text-display-lg font-semibold text-ink">
            Try it on your own phone first
          </h2>
          <p className="mt-4 max-w-xl text-base leading-relaxed text-ink-secondary sm:text-lg">
            Sign in, pick a template and ring your own number from the test lab. Nobody else is called while you
            rehearse.
          </p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-x-6 gap-y-4">
            <ButtonLink to={LOGIN} size="lg" iconRight={<IconArrowRight size={15} />}>
              Sign in to the console
            </ButtonLink>
            <ExternalLink href={BRAND.setupUrl} className="text-sm">
              Read the setup guide
            </ExternalLink>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
