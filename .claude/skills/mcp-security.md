# MCP Security Skill

## When to Use

Use this skill when setting up MCP servers for any FACET project. Ensures credentials are isolated from the LLM, scope is minimized, and known attack vectors are mitigated.

## Credential Isolation

### What the LLM CAN See

- Tool names and descriptions
- Tool input schemas (parameter names/types)
- Tool output (results of calling tools)
- Server instructions (if defined)

### What the LLM CANNOT See

- Environment variable values passed to stdio server processes
- OAuth tokens stored in the system keychain
- HTTP headers configured on transport connections
- The `env` block values in `.mcp.json`

### Primary Leak Vector

If an MCP server's tool **returns** credential material in its output (connection strings, IAM keys), those values enter the LLM context. Control this at the MCP server implementation level.

## Configuration Patterns

### Use `${VAR}` Expansion (Never Hardcode)

```json
{
  "mcpServers": {
    "postgres": {
      "command": "npx",
      "args": ["-y", "@bytebase/dbhub", "--dsn", "${DATABASE_URL}"],
      "env": {
        "DATABASE_URL": "${DATABASE_URL}"
      }
    }
  }
}
```

### Known Bug: `claude mcp add` Resolves Variables

`claude mcp add` can expand `${VAR}` to plaintext and write it back to `.mcp.json` (GitHub Issue #18692). Use `claude mcp add-json` with explicit `${VAR}` syntax instead. Always review `.mcp.json` changes before committing.

### Credential Sources (Preferred Order)

1. 1Password CLI: `op run --env-file=.env.tpl -- claude`
2. AWS Secrets Manager via wrapper script
3. macOS Keychain via `security find-generic-password`
4. `.env` file loaded by direnv (never committed)

### Wrapper Script Pattern

For stdio servers needing secrets:

```bash
#!/bin/bash
export DATABASE_URL=$(op read "op://vault/db-credential/url")
exec npx -y @bytebase/dbhub --dsn "$DATABASE_URL"
```

Reference in `.mcp.json`:

```json
{
  "mcpServers": {
    "postgres": {
      "command": "./scripts/start-db-mcp.sh"
    }
  }
}
```

## Scope Limitation per Server

| Server | Auth Pattern | Scope Limitation |
|--------|-------------|-----------------|
| Context7 | None required | N/A — read-only docs |
| Atlassian/Jira | OAuth 2.1 | Scoped to user's existing project permissions; use IP allowlists |
| Notion | OAuth | Create dedicated integration; restrict to specific workspace pages |
| Google Drive | OAuth 2.0 | Use `drive.file` scope (not `drive`); restrict service account to specific folders |
| Mermaid Chart | OAuth or API key | Read-only scope |
| AWS | IAM credentials | IAM role with minimum permissions; use STS temp credentials |
| Database tools | Connection string | Read-only DB user; restrict to specific schemas/tables |

## Team Standardization

### Managed MCP (`managed-mcp.json`)

Deploy to `/Library/Application Support/ClaudeCode/managed-mcp.json` (macOS) to enforce approved servers:

```json
{
  "allowedMcpServers": [
    { "serverName": "notion" },
    { "serverName": "jira" },
    { "serverUrl": "https://mcp.notion.com/*" },
    { "serverUrl": "https://mcp.atlassian.com/*" }
  ]
}
```

### Docker MCP Gateway

For production/team deployments, Docker MCP Gateway provides:

- Container isolation per server (credentials scoped to specific containers)
- Secret management through Docker Desktop (not env vars)
- Call logging for all tool invocations
- Network controls restricting container egress

## Known Vulnerabilities

| CVE | Impact | Mitigation |
|-----|--------|-----------|
| CVE-2025-6514 (mcp-remote) | Command injection via crafted `authorization_endpoint` | Update mcp-remote; validate OAuth URLs |
| CVE-2025-68143/44/45 (Anthropic Git MCP) | Path traversal, unrestricted git_init, argument injection | Update to patched version |
| CVE-2025-6515 (Session Hijacking) | Predictable session IDs enable payload injection | Use MCP servers with secure session ID generation |

## Threat Model

| Threat | Likelihood | Impact | Mitigation |
|--------|-----------|--------|-----------|
| Credentials in `.mcp.json` committed to git | High | Critical | `${VAR}` expansion; `.gitignore`; PR review |
| Prompt injection via untrusted content | High | High | Caution with GitHub/Slack/email MCPs; user confirmation |
| Tool poisoning from malicious MCP server | Medium | Critical | Evaluate before install; pin versions; use allowlists |
| Cross-server credential theft | Medium | Critical | Container isolation; env var scoping per server |
| Rug pull (post-approval tool change) | Medium | High | Pin versions; checksums; monitor `list_changed` events |
| Supply chain typosquatting | Low | Critical | Use official servers; verify package names |

## Installation Checklist

When adding any MCP server to a project:

- [ ] Evaluate source code in a separate clone
- [ ] Pin to a specific version (not `latest`)
- [ ] Use `${VAR}` expansion for all credentials in `.mcp.json`
- [ ] Verify `.mcp.json` is in `.gitignore` OR contains no resolved credentials
- [ ] Apply principle of least privilege (read-only users, minimal scopes)
- [ ] Test that tool output does not leak credentials
- [ ] Document risk factors in `LOCAL-SECURITY.md`
- [ ] Add to `managed-mcp.json` allowlist if using team standardization
