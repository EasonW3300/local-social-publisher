# Security policy

Please report security issues privately through GitHub's security advisory
feature rather than opening a public issue.

The application binds to loopback only. App secrets belong in the operating
system credential store, and cookies belong in isolated browser profiles. Logs,
SQLite files, screenshots, fixtures, and bug reports must not contain tokens,
cookies, QR codes, AppSecrets, or unpublished user content.

