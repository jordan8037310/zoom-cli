# Local Security — MCP & Tool Risk Assessment

Risk register for local AI/dev tooling configured against this project. Update this document when an MCP server, skill, or plugin is installed, changed, or removed.

## Installed MCP Servers

This project does **not** configure any project-scoped MCP servers (no `.mcp.json` present). Any MCP servers used during development are inherited from the developer's global Claude Code settings.

If a future MCP is added at the project scope, document it here following the FACET MCP Security Skill checklist (`.claude/skills/mcp-security.md`):

| Server | Source | Risk Level | Credential Source | Notes |
|--------|--------|------------|-------------------|-------|
| _none configured_ | — | — | — | — |

## Installed Skills

Skills committed at `.claude/skills/` are reviewed and shared with all collaborators. Skills installed only in personal config (e.g. `~/.claude/skills/`) are not covered here.

| Skill | Source | Risk Level | Notes |
|-------|--------|------------|-------|
| `env-safe.md` | facet-skills `skills/developer/` | Low | Behavioral guidance only — no executable code. Provides safe `.env` inspection patterns that never expose secret values. |
| `mcp-security.md` | facet-skills `skills/developer/` | Low | Reference document — no executable code. Threat model + checklist for any future MCP install. |
| `codebase-introspection.md` | facet-skills `skills/developer/` | Low | Static analysis guidance — no executable code. |

## Installed Plugins

Plugins are installed at the user level (`~/.claude/`) and shared across projects. They are not pinned by this repo. Document expected plugins so collaborators know what AI tooling has been validated against this project:

| Plugin | Source | Risk Level | Notes |
|--------|--------|------------|-------|
| `superpowers` | github.com/pcvelz/superpowers | Low–Medium | Methodology skills (TDD, debugging, planning, code review). No credential access. Used for `superpowers:requesting-code-review` per CLAUDE.md. |
| `context7` | github.com/upstash/context7 | Low | Read-only documentation lookup. No credentials. |
| `codex` | Anthropic Codex plugin | Medium | Delegates to OpenAI Codex CLI. Codex runs in a sandboxed runtime against this repo — verify `codex:setup` reports green before extended use. Codex output is returned verbatim; the prompt context flows out to OpenAI. |
| `fullstack-dev-skills` | github.com/Jeffallan/claude-skills | Low–Medium | Domain skills, including `fullstack-dev-skills:code-reviewer` per CLAUDE.md. |

## Risk Factors Specific to zoom-cli

- **Real Zoom credentials in OS keyring** — the developer's Keychain may contain entries under `zoom-cli` and `zoom-cli-auth`. AI assistants are denied keyring access for these services (see `.claude/settings.json` deny rules) and denied execution of any subcommand that would prompt for or use these credentials (`zoom auth s2s set/test`, `zoom users me`, etc.).
- **Legacy plaintext meeting passwords** — the user's `~/.zoom-cli/meetings.json` may still contain plaintext passwords for bookmarks created before PR #28 and not yet touched by `zoom edit`. Read access to `~/.zoom-cli/**` is denied.
- **No .env file** — the project does not use environment-file credentials. `.env*` deny rules are baseline defense-in-depth only.

## Review Schedule

Update this document when:

- A new MCP server is installed at the project scope (`.mcp.json`)
- A new skill is committed to `.claude/skills/`
- A new plugin is added to the team's recommended set
- A dependency that handles credentials (`keyring`, `httpx`, `click`, `questionary`) is upgraded
- The threat model in `SECURITY.md` changes
