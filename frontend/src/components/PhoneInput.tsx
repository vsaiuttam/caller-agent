/**
 * A phone number as two fields: the country (its dialling code) and the
 * number as people write it locally. The parent sees one E.164 string —
 * "+919876543210" — or "" while nothing usable is typed.
 *
 * A number typed with its own "+" wins over the selected country, so pasting
 * an international number from anywhere still works.
 */

import { useEffect, useState } from "react";
import { cx } from "./ui";
import { IconChevronDown } from "./icons";

export interface Country {
  iso: string;
  name: string;
  dial: string;
  /** Digits in a national number, without the trunk 0. */
  lengths: number[];
  /** Where most numbers in the country ring, for a contact's local time. */
  timezone: string;
  example: string;
}

export const COUNTRIES: Country[] = [
  { iso: "IN", name: "India", dial: "91", lengths: [10], timezone: "Asia/Kolkata", example: "98765 43210" },
  { iso: "US", name: "United States", dial: "1", lengths: [10], timezone: "America/New_York", example: "415 555 0123" },
  { iso: "CA", name: "Canada", dial: "1", lengths: [10], timezone: "America/Toronto", example: "416 555 0123" },
  { iso: "GB", name: "United Kingdom", dial: "44", lengths: [10], timezone: "Europe/London", example: "7400 123456" },
  { iso: "AE", name: "United Arab Emirates", dial: "971", lengths: [9], timezone: "Asia/Dubai", example: "50 123 4567" },
  { iso: "SA", name: "Saudi Arabia", dial: "966", lengths: [9], timezone: "Asia/Riyadh", example: "51 234 5678" },
  { iso: "QA", name: "Qatar", dial: "974", lengths: [8], timezone: "Asia/Qatar", example: "3312 3456" },
  { iso: "KW", name: "Kuwait", dial: "965", lengths: [8], timezone: "Asia/Kuwait", example: "500 12345" },
  { iso: "OM", name: "Oman", dial: "968", lengths: [8], timezone: "Asia/Muscat", example: "9212 3456" },
  { iso: "BH", name: "Bahrain", dial: "973", lengths: [8], timezone: "Asia/Bahrain", example: "3600 1234" },
  { iso: "SG", name: "Singapore", dial: "65", lengths: [8], timezone: "Asia/Singapore", example: "8123 4567" },
  { iso: "MY", name: "Malaysia", dial: "60", lengths: [9, 10], timezone: "Asia/Kuala_Lumpur", example: "12 345 6789" },
  { iso: "AU", name: "Australia", dial: "61", lengths: [9], timezone: "Australia/Sydney", example: "412 345 678" },
  { iso: "NZ", name: "New Zealand", dial: "64", lengths: [8, 9, 10], timezone: "Pacific/Auckland", example: "21 123 4567" },
  { iso: "DE", name: "Germany", dial: "49", lengths: [10, 11], timezone: "Europe/Berlin", example: "1512 3456789" },
  { iso: "FR", name: "France", dial: "33", lengths: [9], timezone: "Europe/Paris", example: "6 12 34 56 78" },
  { iso: "NL", name: "Netherlands", dial: "31", lengths: [9], timezone: "Europe/Amsterdam", example: "6 12345678" },
  { iso: "IE", name: "Ireland", dial: "353", lengths: [9], timezone: "Europe/Dublin", example: "85 012 3456" },
  { iso: "ZA", name: "South Africa", dial: "27", lengths: [9], timezone: "Africa/Johannesburg", example: "71 123 4567" },
  { iso: "KE", name: "Kenya", dial: "254", lengths: [9], timezone: "Africa/Nairobi", example: "712 123456" },
  { iso: "NG", name: "Nigeria", dial: "234", lengths: [10], timezone: "Africa/Lagos", example: "802 123 4567" },
  { iso: "LK", name: "Sri Lanka", dial: "94", lengths: [9], timezone: "Asia/Colombo", example: "71 234 5678" },
  { iso: "NP", name: "Nepal", dial: "977", lengths: [10], timezone: "Asia/Kathmandu", example: "984 1234567" },
  { iso: "BD", name: "Bangladesh", dial: "880", lengths: [10], timezone: "Asia/Dhaka", example: "1812 345678" },
  { iso: "PH", name: "Philippines", dial: "63", lengths: [10], timezone: "Asia/Manila", example: "905 123 4567" },
  { iso: "ID", name: "Indonesia", dial: "62", lengths: [9, 10, 11, 12], timezone: "Asia/Jakarta", example: "812 3456 7890" },
  { iso: "JP", name: "Japan", dial: "81", lengths: [10], timezone: "Asia/Tokyo", example: "90 1234 5678" },
];

const BY_ISO = new Map(COUNTRIES.map((c) => [c.iso, c]));
const STORE_KEY = "samvaad.phone.country";

function rememberedCountry(fallback: string): Country {
  try {
    const iso = window.localStorage.getItem(STORE_KEY);
    if (iso && BY_ISO.has(iso)) return BY_ISO.get(iso)!;
  } catch {
    // Storage blocked: the default is fine.
  }
  return BY_ISO.get(fallback) ?? COUNTRIES[0];
}

/** The country a stored E.164 number belongs to, longest code first. */
export function countryOf(e164: string): Country | undefined {
  const digits = e164.replace(/^\+/, "");
  return [...COUNTRIES]
    .sort((a, b) => b.dial.length - a.dial.length)
    .find((c) => digits.startsWith(c.dial) && c.lengths.includes(digits.length - c.dial.length));
}

/** "+919876543210", or "" when nothing is typed. Not a validity check. */
export function toE164(country: Country, typed: string): string {
  const trimmed = typed.trim();
  if (trimmed.startsWith("+")) {
    const digits = trimmed.replace(/\D/g, "");
    return digits ? `+${digits}` : "";
  }
  // Drop the trunk 0 people write in front of a local number (098765…).
  const national = trimmed.replace(/\D/g, "").replace(/^0+/, "");
  return national ? `+${country.dial}${national}` : "";
}

/** Plausible for its country, or any 8–15 digit E.164 when the country is unknown. */
export function isValidPhone(e164: string): boolean {
  if (!/^\+[1-9]\d{7,14}$/.test(e164)) return false;
  const digits = e164.slice(1);
  const matches = COUNTRIES.filter((c) => digits.startsWith(c.dial));
  if (!matches.length) return true;
  return matches.some((c) => c.lengths.includes(digits.length - c.dial.length));
}

export function PhoneInput({
  value,
  onChange,
  onCountryChange,
  onBlur,
  disabled = false,
  invalid = false,
  defaultCountry = "IN",
  id,
  label = "Phone number",
}: {
  /** E.164, as last emitted. Used only to seed the fields. */
  value: string;
  onChange: (e164: string) => void;
  onCountryChange?: (country: Country) => void;
  onBlur?: () => void;
  disabled?: boolean;
  invalid?: boolean;
  defaultCountry?: string;
  id?: string;
  /** For screen readers; the visible label is the surrounding Field's. */
  label?: string;
}) {
  const [country, setCountry] = useState<Country>(() => countryOf(value) ?? rememberedCountry(defaultCountry));
  const [typed, setTyped] = useState(() => {
    const seeded = countryOf(value);
    return seeded ? value.slice(seeded.dial.length + 1) : value;
  });

  // The parent cleared the value (e.g. after adding a contact).
  useEffect(() => {
    if (!value) setTyped("");
  }, [value]);

  const pickCountry = (iso: string) => {
    const next = BY_ISO.get(iso);
    if (!next) return;
    setCountry(next);
    onCountryChange?.(next);
    try {
      window.localStorage.setItem(STORE_KEY, iso);
    } catch {
      // Not remembered; nothing else changes.
    }
    onChange(toE164(next, typed));
  };

  return (
    <div
      className={cx(
        "flex h-10 items-stretch overflow-hidden rounded-md border bg-surface transition-[border-color,box-shadow] duration-150 focus-within:border-brand focus-within:ring-3 focus-within:ring-brand/20 sm:h-9",
        invalid ? "border-critical" : "border-line-control hover:border-ink-secondary",
        disabled && "opacity-60",
      )}
    >
      {/* The visible part is a compact "IN +91"; the native select sits over
          it, invisible, so the open list still shows full country names. */}
      <span className="relative flex shrink-0 items-center gap-1.5 border-r border-line bg-subtle/60 pl-3 pr-2 text-sm text-ink">
        <span className="rounded bg-surface px-1 py-px text-[0.6875rem] font-semibold tracking-wide text-ink-secondary">{country.iso}</span>
        <span className="tnum">+{country.dial}</span>
        <IconChevronDown size={13} className="text-ink-muted" />
        <select
          aria-label="Country code"
          value={country.iso}
          disabled={disabled}
          onChange={(e) => pickCountry(e.target.value)}
          className="absolute inset-0 h-full w-full cursor-pointer appearance-none opacity-0 disabled:cursor-not-allowed"
        >
          {COUNTRIES.map((c) => (
            <option key={c.iso} value={c.iso}>
              {c.name} (+{c.dial})
            </option>
          ))}
        </select>
      </span>
      <input
        id={id}
        type="tel"
        inputMode="tel"
        autoComplete="tel-national"
        aria-label={label}
        aria-invalid={invalid}
        placeholder={country.example}
        value={typed}
        disabled={disabled}
        onBlur={onBlur}
        onChange={(e) => {
          setTyped(e.target.value);
          onChange(toE164(country, e.target.value));
        }}
        className="tnum h-full min-w-0 flex-1 bg-transparent px-3 text-sm text-ink outline-none placeholder:text-ink-muted disabled:cursor-not-allowed"
      />
    </div>
  );
}
