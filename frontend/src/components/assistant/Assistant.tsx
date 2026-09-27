/**
 * Ask Samvaad (§7): an in-app help assistant. A launcher bottom-right on
 * console pages opens a side panel (full screen on phones) that streams
 * answers from POST /api/assistant/chat, suggests questions for the page
 * you're on, and turns the server's links into buttons. It answers; it never
 * acts. The conversation lasts for the browser tab (sessionStorage).
 */

import { Fragment, useCallback, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Link, useLocation } from "react-router-dom";
import { AnimatePresence, m } from "framer-motion";
import { ApiError, streamAssistant, type AssistantLink, type AssistantMessage } from "../../api";
import { useMediaQuery } from "../../hooks";
import { T } from "../../motion";
import { safeNext } from "../../routes";
import { AgentAvatar } from "../AgentAvatar";
import { IconArrowRight, IconClose, IconCopy, IconRefresh, IconSend } from "../icons";
import { LogoMark } from "../Logo";
import { ConfirmDialog, IconButton, cx, toast } from "../ui";
import { suggestionsFor } from "./suggestions";

interface Turn extends AssistantMessage {
  links?: AssistantLink[];
  error?: string;
}

const STORE = "samvaad.assistant.v1";

function load(): Turn[] {
  try {
    const raw = sessionStorage.getItem(STORE);
    return raw ? (JSON.parse(raw) as Turn[]) : [];
  } catch {
    return [];
  }
}

function save(turns: Turn[]) {
  try {
    sessionStorage.setItem(STORE, JSON.stringify(turns.slice(-40)));
  } catch {
    /* blocked storage: the chat just won't survive a reload */
  }
}

export function Assistant() {
  const location = useLocation();
  const phone = !useMediaQuery("(min-width: 640px)");
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>(load);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const [confirmClear, setConfirmClear] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const launcher = useRef<HTMLButtonElement>(null);

  useEffect(() => save(turns), [turns]);
  useEffect(() => () => abort.current?.abort(), []);

  // Keep the newest words in view while they stream in.
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, open]);

  useEffect(() => {
    if (open) requestAnimationFrame(() => inputRef.current?.focus());
  }, [open]);

  const close = useCallback(() => {
    setOpen(false);
    requestAnimationFrame(() => launcher.current?.focus());
  }, []);

  const ask = async (text: string, base: Turn[] = turns) => {
    const question = text.trim();
    if (!question || streaming) return;
    setInput("");
    const history: Turn[] = [...base.filter((t) => !t.error), { role: "user", content: question }];
    setTurns([...history, { role: "assistant", content: "" }]);
    setStreaming(true);
    const controller = new AbortController();
    abort.current = controller;

    const patchLast = (fn: (t: Turn) => Turn) =>
      setTurns((prev) => {
        const next = [...prev];
        next[next.length - 1] = fn(next[next.length - 1]);
        return next;
      });

    try {
      const links = await streamAssistant(
        { messages: history.map(({ role, content }) => ({ role, content })), page: location.pathname },
        (token) => patchLast((t) => ({ ...t, content: t.content + token })),
        controller.signal,
      );
      patchLast((t) => ({ ...t, links: links.filter((l) => safeNext(l.to) === l.to) }));
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        patchLast((t) => (t.content ? t : { ...t, content: "Stopped." }));
      } else {
        const status = err instanceof ApiError ? err.status : 0;
        const message =
          status === 404
            ? "Ask Samvaad needs a server update before it can answer."
            : status === 429
              ? "That's a lot of questions at once. Try again in a minute."
              : (err as Error).message || "Something went wrong.";
        patchLast((t) => ({ ...t, error: message }));
      }
    } finally {
      setStreaming(false);
      abort.current = null;
    }
  };

  const retry = () => {
    const lastQuestion = [...turns].reverse().find((t) => t.role === "user");
    if (!lastQuestion) return;
    void ask(lastQuestion.content, turns.slice(0, turns.lastIndexOf(lastQuestion)));
  };

  const onKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void ask(input);
    }
  };

  const clear = () => {
    abort.current?.abort();
    setTurns([]);
    setConfirmClear(false);
    inputRef.current?.focus();
  };

  const suggestions = suggestionsFor(location.pathname);

  return (
    <>
      <AnimatePresence>
        {!open && (
          <m.button
            ref={launcher}
            key="launcher"
            type="button"
            onClick={() => setOpen(true)}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 8 }}
            transition={T.base}
            aria-label="Ask Samvaad, the help assistant"
            className="fixed bottom-4 right-4 z-40 flex h-12 items-center gap-2 rounded-full border border-line bg-raised pl-2 pr-2 text-sm font-medium text-ink elev-3 transition-[border-color,transform] duration-150 hover:border-line-strong active:translate-y-px sm:pr-4"
          >
            <LogoMark size={30} />
            <span className="hidden sm:inline">Ask Samvaad</span>
          </m.button>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {open && (
          <m.section
            key="panel"
            role="dialog"
            aria-modal="false"
            aria-label="Ask Samvaad"
            onKeyDown={(e) => {
              if (e.key === "Escape" && !confirmClear) {
                e.stopPropagation();
                close();
              }
            }}
            initial={phone ? { opacity: 0, y: 24 } : { opacity: 0, y: 12, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={phone ? { opacity: 0, y: 24 } : { opacity: 0, y: 8, scale: 0.98 }}
            transition={T.base}
            className={cx(
              "fixed z-50 flex flex-col overflow-hidden border-line bg-raised elev-3",
              phone ? "inset-0" : "bottom-4 right-4 h-[min(640px,calc(100dvh-6rem))] w-[400px] origin-bottom-right rounded-2xl border",
            )}
          >
            <header className="flex items-center gap-2.5 border-b border-line px-4 py-3">
              <LogoMark size={26} />
              <div className="min-w-0 flex-1">
                <h2 className="text-sm font-semibold text-ink">Ask Samvaad</h2>
                <p className="truncate text-2xs text-ink-muted">Answers about this console. It won't change anything.</p>
              </div>
              {turns.length > 0 && (
                <IconButton label="Clear the conversation" icon={<IconRefresh size={15} />} size="sm" onClick={() => setConfirmClear(true)} tooltipSide="bottom" />
              )}
              <IconButton label="Close" icon={<IconClose size={16} />} size="sm" onClick={close} tooltip={false} />
            </header>

            <div ref={scroller} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4" aria-live="polite">
              {turns.length === 0 ? (
                <div className="flex flex-col items-center pt-4 text-center">
                  <AgentAvatar state="listening" size="sm" />
                  <p className="mt-3 text-sm font-semibold text-ink">How can I help?</p>
                  <p className="mt-1 max-w-xs text-xs leading-relaxed text-ink-muted">
                    Ask how anything here works: providers, telephony, languages, costs, or why a campaign isn't calling.
                  </p>
                  <ul className="mt-5 w-full space-y-1.5 text-left">
                    {suggestions.map((q) => (
                      <li key={q}>
                        <button
                          type="button"
                          onClick={() => void ask(q)}
                          className="flex w-full items-center justify-between gap-2 rounded-lg border border-line bg-surface px-3 py-2 text-left text-xs text-ink-secondary transition-colors hover:border-line-strong hover:text-ink"
                        >
                          {q}
                          <IconArrowRight size={12} className="shrink-0 text-ink-muted" />
                        </button>
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                turns.map((turn, i) => (
                  <Message
                    key={i}
                    turn={turn}
                    streaming={streaming && i === turns.length - 1}
                    onRetry={i === turns.length - 1 ? retry : undefined}
                    onNavigate={() => phone && setOpen(false)}
                  />
                ))
              )}
            </div>

            <div className="safe-bottom border-t border-line p-3">
              <div className="flex items-end gap-2 rounded-xl border border-line-control bg-surface px-3 py-2 focus-within:border-brand focus-within:ring-3 focus-within:ring-brand/20">
                <label htmlFor="assistant-input" className="sr-only">
                  Your question
                </label>
                <textarea
                  id="assistant-input"
                  ref={inputRef}
                  rows={1}
                  value={input}
                  onChange={(e) => {
                    setInput(e.target.value);
                    e.target.style.height = "auto";
                    e.target.style.height = `${Math.min(e.target.scrollHeight, 120)}px`;
                  }}
                  onKeyDown={onKeyDown}
                  placeholder="Ask a question"
                  className="max-h-[120px] min-h-6 flex-1 resize-none bg-transparent text-sm leading-6 text-ink placeholder:text-ink-muted focus:outline-none"
                />
                {streaming ? (
                  <button
                    type="button"
                    onClick={() => abort.current?.abort()}
                    className="h-8 shrink-0 rounded-md px-2.5 text-xs font-medium text-ink-secondary transition-colors hover:bg-subtle hover:text-ink"
                  >
                    Stop
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={() => void ask(input)}
                    disabled={!input.trim()}
                    aria-label="Send"
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-brand text-on-brand transition-colors hover:bg-brand-hover disabled:opacity-40"
                  >
                    <IconSend size={15} />
                  </button>
                )}
              </div>
              <p className="mt-1.5 px-1 text-2xs text-ink-muted">Enter to send, Shift+Enter for a new line. Answers can be wrong; check before acting.</p>
            </div>
          </m.section>
        )}
      </AnimatePresence>

      <ConfirmDialog
        open={confirmClear}
        onClose={() => setConfirmClear(false)}
        onConfirm={clear}
        title="Clear the conversation?"
        description="The questions and answers in this panel go. Nothing else changes."
        confirmLabel="Clear"
      />
    </>
  );
}

function Message({ turn, streaming, onRetry, onNavigate }: { turn: Turn; streaming: boolean; onRetry?: () => void; onNavigate: () => void }) {
  if (turn.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-brand/10 px-3.5 py-2 text-sm leading-relaxed text-ink">{turn.content}</p>
      </div>
    );
  }

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(turn.content);
      toast.success("Answer copied");
    } catch {
      toast.error("Couldn't copy", "The browser blocked clipboard access.");
    }
  };

  return (
    <div className="group">
      {turn.content ? (
        <div className="text-sm leading-relaxed text-ink">
          <RichText text={turn.content} onNavigate={onNavigate} />
          {streaming && <span className="ml-0.5 inline-block h-3.5 w-1.5 animate-pulse rounded-sm bg-brand align-middle" aria-hidden />}
        </div>
      ) : streaming ? (
        <p className="flex items-center gap-1 text-xs text-ink-muted" aria-label="Thinking">
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink-muted" />
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink-muted [animation-delay:150ms]" />
          <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink-muted [animation-delay:300ms]" />
        </p>
      ) : null}

      {turn.error && (
        <div role="alert" className="mt-1 rounded-lg border border-critical/25 bg-critical/6 px-3 py-2 text-xs text-ink-secondary">
          {turn.error}
          {onRetry && (
            <button type="button" onClick={onRetry} className="ml-2 font-medium text-brand hover:underline">
              Try again
            </button>
          )}
        </div>
      )}

      {!!turn.links?.length && (
        <div className="mt-2.5 flex flex-wrap gap-1.5">
          {turn.links.map((l) => (
            <Link
              key={`${l.to}-${l.label}`}
              to={l.to}
              onClick={onNavigate}
              className="inline-flex h-7 items-center gap-1 rounded-full border border-brand/30 bg-brand/6 px-2.5 text-xs font-medium text-brand transition-colors hover:bg-brand/12"
            >
              {l.label} <IconArrowRight size={11} />
            </Link>
          ))}
        </div>
      )}

      {turn.content && !streaming && (
        <button
          type="button"
          onClick={copy}
          className="mt-1.5 inline-flex items-center gap-1 rounded text-2xs text-ink-muted opacity-70 transition-opacity hover:text-ink hover:opacity-100 focus-visible:opacity-100"
        >
          <IconCopy size={11} /> Copy
        </button>
      )}
    </div>
  );
}

/**
 * Just enough Markdown for help answers: paragraphs, bullet and numbered
 * lists, **bold**, `code` and [links](/app/...). Rendered as React nodes;
 * no HTML from the server ever reaches the DOM.
 */
function RichText({ text, onNavigate }: { text: string; onNavigate: () => void }) {
  const blocks = text.replace(/\r/g, "").split(/\n{2,}/);
  return (
    <>
      {blocks.map((block, i) => {
        const lines = block.split("\n").filter((l) => l.trim());
        const bullets = lines.length > 0 && lines.every((l) => /^\s*([-*•]|\d+[.)])\s+/.test(l));
        if (bullets) {
          const ordered = /^\s*\d/.test(lines[0]);
          const items = lines.map((l) => l.replace(/^\s*([-*•]|\d+[.)])\s+/, ""));
          const List = ordered ? "ol" : "ul";
          return (
            <List key={i} className={cx("my-2 space-y-1 pl-5", ordered ? "list-decimal" : "list-disc")}>
              {items.map((item, j) => (
                <li key={j}>{inline(item, onNavigate)}</li>
              ))}
            </List>
          );
        }
        return (
          <p key={i} className="my-2 first:mt-0 last:mb-0">
            {lines.map((l, j) => (
              <Fragment key={j}>
                {j > 0 && <br />}
                {inline(l.replace(/^#+\s*/, ""), onNavigate)}
              </Fragment>
            ))}
          </p>
        );
      })}
    </>
  );
}

function inline(text: string, onNavigate: () => void): ReactNode[] {
  const out: ReactNode[] = [];
  const re = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^)\s]+)\)/g;
  let last = 0;
  let match: RegExpExecArray | null;
  let k = 0;
  while ((match = re.exec(text))) {
    if (match.index > last) out.push(text.slice(last, match.index));
    if (match[1]) out.push(<strong key={k++} className="font-semibold">{match[1]}</strong>);
    else if (match[2]) out.push(<code key={k++} className="rounded bg-subtle px-1 py-0.5 font-mono text-[0.8em]">{match[2]}</code>);
    else if (match[3]) {
      const href = match[4];
      if (href.startsWith("/app") && safeNext(href) === href) {
        out.push(
          <Link key={k++} to={href} onClick={onNavigate} className="font-medium text-brand underline-offset-2 hover:underline">
            {match[3]}
          </Link>,
        );
      } else if (/^https:\/\//.test(href)) {
        out.push(
          <a key={k++} href={href} target="_blank" rel="noreferrer noopener" className="font-medium text-brand underline-offset-2 hover:underline">
            {match[3]}
          </a>,
        );
      } else out.push(match[3]);
    }
    last = re.lastIndex;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}
