/**
 * Create an account, at /register. Shares the login page's layout. What it
 * asks for depends on `registration.mode` from /api/auth/status:
 *
 *   owner   no account exists yet: this one becomes the owner and turns
 *           sign-in on (plus a setup code, the server's ADMIN_PASSWORD, when
 *           the server requires it)
 *   invite  an invite code, prefilled from ?invite=
 *   open    nothing extra; you join as a member
 *   closed  no form: ask the owner for access
 *
 * Backends from before accounts get a plain "not available here" state.
 * Success signs you in and continues to `next` (or the overview).
 */

import { useRef, useState, type FormEvent, type ReactNode } from "react";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { ApiError, type RegisterRequest, type RegistrationMode } from "../api";
import { useAuth } from "../auth";
import { BRAND } from "../brand";
import type { AgentState } from "../components/AgentAvatar";
import {
  AuthField,
  AuthHeading,
  AuthLayout,
  AuthSkeleton,
  EMAIL_SHAPE,
  PasswordInput,
  authInputClass,
  useCooldown,
} from "../components/site/AuthLayout";
import { IconArrowRight, IconCheck, IconClose, IconRefresh } from "../components/icons";
import { Button, ButtonLink, Callout, cx } from "../components/ui";
import { useDocumentTitle } from "../hooks";
import { APP, LOGIN, safeNext } from "../routes";

export default function Register() {
  const auth = useAuth();
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const invite = params.get("invite") ?? "";
  const [mood, setMood] = useState<AgentState>("idle");
  useDocumentTitle("Create an account");

  const loginHref = next === APP ? LOGIN : `${LOGIN}?next=${encodeURIComponent(next)}`;

  let body: ReactNode;
  if (auth.phase === "checking") body = <AuthSkeleton />;
  else if (auth.phase === "unknown") body = <Unreachable />;
  else if (auth.phase === "signed-in") {
    // Opening someone's invite link while signed in: say so rather than
    // silently dropping the invite.
    if (!invite) return <Navigate to={next} replace />;
    body = <AlreadySignedIn next={next} />;
  } else if (!auth.registration) body = <NotAvailable loginHref={loginHref} open={auth.phase === "open"} next={next} />;
  else if (auth.registration.mode === "closed") body = <Closed loginHref={loginHref} />;
  else
    body = (
      <RegisterForm
        mode={auth.registration.mode}
        setupRequired={auth.registration.setup_code_required}
        invite={invite}
        loginHref={loginHref}
        setMood={setMood}
      />
    );

  return <AuthLayout mood={auth.phase === "unknown" ? "error" : mood}>{body}</AuthLayout>;
}

// ---------------------------------------------------------------------------

function Unreachable() {
  const { recheck } = useAuth();
  return (
    <div>
      <AuthHeading title="Can't reach the server">
        We couldn't ask the {BRAND.name} server how new accounts are created. Check that the API is running, then try
        again.
      </AuthHeading>
      <Button size="lg" className="mt-8 w-full" icon={<IconRefresh size={15} />} onClick={recheck}>
        Try again
      </Button>
    </div>
  );
}

function AlreadySignedIn({ next }: { next: string }) {
  // Plain signOut (no redirect): this page re-renders as the invite form.
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  return (
    <div>
      <AuthHeading title="You're already signed in">
        {user?.email ? `You're signed in as ${user.email}. ` : ""}To use this invite for a new account, sign out first.
      </AuthHeading>
      <div className="mt-8 flex flex-col gap-3">
        <Button size="lg" onClick={signOut}>
          Sign out and use the invite
        </Button>
        <Button size="lg" variant="secondary" onClick={() => navigate(next)}>
          Go to the console
        </Button>
      </div>
    </div>
  );
}

function NotAvailable({ loginHref, open, next }: { loginHref: string; open: boolean; next: string }) {
  return (
    <div>
      <AuthHeading title="Accounts aren't available here">
        This {BRAND.name} server doesn't support accounts yet.{" "}
        {open ? "The console is open, so you can go straight in." : "Sign in with the workspace's admin password instead."}
      </AuthHeading>
      <ButtonLink to={open ? next : loginHref} size="lg" className="mt-8 w-full" iconRight={<IconArrowRight size={15} />}>
        {open ? "Enter the console" : "Go to sign in"}
      </ButtonLink>
    </div>
  );
}

function Closed({ loginHref }: { loginHref: string }) {
  return (
    <div>
      <AuthHeading title="Registration is closed">
        This workspace isn't taking new sign-ups. Ask your workspace owner for access, and they can send you an invite.
      </AuthHeading>
      <ButtonLink to={loginHref} size="lg" className="mt-8 w-full">
        I already have an account
      </ButtonLink>
    </div>
  );
}

// ---------------------------------------------------------------------------

type Field = "name" | "email" | "password" | "invite_code" | "setup_code";
type Errors = Partial<Record<Field | "form", string>>;

/** The server's rules (accounts spec §1), checked here first so errors arrive as you type. */
function passwordRules(password: string, email: string) {
  return [
    { ok: password.length >= 10 && password.length <= 128, text: "10 to 128 characters" },
    { ok: password.length > 0 && !/^\d+$/.test(password), text: "Not only numbers" },
    {
      ok: password.length > 0 && password.trim().toLowerCase() !== email.trim().toLowerCase(),
      text: "Not the same as your email",
    },
  ];
}

const COPY: Record<Exclude<RegistrationMode, "closed">, { title: string; lead: string; submit: string }> = {
  owner: {
    title: "Create the owner account",
    lead: "You're the first one here. This account owns the workspace, and creating it turns on sign-in for everyone who opens the console.",
    submit: "Create the owner account",
  },
  invite: {
    title: "Join your team",
    lead: "Create your account with the invite code you were sent.",
    submit: "Create account",
  },
  open: {
    title: "Create your account",
    lead: "Anyone can register on this workspace. You'll join as a member.",
    submit: "Create account",
  },
};

function RegisterForm({
  mode,
  setupRequired,
  invite,
  loginHref,
  setMood,
}: {
  mode: Exclude<RegistrationMode, "closed">;
  setupRequired: boolean;
  invite: string;
  loginHref: string;
  setMood: (mood: AgentState) => void;
}) {
  const { register, recheck } = useAuth();
  const [values, setValues] = useState({ name: "", email: "", password: "", invite_code: invite, setup_code: "" });
  const [touched, setTouched] = useState<Partial<Record<Field, boolean>>>({});
  const [errors, setErrors] = useState<Errors>({});
  const [busy, setBusy] = useState(false);
  const cooldown = useCooldown();
  const refs = {
    name: useRef<HTMLInputElement>(null),
    email: useRef<HTMLInputElement>(null),
    password: useRef<HTMLInputElement>(null),
    invite_code: useRef<HTMLInputElement>(null),
    setup_code: useRef<HTMLInputElement>(null),
  };
  const needsInvite = mode === "invite";
  const needsSetup = mode === "owner" && setupRequired;
  const copy = COPY[mode];
  const rules = passwordRules(values.password, values.email);

  const validate = (v = values): Errors => {
    const e: Errors = {};
    if (!v.name.trim()) e.name = "Enter your name.";
    else if (v.name.trim().length > 100) e.name = "Keep your name under 100 characters.";
    if (!v.email.trim()) e.email = "Enter your email address.";
    else if (v.email.trim().length > 254 || !EMAIL_SHAPE.test(v.email.trim())) e.email = "That doesn't look like an email address.";
    const failed = passwordRules(v.password, v.email).find((r) => !r.ok);
    if (!v.password) e.password = "Choose a password.";
    else if (failed) e.password = `Your password needs to be: ${failed.text.toLowerCase()}.`;
    if (needsInvite && !v.invite_code.trim()) e.invite_code = "Enter the invite code you were sent.";
    if (needsSetup && !v.setup_code) e.setup_code = "Enter the setup code.";
    return e;
  };

  const set = (field: Field, value: string) => {
    const nextValues = { ...values, [field]: value };
    setValues(nextValues);
    // Once a field has been left (or submitted), keep its error current as you type.
    if (touched[field] || errors[field]) {
      const found = validate(nextValues);
      setErrors((x) => ({ ...x, [field]: found[field] }));
    }
    if (!busy) setMood(value ? "listening" : "idle");
  };

  const blur = (field: Field) => {
    setTouched((t) => ({ ...t, [field]: true }));
    if (values[field]) setErrors((x) => ({ ...x, [field]: validate()[field] }));
    if (!busy) setMood("idle");
  };

  const focusFirst = (e: Errors) => {
    const order: Field[] = ["name", "email", "password", "invite_code", "setup_code"];
    const first = order.find((f) => e[f]);
    if (first) refs[first].current?.focus();
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (busy || cooldown.active) return;
    const found = validate();
    setErrors(found);
    setTouched({ name: true, email: true, password: true, invite_code: true, setup_code: true });
    if (Object.keys(found).some((k) => found[k as Field])) return focusFirst(found);

    const body: RegisterRequest = { name: values.name.trim(), email: values.email.trim(), password: values.password };
    if (needsInvite) body.invite_code = values.invite_code.trim();
    if (needsSetup) body.setup_code = values.setup_code;

    setBusy(true);
    setMood("thinking");
    try {
      await register(body, () => setMood("ended"), 900);
    } catch (err) {
      setBusy(false);
      setMood("error");
      const e = err instanceof ApiError ? err : new ApiError((err as Error).message, 0);
      const message = e.message || "Couldn't create the account. Try again.";
      let mapped: Errors;
      if (e.status === 409) mapped = { email: "An account with this email already exists. Sign in instead." };
      else if (e.status === 429) {
        cooldown.start(60);
        mapped = { form: "Too many attempts from this device. Wait a minute, then try again." };
      } else if (e.status === 403) {
        if (/closed/i.test(message)) {
          recheck();
          mapped = { form: message };
        } else if (/setup/i.test(message)) mapped = { setup_code: message };
        else if (/invite/i.test(message) && needsInvite) mapped = { invite_code: message };
        else mapped = { form: message };
      } else if (e.status === 400) {
        if (/password/i.test(message)) mapped = { password: message };
        else if (/e-?mail/i.test(message)) mapped = { email: message };
        else if (/name/i.test(message)) mapped = { name: message };
        else if (/invite/i.test(message) && needsInvite) mapped = { invite_code: message };
        else mapped = { form: message };
      } else mapped = { form: message };
      setErrors(mapped);
      focusFirst(mapped);
    }
  };

  const text = (field: Field, props: { label: string; type?: string; autoComplete: string; hint?: ReactNode; placeholder?: string; inputMode?: "email" | "text" }) => (
    <AuthField label={props.label} error={errors[field]} hint={props.hint}>
      {({ id, describedBy, invalid }) => (
        <input
          ref={refs[field]}
          id={id}
          name={field}
          type={props.type ?? "text"}
          inputMode={props.inputMode}
          autoComplete={props.autoComplete}
          spellCheck={false}
          value={values[field]}
          placeholder={props.placeholder}
          onChange={(e) => set(field, e.target.value)}
          onBlur={() => blur(field)}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          className={cx(authInputClass, (field === "invite_code" || field === "setup_code") && "font-mono")}
        />
      )}
    </AuthField>
  );

  return (
    <div>
      <AuthHeading title={copy.title}>{copy.lead}</AuthHeading>

      {errors.form && (
        <Callout tone={cooldown.active ? "warning" : "critical"} className="mt-6">
          {errors.form}
        </Callout>
      )}

      <form onSubmit={submit} className="mt-6 space-y-5" noValidate>
        {needsInvite &&
          text("invite_code", {
            label: "Invite code",
            autoComplete: "off",
            hint: invite ? "Filled in from your invite link." : "It's in the invite link your owner or admin sent.",
          })}
        {text("name", { label: "Name", autoComplete: "name" })}
        {text("email", { label: "Email", type: "email", inputMode: "email", autoComplete: "email", placeholder: "you@company.com" })}

        <AuthField
          label="Password"
          error={errors.password}
          hint={
            <ul className="grid gap-1" aria-label="Password rules">
              {rules.map((rule) => (
                <li key={rule.text} className={cx("flex items-center gap-1.5", rule.ok ? "text-good" : "text-ink-muted")}>
                  {rule.ok ? <IconCheck size={12} /> : <IconClose size={12} />}
                  {rule.text}
                  <span className="sr-only">{rule.ok ? "(done)" : "(not yet)"}</span>
                </li>
              ))}
            </ul>
          }
        >
          {({ id, describedBy, invalid }) => (
            <PasswordInput
              ref={refs.password}
              id={id}
              name="new-password"
              autoComplete="new-password"
              value={values.password}
              onChange={(e) => set("password", e.target.value)}
              onBlur={() => blur("password")}
              aria-invalid={invalid}
              aria-describedby={describedBy}
            />
          )}
        </AuthField>

        {needsSetup &&
          text("setup_code", {
            label: "Setup code",
            type: "password",
            autoComplete: "off",
            hint: (
              <>
                The server's <code className="font-mono">ADMIN_PASSWORD</code>. It proves you run this deployment, so a
                stranger can't claim it first.
              </>
            ),
          })}

        <Button type="submit" size="lg" className="w-full" loading={busy} disabled={cooldown.active}>
          {busy ? "Creating your account…" : cooldown.active ? `Try again in ${cooldown.label}` : copy.submit}
        </Button>
      </form>

      <p className="mt-6 text-sm text-ink-secondary">
        Already have an account?{" "}
        <Link to={loginHref} className="font-medium text-brand underline-offset-4 hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
