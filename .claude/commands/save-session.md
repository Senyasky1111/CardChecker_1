---
description: Write a session-log markdown to vault/_sessions/ summarizing what was done this session, what's pending, what's the handoff. Use before ending a session or moving to new context. Follows the _template.md structure.
---

# /save-session — Session archival

You are about to write a session summary to `vault/_sessions/YYYY-MM-DD-<slug>.md`. This is the bridge between this ephemeral session and future Claude sessions. Get it right — future you depends on it.

## Steps

### 1. Pick a slug

Short, hyphenated, descriptive of the session's main theme. Examples:
- `vault-overhaul-multi-agent-subscription-mgmt`
- `stripe-webhook-implementation`
- `defect-detection-v3-training-run`

If the session covered multiple disjoint themes, pick the most consequential one for the filename. Mention others in tags.

### 2. Read the template

Open `vault/_sessions/_template.md` and use it as the structural skeleton. Don't skip sections — even brief ones add value.

### 3. Fill in honestly

- **TL;DR**: 1-2 sentences. Future Claude reads this first.
- **Goal**: what user actually wanted, not what we ended up doing
- **Decisions made**: table form. Every decision the user approved → row. Decisions that emerged from review → row. Link to ADRs.
- **Artefacts**: every file modified or created. Git commit SHAs. Configuration changes.
- **Bugs found by reviewers**: when /feature-flow was used, list findings + status
- **Mistakes / detours**: the lessons. What went wrong, how we corrected. Future sessions avoid these.
- **Pending / handoff**: checkbox list. What the next session must pick up. Be specific.
- **Context to carry forward**: 3-7 bullets. The minimum facts a fresh session needs to continue effectively.
- **Open questions**: things needing user input or further investigation.
- **Raw transcript**: pointer to `~/.claude/projects/d--CardChecker/<uuid>.jsonl` (find latest .jsonl by mtime).

### 4. Update the sessions MOC

Add a line to `vault/_sessions/_MOC.md` under "Manual list":
```markdown
- [[YYYY-MM-DD-slug]] — one-line description
```

If this session is foundational (changes how future sessions should approach the project), mark it explicitly: "**Foundational session — read first when picking up X**".

### 5. Cross-link from main log

Append a short entry to `vault/log.md` referencing the new session summary. Keep it terse — the session file has the details.

### 6. Memory check

Did this session reveal new user preferences, project facts, references, or feedback worth persisting in auto-memory (`~/.claude/projects/d--CardChecker/memory/`)? If yes, write or update the relevant memory file. Don't duplicate — if the fact is in the session summary AND the user wants it remembered across sessions, it goes in memory.

## What NOT to save

- Don't paste raw transcript content (it's already in the .jsonl).
- Don't write essay-length narrative — structure beats prose for retrieval.
- Don't save planning artefacts that turned out wrong — note them in "Mistakes / detours" instead.
- Don't duplicate decisions that became ADRs — point to the ADR.

## Output

Confirm to user:
- File written at `vault/_sessions/YYYY-MM-DD-slug.md`
- MOC updated
- Log entry added
- Memory updated (which files, if any)
- One-line summary of what the next session should know

## When to use

- User signals "moving to new session" / "сохрани контекст" / "закрываем сессию"
- After /compact or before /compact (preserve summary before context trim)
- Periodic checkpoint during long session (>4h) — save partial then continue
- Before risky destructive actions (in case session ends abruptly)