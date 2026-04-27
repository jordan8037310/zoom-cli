# Tasks

Tracking-only document for security and tooling follow-ups surfaced during the FACET CC onboarding pass. Active feature work lives in GitHub Issues on `jordan8037310/zoom-cli`.

## Backlog (security & tooling)

- [ ] **Audit existing GitHub Issues against `SECURITY.md` threat model** — confirm the deferred items (#12 PKCE, #16 rate-limit pagination, #17 webhook HMAC, #24 schema versioning) match what's documented.
- [ ] **Add a `security` label** to GitHub Issues #5 (closed), #6 (closed), #12, #17 for filterability.
- [ ] **Evaluate adding `bandit` or `semgrep`** to the lint stage in CI for static security analysis.
- [ ] **Evaluate `pip-audit` / `safety`** as a CI step for dependency vulnerability scanning.
- [ ] **Document the upstream-sync security posture** — when porting changes from `tmonfre/zoom-cli`, what threat-model items must be re-verified?
- [ ] **Decide on a SECURITY.md disclosure channel** — currently routes through public GitHub Issues; consider a private email or `SECURITY.md`-style `report-to` address for sensitive disclosures.
- [ ] **Schema versioning of `meetings.json`** (partial of #24) — needed before any auto-migration that could destroy un-readable legacy fields.
- [ ] **Migration story for legacy plaintext passwords** — `_edit` migrates on touch, but stale bookmarks could sit untouched indefinitely. Consider a one-shot `zoom migrate` command.

## Out of scope for this onboarding

These items from the FACET CC onboarding checklist do not apply or are deferred:

- **GitLab Ultimate features** — repo is hosted on GitHub, not GitLab.
- **Lando / Docker container review** — no containers in use.
- **Project-scoped MCP setup (`.mcp.json`)** — no project-scoped MCP servers configured; project does not use Atlassian or GitLab MCP integrations.
- **Strategist / delivery-manager skills** — single-developer fork, no Jira project; not relevant.

## Completed during this onboarding pass

- [x] `.gitignore` extended with FACET baseline + Python entries; `.claude/settings.local.json` and `.claude/CLAUDE.local.md` are now correctly ignored while shared `.claude/settings.json` and `.claude/skills/` are committed.
- [x] `.claude/settings.json` created with three-tier permissions (deny / allow / default-ask).
- [x] Credential-path scan run; no committed credential files found on `develop`.
- [x] `.claude/skills/env-safe.md`, `mcp-security.md`, `codebase-introspection.md` installed from facet-skills.
- [x] `SECURITY.md` written with project-specific threat model.
- [x] `LOCAL-SECURITY.md` written with MCP/skill/plugin risk register.
- [x] `CLAUDE.md` extended with pointers to security docs and the no-Zoom-API-keys rule for AI development.
