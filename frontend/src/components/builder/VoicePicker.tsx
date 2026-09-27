/**
 * Voice selection (§4): the Sarvam speakers that speak the campaign's
 * language, each with a play button that fetches a short sample.
 */

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { Link } from "react-router-dom";
import { ApiError, api, unlessMissing, type Voice } from "../../api";
import { useAsync } from "../../hooks";
import { IconCheck, IconPause, IconPlay } from "../icons";
import { Skeleton, Spinner, cx } from "../ui";

/** Samples already fetched this session, by voice + language. */
const samples = new Map<string, string>();

export function VoicePicker({
  language,
  languageLabel,
  value,
  onChange,
}: {
  language: string;
  languageLabel: string;
  value: string | null;
  onChange: (voice: string | null) => void;
}) {
  const voices = useAsync(() => unlessMissing(api.voices(language)), [language]);
  const [playing, setPlaying] = useState<string | null>(null);
  const [loading, setLoading] = useState<string | null>(null);
  const [error, setError] = useState<{ message: string; noKey: boolean } | null>(null);
  const audio = useRef<HTMLAudioElement | null>(null);

  useEffect(() => () => audio.current?.pause(), []);
  useEffect(() => {
    audio.current?.pause();
    setPlaying(null);
    setError(null);
  }, [language]);

  const play = async (voice: Voice) => {
    if (playing === voice.id) {
      audio.current?.pause();
      setPlaying(null);
      return;
    }
    audio.current?.pause();
    setError(null);
    const key = `${voice.id}:${language}`;
    let url = samples.get(key);
    if (!url) {
      setLoading(voice.id);
      try {
        const blob = await api.voicePreview({ voice: voice.id, language, text: voice.sample_text || undefined });
        url = URL.createObjectURL(blob);
        samples.set(key, url);
      } catch (err) {
        const status = err instanceof ApiError ? err.status : 0;
        setError({ message: status === 404 ? "Voice previews need a server update." : (err as Error).message, noKey: status === 409 });
        return;
      } finally {
        setLoading(null);
      }
    }
    const el = new Audio(url);
    audio.current = el;
    el.onended = () => setPlaying(null);
    setPlaying(voice.id);
    el.play().catch(() => setPlaying(null));
  };

  if (voices.loading) {
    return (
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-14 rounded-lg" />
        ))}
      </div>
    );
  }
  if (voices.error) return <p className="text-xs text-critical">Couldn't load voices: {voices.error}</p>;
  if (voices.data === null) {
    return <p className="text-xs text-ink-muted">Voice choice needs a server update. Calls use the default voice meanwhile.</p>;
  }

  const list = voices.data.filter((v) => !v.languages.length || v.languages.includes(language));
  const options: Array<Voice | null> = [null, ...list];
  const current = value ?? null;
  const missing = current && !list.some((v) => v.id === current);

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowRight", "ArrowDown", "ArrowLeft", "ArrowUp"].includes(e.key)) return;
    e.preventDefault();
    const i = options.findIndex((o) => (o?.id ?? null) === current);
    const next = options[(i + (e.key === "ArrowRight" || e.key === "ArrowDown" ? 1 : options.length - 1)) % options.length];
    onChange(next?.id ?? null);
    requestAnimationFrame(() => e.currentTarget.querySelector<HTMLElement>('[aria-checked="true"]')?.focus());
  };

  return (
    <div className="space-y-2">
      <div role="radiogroup" aria-label="Voice" onKeyDown={onKeyDown} className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {options.map((voice) => {
          const id = voice?.id ?? null;
          const selected = id === current;
          return (
            <div
              key={id ?? "default"}
              className={cx(
                "flex items-center gap-2 rounded-lg border px-3 py-2 transition-colors duration-150",
                selected ? "border-brand/60 bg-brand/6 ring-2 ring-brand/15" : "border-line hover:border-line-strong hover:bg-subtle/60",
              )}
            >
              <button
                type="button"
                role="radio"
                aria-checked={selected}
                tabIndex={selected ? 0 : -1}
                onClick={() => onChange(id)}
                className="flex min-w-0 flex-1 items-center gap-2 text-left"
              >
                <span
                  className={cx(
                    "flex h-4 w-4 shrink-0 items-center justify-center rounded-full border",
                    selected ? "border-brand bg-brand text-on-brand" : "border-line-control",
                  )}
                  aria-hidden
                >
                  {selected && <IconCheck size={10} />}
                </span>
                <span className="min-w-0">
                  <span className="block truncate text-sm font-medium text-ink">{voice ? voice.name : "Default voice"}</span>
                  <span className="block truncate text-2xs capitalize text-ink-muted">{voice ? voice.gender || "Voice" : "The deployment's standard speaker"}</span>
                </span>
              </button>
              {voice && (
                <button
                  type="button"
                  onClick={() => void play(voice)}
                  aria-label={playing === voice.id ? `Stop ${voice.name}` : `Play a sample of ${voice.name}`}
                  aria-pressed={playing === voice.id}
                  className={cx(
                    "flex h-8 w-8 shrink-0 items-center justify-center rounded-full border transition-colors",
                    playing === voice.id ? "border-brand bg-brand text-on-brand" : "border-line-strong bg-surface text-ink-secondary hover:border-brand/60 hover:text-brand",
                  )}
                >
                  {loading === voice.id ? <Spinner size={12} /> : playing === voice.id ? <IconPause size={12} /> : <IconPlay size={12} />}
                </button>
              )}
            </div>
          );
        })}
      </div>
      {list.length === 0 && <p className="text-xs text-ink-muted">No named voices for {languageLabel} yet; the default voice speaks it.</p>}
      {missing && (
        <p className="text-xs text-warning" role="alert">
          The chosen voice doesn't speak {languageLabel}. Pick one above, or the default.
        </p>
      )}
      {error && (
        <p className="text-xs text-critical" role="alert">
          {error.message}{" "}
          {error.noKey && (
            <Link to="/app/integrations?tab=telephony" className="font-medium text-brand hover:underline">
              Set up Sarvam
            </Link>
          )}
        </p>
      )}
    </div>
  );
}
