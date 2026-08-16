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

