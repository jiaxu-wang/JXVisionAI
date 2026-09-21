# Security policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems
(default passwords, RCE, auth bypass, path traversal, leaked credentials).

Email the maintainer listed on the GitHub repository profile, or open a
**private** GitHub Security Advisory on
https://github.com/jiaxu-wang/JXVisionAI/security/advisories/new

Include:

- Affected version / commit
- Reproduction steps (no production secrets)
- Impact

We will acknowledge the report and work on a fix before any public
disclosure.

## Deployment

- Copy `.env.example` to `.env` and set unique secrets before
  `docker compose up`. Values shipped in docs or old compose files are
  **public** and must be rotated on any network-facing host.
- Do not commit `config/config.ini`, `.env`, face photos, or alert images.
- Keep `OPEN_API_KEY` empty unless you need the machine API; treat it like
  a password.
- `/api/restart` is disabled unless `VISIONAI_ALLOW_PROCESS_RESTART=1`.
