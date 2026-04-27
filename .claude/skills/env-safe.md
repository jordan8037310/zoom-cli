# Env-Safe Skill

## When to Use

Use this skill on any project where `.env` files contain secrets (API keys, database credentials, tokens). It defines how Claude Code should interact with environment configuration files without ever exposing secret values. Install by copying this file to the target project's `.claude/skills/env-safe.md`.

## Prerequisite: Deny Rules

This skill assumes the project's `.claude/settings.json` includes deny rules that block direct reads of `.env` files. If these deny rules are not yet in place, add them before relying on this skill:

```json
{
  "permissions": {
    "deny": [
      "Read(./.env)",
      "Read(./.env.*)",
      "Bash(cat */.env*)",
      "Bash(head */.env*)",
      "Bash(tail */.env*)",
      "Bash(less */.env*)",
      "Bash(more */.env*)"
    ]
  }
}
```

The deny rules are the hard security boundary. This skill provides the behavioral guidance that works alongside those rules.

## File Classification

### UNSAFE to Read (contain real secrets)

- `.env`
- `.env.local`
- `.env.development`
- `.env.staging`
- `.env.production`
- `.env.test` (if it contains real credentials)
- Any `.env.*` file that is gitignored

### SAFE to Read (contain placeholders only)

- `.env.example`
- `.env.dist`
- `.env.sample`
- `.env.template`
- `.env.lando.dist`
- `.env.ci` (if committed to git and documented as placeholder-only)
- Any env template file that is tracked in git and contains no real secrets

**Rule of thumb:** If the file is in `.gitignore`, treat it as unsafe. If it is committed to the repository and documented as a template, it is safe.

## Safe Inspection Commands

When you need to understand a project's environment configuration, use these commands. They extract structural information without exposing values.

### List All Variable Names (Without Values)

```bash
grep -oP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*(?=\s*=)' .env | sed 's/^export\s*//'
```

This handles:

- Standard format: `DATABASE_URL=...`
- Export prefix: `export DATABASE_URL=...`
- Spaces around equals: `DATABASE_URL = ...`

### Count Total Defined Variables

```bash
grep -cP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=' .env
```

### Count Empty vs Populated Variables

```bash
# Empty (no value after =)
grep -cP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=\s*$' .env

# Populated (has a value after =)
grep -cP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=\s*.+' .env
```

### Check If a Specific Variable Exists

```bash
grep -qP '^(export\s+)?MY_VARIABLE\s*=' .env && echo "defined" || echo "missing"
```

### Check If a Specific Variable Has a Value

```bash
grep -qP '^(export\s+)?MY_VARIABLE\s*=\s*.+' .env && echo "populated" || echo "empty or missing"
```

### Validate .env Syntax

```bash
# Find malformed lines (not blank, not comments, not valid assignments)
grep -nP '^(?!\s*#)(?!\s*$)(?!(export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=)' .env
```

If this produces output, those line numbers contain syntax errors. Report the line numbers, never the line content.

### Compare .env Against Template

```bash
# Variables in .env.example but missing from .env
comm -23 \
  <(grep -oP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*(?=\s*=)' .env.example | sed 's/^export\s*//' | sort) \
  <(grep -oP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*(?=\s*=)' .env | sed 's/^export\s*//' | sort)
```

```bash
# Variables in .env but not in .env.example (potentially stale or custom)
comm -13 \
  <(grep -oP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*(?=\s*=)' .env.example | sed 's/^export\s*//' | sort) \
  <(grep -oP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*(?=\s*=)' .env | sed 's/^export\s*//' | sort)
```

Replace `.env.example` with `.env.dist`, `.env.lando.dist`, or whatever template the project uses.

### Detect Duplicate Keys

```bash
grep -oP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*(?=\s*=)' .env | sed 's/^export\s*//' | sort | uniq -d
```

### Count Lines by Type

```bash
# Total lines
wc -l < .env

# Comment lines
grep -cP '^\s*#' .env

# Blank lines
grep -cP '^\s*$' .env

# Assignment lines
grep -cP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*\s*=' .env
```

## Anti-Patterns (Never Do These)

### Never Read .env File Contents

```bash
# FORBIDDEN
cat .env
head .env
tail .env
less .env
more .env
source .env
```

```
# FORBIDDEN — Claude Code Read tool
Read(.env)
Read(.env.local)
Read(.env.production)
```

### Never Use grep Patterns That Match Values

```bash
# FORBIDDEN — the value appears in output
grep "DATABASE" .env
grep -i "password" .env
grep "=" .env
```

The safe patterns above use `-oP` with a lookahead (`(?=\s*=)`) or `-c` (count only) to ensure only key names or counts appear in output, never values.

### Never Echo Environment Variable Values

```bash
# FORBIDDEN
echo $SECRET_KEY
echo $DATABASE_URL
printenv SECRET_KEY
env | grep SECRET
```

### Never Use sed/awk to Process .env Content

```bash
# FORBIDDEN — may output values
sed -n '5p' .env
awk -F= '{print $2}' .env
cut -d= -f2 .env
```

### Never Pipe .env Through Any Command That Outputs Content

```bash
# FORBIDDEN
cat .env | wc -l      # Use: wc -l < .env (safe — only outputs count)
cat .env | grep KEY    # Exposes value
sort .env              # Outputs entire file sorted
diff .env .env.example # Outputs values from both files
```

## Setting Environment Variables

When a user needs to add or update a value in `.env`:

1. **Ask the user** to provide the value or set it themselves.
2. **Never generate** plausible-looking secret values.
3. If writing to `.env`, use append or targeted replacement without reading the file first:

```bash
# Safe: append a new variable (user provides the value)
echo 'NEW_VAR=user-provided-value' >> .env
```

```bash
# Safe: replace a specific variable's value (user provides the new value)
sed -i '' 's|^OLD_VAR=.*|OLD_VAR=new-value|' .env
```

These write operations are safe because they do not read or display the file contents.

## Docker and Lando

The same rules apply to `.env` files used by Docker Compose and Lando:

- `docker-compose.yml` may reference `.env` via `env_file:` -- the `.env` is still unsafe to read
- `.env.lando.dist` is safe (template with placeholders, committed to git)
- After `lando start`, `.env` may be auto-generated from `.env.lando.dist` -- the generated `.env` is unsafe

Use the same safe inspection commands listed above for any `.env` file regardless of which tool consumes it.

## Multi-Environment Projects

Some projects use multiple environment files (`.env.development`, `.env.staging`, `.env.production`). Apply the same rules to all of them:

```bash
# List variable names across all env files
for f in .env .env.development .env.staging .env.production; do
  [ -f "$f" ] && echo "=== $f ===" && grep -oP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*(?=\s*=)' "$f" | sed 's/^export\s*//'
done
```

```bash
# Compare any two env files by key names only
comm -3 \
  <(grep -oP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*(?=\s*=)' .env.staging | sed 's/^export\s*//' | sort) \
  <(grep -oP '^(export\s+)?[A-Za-z_][A-Za-z0-9_]*(?=\s*=)' .env.production | sed 's/^export\s*//' | sort)
```

## Error Handling

If a safe inspection command encounters malformed lines, report only:

- The line number
- The type of error (e.g., "line 12 is not a valid assignment, comment, or blank line")
- Never include the line content itself, as malformed lines may contain partial secrets

## Checklist for New Projects

When setting up env-safe on a new project:

- [ ] Verify `.env` and `.env.*` are in `.gitignore`
- [ ] Verify `settings.json` deny rules block `Read(./.env)` and `Read(./.env.*)`
- [ ] Identify which `.env.*` template files exist and are safe to read
- [ ] Run the template comparison command to identify any missing variables
- [ ] Validate `.env` syntax and report any malformed line numbers
- [ ] Document the project's env template file in `CLAUDE.md` or `LOCAL.md`
