# Contributing

## Quality gate

Every module must pass its focused tests and the complete regression suite before
it is committed or pushed.

```bash
.venv/bin/ruff check src tests
.venv/bin/pytest --cov=social_publisher --cov-report=term-missing
cd frontend
npm test
npm run build
```

Platform browser automation must keep selectors inside the relevant adapter.
Tests must use injected fakes and must never publish real content in CI.

## Commit scope

- Keep platform adapters independent.
- Do not store secrets, cookies, local databases, browser profiles, or generated
  content in Git.
- A platform failure must not roll back a sibling platform result.
- Never automatically retry an ambiguous browser submission.

