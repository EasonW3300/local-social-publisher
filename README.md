# Local Social Publisher

Local Social Publisher is a local-first, open-source publishing tool for a single
image, a title of up to 20 characters, and Markdown copy of up to 2,000
characters.

The first release targets:

- WeChat Official Accounts: publish through the official API when available,
  with an explicitly enabled browser fallback.
- CSDN: create a draft in a dedicated Chromium profile and open it for human
  review.

The application will expose a React user interface through a loopback-only
FastAPI service. SQLite stores grouped submissions, per-platform jobs, rendered
payloads, links, and audit events. Secrets are never stored in SQLite.
Every write request also carries an in-memory, per-process session token fetched
by the same-origin frontend, preventing an unrelated website from silently
triggering a local publication.

## Status

Active development. The domain and persistence contracts are implemented first;
publishing adapters and the frontend are added behind tested interfaces.

## Development

Python 3.10 or newer is required.

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

The project is licensed under Apache-2.0.

## Run the application

Build the frontend once, then start the loopback service:

```bash
cd frontend
npm install
npm run build
cd ..
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/local-social-publisher
```

The UI opens at `http://127.0.0.1:8765`. Use **账号设置** to configure a
WeChat AppID/AppSecret or open the isolated WeChat and CSDN browser profiles for
interactive login.

## Publishing guarantees

- WeChat official publishing stores `publish_id`, polls the asynchronous result,
  and only marks success after a public URL is returned.
- Browser fallback is explicit. CAPTCHA, QR, administrator confirmation, or
  platform risk controls always pause for the user.
- CSDN completion means a draft was created and its editor URL was saved. The
  user performs the final CSDN review.
- Temporary failures retry at most three times. An ambiguous submit is terminal
  until manually inspected.
