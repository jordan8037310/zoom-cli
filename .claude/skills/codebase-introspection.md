# Codebase Introspection Skill

## When to Use

Use this skill when you need to understand the overall structure, maturity, or integration landscape of a codebase. Useful for:

- Onboarding to a project
- Planning large refactors
- Auditing security or reliability posture
- Identifying where to add tests
- Understanding external service dependencies
- Generating a prioritized backlog of tech debt
- Tracking remediation tasks from findings

## How to Run

```bash
python scripts/introspection.py
```

### Options

```bash
python scripts/introspection.py --root .              # specify repo root
python scripts/introspection.py --config .introspect.yml  # custom config
python scripts/introspection.py --output docs/introspection  # custom output dir
python scripts/introspection.py --budget-files 1000   # limit scan scope
```

### Configuration

Edit `.introspect.yml` in the repo root to customize:

- `exclude`: additional glob patterns to skip
- `sensitive_zones`: paths where file content is not stored (only metadata)
- `entrypoints`: extra files to prioritize in analysis
- `budget_files` / `budget_bytes`: scan limits

## Exclusion Rules (Layered)

The scanner enforces a layered exclusion system to prevent scanning sensitive or irrelevant files. Patterns are loaded from three sources and merged:

1. **Built-in defaults** — vendor, node_modules, dist, binary formats, `.env`
2. **`.gitignore`** — parsed automatically on each run, including negation patterns (e.g. `!.env*.dist` re-includes `.env.dist`). This ensures the scanner never processes files that are not tracked by git.
3. **`.claude/settings.json` deny list** — `Read()` denial rules are extracted and converted to exclude globs. This ensures the scanner respects the same access boundaries as Claude Code itself.

The three sources are merged and deduplicated. Negation patterns from `.gitignore` act as an allowlist that overrides exclusions.

## Output Structure

```
docs/introspection/
  ARCHITECTURE.md          # C4-style: context, containers, components, data layer
  MATURITY.md              # Testing, lint, CI/CD, observability, security assessment
  BACKLOG.yaml             # Prioritized reliability/security tasks with evidence
  TASKS.md                 # Itemized findings with actionable resolution checklists
  SKILLS.md                # Recommended Claude Code skills for this stack
  introspection_plan.yaml  # The generated scan plan
  INTEGRATIONS/
    REST_SERVICES.md       # All detected REST API integrations by domain
  MIRROR/
    app/
      Http/Controllers/README.md
      Models/README.md
      ...
    config/README.md
    database/migrations/README.md
    tests/README.md
    ...
```

## Key Output Files

### ARCHITECTURE.md

C4-style architecture overview:

- **Context (L1):** System purpose, tech stack, external systems
- **Containers (L2):** Entrypoints grouped by kind (routes, controllers, jobs, etc.)
- **Components (L3):** Per-module breakdown with file counts, key files, dependencies
- **Data Layer:** Eloquent models and migrations

### MATURITY.md

Assessment of operational maturity:

- Test coverage (files, frameworks, distribution)
- Lint/formatting tools and enforcement
- CI/CD configuration
- Observability (logging, error tracking, metrics, tracing)
- Security posture (auth patterns, secret detection)

### BACKLOG.yaml

Prioritized list of reliability and security tasks. Each item has:

- `severity`: critical / high / medium / low
- `effort`: small / medium / large
- `evidence`: file paths and line numbers supporting the finding
- `acceptance_criteria`: what "done" looks like

### TASKS.md

Human-curated remediation tracker generated from BACKLOG.yaml findings. Each task has:

- Status, severity, effort
- Evidence pointers
- Checklist of resolution steps
- Notes on prioritization and approach

This file is intended to be updated manually as tasks are completed. Unlike BACKLOG.yaml (regenerated on each run), TASKS.md is a persistent tracking document.

### SKILLS.md

Stack-specific skill recommendations:

- Laravel skill pack (if detected): routing, services, Eloquent, queues, testing, static analysis
- REST integration skill (if external APIs found): retries, timeouts, circuit breakers
- Async/queue skill (if jobs/events found)
- Data layer skill (if models/migrations found)

### INTEGRATIONS/REST_SERVICES.md

Comprehensive REST/API surface area analysis with three discovery methods:

- **Dependencies** — packages in `composer.json` / `package.json` that provide or consume REST (e.g., `drupal/restui`, `laravel/sanctum`, `express`, `@fastify/swagger`)
- **Route Definitions** — source code patterns that expose REST endpoints (e.g., `Route::get()`, `register_rest_route()`, Drupal `.routing.yml`, Next.js route handlers)
- **HTTP Client Calls** — outbound API calls to external services (Guzzle, Laravel HTTP, fetch/axios, cURL)

### MIRROR/**

Per-module documentation mirroring the repo structure. Each module gets:

- Purpose, file count, line count
- Key files and dependencies
- Integration points (REST APIs used)
- TODOs extracted from comments
- Risk assessment

## Constraints

- **Offline:** No network calls. All analysis is static, local file scanning.
- **Budget:** Default 3,000 files or 200MB, whichever is hit first.
- **Secrets:** Detected patterns are noted but values are never stored. Sensitive zone files have content suppressed. Files denied in `.claude/settings.json` and `.gitignore` are never read.
- **Evidence-based:** Every claim cites file paths. No hallucinated findings.
- **Env files:** `.env` is never scanned. `.env.dist` is recognized as the env example template.

## Refreshing

Re-run `python scripts/introspection.py` any time the codebase changes significantly. The auto-generated output files (ARCHITECTURE.md, MATURITY.md, BACKLOG.yaml, SKILLS.md, MIRROR/**, REST_SERVICES.md) are overwritten on each run. TASKS.md is a manual tracking document and should not be auto-regenerated.

## False Positive Notes

The secret scanner matches patterns heuristically. Known non-issues:

- **Dockerfile** — ARG/ENV declarations reference variables, not hardcoded secrets
- **`.gitlab-ci.yml`** — CI variables use `$VAR` references, not literals
- **`.env`** — excluded from scanning entirely
- Only flag files where the regex matches a quoted literal string value
