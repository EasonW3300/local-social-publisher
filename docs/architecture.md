# Architecture baseline

## Runtime

The packaged application starts a loopback-only FastAPI service, an APScheduler
worker, and a system-tray process. The React frontend opens in the user's default
browser. Platform browser automation uses isolated persistent Chromium profiles.

## Core flow

1. Accept one image, a title of 1–20 characters, Markdown of 1–2,000 characters,
   and one or both first-release platforms.
2. Copy the image into managed application storage and compute a content
   fingerprint.
3. Render deterministic platform previews and ask for one confirmation.
4. Create independent platform jobs for immediate or scheduled execution.
5. Persist every transition and expose grouped results in the frontend.

## Reliability boundaries

- WeChat official API is preferred. Browser fallback is used only when publishing
  permission is known to be unavailable and the user enabled it.
- CSDN delivery ends at an editable draft. Human review remains mandatory.
- A platform failure never rolls back or blocks a successful sibling platform.
- Transient failures retry at most three times. Ambiguous browser submissions
  become `unknown` and are never retried automatically.
- Missed schedules run at startup only inside a 30-minute grace period.

## Security boundaries

- HTTP listens only on `127.0.0.1` and uses an installation token plus CSRF
  protection.
- Credentials use the operating-system secret store. Linux may fall back to a
  password-unlocked encrypted vault.
- Cookies remain inside dedicated browser profiles.
- Tokens, cookies, secrets, and sensitive platform responses are redacted from
  logs and API responses.

