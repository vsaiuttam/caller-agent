# Samvaad — Accounts & registration (round 3b spec)

Owner: lead. The contract for DEV-AGENT (`src/voiceagent/**`), TEST-AGENT
(`tests/**`) and UI-UX-AGENT (`frontend/**`). Names in `code` are exact.
Base: `5390d4e`. This extends the opt-in auth from `docs/v2-spec.md` §1.6
(`src/voiceagent/api/auth.py`); everything that works today keeps working.

## 0. Model and decisions
- **User accounts** replace "one shared password" as the normal way in. The
  legacy `ADMIN_PASSWORD` keeps working as a break-glass sign-in (existing
  tests must still pass unchanged).
- **Access control is on** when `ADMIN_PASSWORD` is set **or** at least one
  user exists. With neither, the console stays open exactly as today.
- **Owner bootstrap:** when no user exists, the first successful registration
  creates the **owner**, which immediately turns access control on. If
  `ADMIN_PASSWORD` is set, that bootstrap registration must also present it as
  `setup_code` (so a public deploy can't be claimed by a stranger).
- **After the owner exists**, `REGISTRATION_MODE` (read at call time) decides:
  `invite` (default) — a valid invite code is required; `open` — anyone may
  register as a `member`; `closed` — registration refused (403).
- **Roles:** `owner` (exactly one; can't be removed or demoted), `admin`
  (manages team + invites), `member` (uses the console). Everyone signed in can
  use the whole console as today; only owner/admin reach the team endpoints.

## 1. Backend — DEV-AGENT
### Storage (additive; Postgres-safe)
- `users`: `id` String(36) PK, `email` String(254) unique (stored lowercase,
  trimmed), `name` String(100), `password_hash` String(255), `role`
  String(16), `disabled` Boolean default FALSE, `created_at`,
  `last_login_at` nullable.
- `invites`: `id` String(36) PK, `code_hash` String(64) unique (SHA-256 hex of
  the code — the code itself is never stored), `email` String(254) nullable
  (if set, only that email may use it), `role` String(16) (`member`|`admin`),
  `created_by` String(36), `created_at`, `expires_at`, `used_at` nullable,
  `used_by` String(36) nullable, `revoked` Boolean default FALSE.

### `api/auth.py` additions (keep existing names/behaviour)
- `hash_password(password: str) -> str` / `check_password_hash(password,
  stored) -> bool` — `hashlib.scrypt` (n=2**14, r=8, p=1, 16-byte random salt,
  64-byte key), stored as `scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>`; constant
  time compare. No new dependency.
- `issue_token(now=None, *, subject: str = "admin", role: str = "owner")` —
  payload gains `sub` and `role`; old callers unchanged.
- `token_claims(token, now=None) -> dict | None` — `{"sub", "role", "exp"}`
  for a valid token, else None. `verify_token` stays (bool).
- `auth_enabled()` becomes true when `ADMIN_PASSWORD` is set **or** a user
  exists. Keep it synchronous and cheap: an in-process flag loaded at startup
  (`init_db`/lifespan) and set on the first registration; tests may call
  `auth.set_users_exist(bool)` to control it.
- A token for a user that has since been disabled or deleted must stop working
  within the same process immediately (track revoked subjects in memory,
  updated by the team endpoints) and after a restart (tokens whose `sub` no
  longer resolves to an enabled user are rejected on first use).
- Passwords: 10–128 chars; not all digits; not equal to the email. Emails:
  basic shape check, ≤254 chars.
- Throttle: reuse `LoginThrottle` for login **and** register (per client).

### Endpoints
- `GET /api/auth/status` → `{auth_enabled, authenticated, user: {id, email,
  name, role} | null, registration: {mode: "owner"|"invite"|"open"|"closed",
  setup_code_required: bool}}` — `mode: "owner"` while no user exists
  (`setup_code_required` = `ADMIN_PASSWORD` is set). Legacy admin-password
  tokens report `user: {id: "admin", email: "", name: "Admin", role: "owner"}`.
- `POST /api/auth/register` `{name, email, password, invite_code?,
  setup_code?}` → 201 `{token, expires_at, user}`; 400 invalid input (message
  says which rule), 403 closed / bad invite / bad setup code, 409 email taken,
  429 throttled. Using an invite marks it used (single use); an expired,
  revoked, used or email-mismatched invite → 403 with a readable reason.
- `POST /api/auth/login` accepts `{email, password}` (user) **or**
  `{password}` (legacy admin). Wrong credentials → 401 with one generic
  message (never reveal whether the email exists). Disabled user → 403
  "This account is disabled". Updates `last_login_at`.
- Team (owner/admin only, else 403; all behind auth):
  - `GET /api/team/users` → `[{id, email, name, role, disabled, created_at,
    last_login_at}]` (never `password_hash`).
  - `PATCH /api/team/users/{id}` `{role?: "admin"|"member", disabled?: bool}`
    — the owner can't be changed; admins can't change other admins; you can't
    disable yourself.
  - `DELETE /api/team/users/{id}` — same guards; 204.
  - `POST /api/team/invites` `{email?, role: "member"|"admin" = "member",
    expires_in_days: int = 7 (1–30)}` → 201 `{id, code, email, role,
    expires_at}` — the **only** time the code is returned. Only the owner can
    invite admins.
  - `GET /api/team/invites` → pending + recent: `[{id, email, role,
    created_at, expires_at, used_at, revoked, status:
    "pending"|"used"|"expired"|"revoked"}]` (no codes).
  - `DELETE /api/team/invites/{id}` → revoke; 204.
- `/api/health` adds `accounts: {users: int, registration_mode: str}`.

## 2. Tests — TEST-AGENT
New files only: `tests/test_accounts.py` (hashing, tokens with sub/role,
auth_enabled rules, owner bootstrap with/without setup code, registration
modes, invites: single use / expiry / revoked / email-bound / role, password
& email rules, generic login errors, disabled + deleted users locked out
immediately, legacy admin password still works, throttling, hashes never in
responses, health) and `tests/test_team_api.py` (role guards, owner
protections, invite listing without codes, revoke). Same conventions as
before (standalone `_run_all()` with `sys.stdout.reconfigure(errors=
"backslashreplace")`, temp SQLite via `dependency_overrides[get_session]` +
monkeypatched `storage.SessionLocal`, env set/restored in each test, call
`auth.set_users_exist(False)` in teardown, imports of new names inside tests,
Red first). Existing `tests/test_auth.py` must keep passing untouched.

## 3. Frontend — UI-UX-AGENT (additive to the round-3 brief)
- `/login`: email + password form (the main path), "Forgot?" note ("ask your
  workspace owner" — there's no email service), a secondary "Use the admin
  password" toggle when `auth_enabled` and the legacy mode is useful, and a
  "Create an account" link to `/register` unless `registration.mode` is
  `closed`.
- `/register`: name, email, password (with a strength hint matching the rules
  and show/hide), plus:
  - `mode: "owner"` → "Create the owner account" copy explaining it locks the
    console; a `setup_code` field when `setup_code_required`.
  - `mode: "invite"` → invite code field, prefilled from `?invite=`.
  - `mode: "open"` → no code.
  - `mode: "closed"` → a friendly "Registration is closed — ask your owner for
    access" state.
  Success → signed in → `next` or `/app`. Errors shown inline per field.
- Console: **Settings → Team** (owner/admin only): users table (role select,
  disable toggle, remove with confirm; guards mirrored in the UI), and
  invites — create (email optional, role, expiry) → shows the code once with a
  copyable invite link `<origin>/register?invite=<code>`; pending list with
  revoke. The user menu shows the signed-in name/email and role.
- Keep the landing, login styling, footers and design system from the round-3
  brief; register shares the login layout.
