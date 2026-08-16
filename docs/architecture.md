# Architecture

## Scope

The first release is a single-user, local-first publisher for one image, a title
of at most 20 characters, and Markdown copy of at most 2,000 characters. A
submission can target WeChat Official Accounts, CSDN, or both. Immediate and
scheduled execution share the same durable job model.

## Components

```text
React composer
    |
    | loopback HTTP + per-process write token
    v
FastAPI application
    |-- validation and deterministic platform previews
    |-- account settings (secret values delegated to the OS keyring)
    |-- grouped submission and recovery endpoints
    v
SQLite repository + managed image store
    |
    v
APScheduler -> single-thread publisher executor -> platform adapters
                                                |-- WeChat official API
                                                |-- explicit WeChat browser fallback
                                                `-- CSDN isolated browser profile
```

The browser drivers and their persistent contexts are created, used, and closed
on the same publisher thread. This avoids Playwright/greenlet cross-thread
access and also serializes interactive browser work.

## Submission flow

1. The frontend validates required fields and requests deterministic previews.
2. The user confirms the rendered output. A normalized content and image hash
   prevents accidental duplicates unless the user explicitly confirms them.
3. One `posts` row and one `platform_jobs` row per selected platform are written
   in a single SQLite transaction. Rendered platform payloads are stored with
   the jobs, so later execution cannot drift after a renderer update.
4. Immediate jobs enter the publisher executor. Scheduled jobs remain durable
   until their timezone-aware due time.
5. Each platform reaches its own terminal state. A failure on one platform does
   not overwrite the other platform's result.
6. Public URLs are persisted in `platform_jobs.result_url` and rendered in the
   grouped frontend history.

## Job states

```text
ready/scheduled -> running -> succeeded
                         |-> pending_remote -> running (poll)
                         |-> waiting_user -> ready (explicit resume)
                         |-> failed -> ready (explicit retry)
                         `-> unknown (manual inspection only)

scheduled -> missed -> ready (explicit retry)
```

Transient failures use three bounded attempts with backoff. A scheduler restart
accepts a 30-minute missed-run grace period. `unknown` deliberately has no retry
transition because an ambiguous platform response could otherwise create a
duplicate publication.

## WeChat

The preferred path is the official API:

1. obtain and centrally cache a `stable_token`;
2. upload the permanent cover material;
3. upload an inline image to WeChat CDN when required;
4. create a draft;
5. submit an asynchronous free-publish job;
6. poll the stored `publish_id` until WeChat returns a public article URL.

An accepted `publish_id` is not treated as success. Review rejection is terminal
until the user edits and creates a new submission. The browser fallback is
disabled by default and is used only when the user enables it and the official
API returns a confirmed permission/configuration error. CAPTCHA, QR code,
administrator confirmation, and risk controls always pause for human action.

## CSDN

CSDN uses a dedicated persistent browser profile. The adapter opens the creator
editor, uploads the image, fills the rendered Markdown, saves a draft, and
returns the editor URL. A CSDN job is complete when a draft link is saved; final
review and public publication remain a user action. If login is required the job
enters `waiting_user`, and the frontend exposes an explicit **已登录，继续**
action after the user signs in.

## Local security

- Uvicorn binds only to `127.0.0.1`.
- Every POST/PUT request requires a random in-memory token obtained through a
  same-origin GET. Cross-origin form posts cannot forge its custom header.
- AppSecret values are stored through the operating-system keyring and are
  never returned by the API or stored in SQLite.
- CSDN and WeChat browser sessions use separate persistent profile directories.
- Private Cookie APIs, CAPTCHA bypasses, and silent risk-control workarounds are
  intentionally excluded.

## Verification

The repository runs Ruff and Pytest on Linux, macOS, and Windows, plus Vitest and
the production Vite build on Linux. Tests cover domain validation, persistence,
rendering, job transitions, duplicate protection, retries, official WeChat
responses, adapter routing, API security, frontend flows, scheduled submission,
manual recovery, and same-thread browser shutdown. Real-account acceptance must
still be run against the target account because platform permissions, login
challenges, and editor selectors are external state.
