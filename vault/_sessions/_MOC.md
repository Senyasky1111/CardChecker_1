---
type: moc
status: active
created: 2026-05-24
updated: 2026-05-24
area: [meta, sessions]
tags: [moc, sessions, archive]
---

# Sessions MOC

> Per-session summaries. The structured log of what we did, why, what's pending.
> **Raw transcripts** live at `~/.claude/projects/d--CardChecker/<uuid>.jsonl` (Claude Code's own storage). This vault folder = curated overlay for retrieval.

## Why this exists

LLM sessions are ephemeral by default. Without explicit consolidation, every new session restarts from scratch. This folder closes the gap: each notable session produces a markdown summary, retrievable by future Claude instances via grep/wikilink/MCP.

Based on patterns from [MindStudio "Self-Evolving Claude Code Memory"](https://www.mindstudio.ai/blog/self-evolving-claude-code-memory-obsidian-hooks), [JP Narowski "Obsidian as AI Second Brain"](https://jpuncompiled.com/articles/tactical-guide-obsidian-second-brain), and [Karpathy's LLM Wiki pattern](https://github.com/ar9av/obsidian-wiki).

## Folder structure

```
_sessions/
├── _MOC.md              ← you are here
├── _template.md         ← copy for new sessions
├── YYYY-MM-DD-slug.md   ← HOT: recent sessions, last 30 days
└── archive/             ← COLD: >90 days, summary-only retained
```

## HOT / WARM / COLD tiering

- **HOT** (current session, last 7 days): full summary + decisions + artefacts. Future Claude reads in full.
- **WARM** (8-90 days): same summary structure stays in place. Pointers to ADRs/code-files preferred over inline content.
- **COLD** (>90 days): move to `archive/`. If conclusions/decisions still matter, they should have been promoted to an ADR or area MOC by now. The session file itself becomes a forensic record.

## Session file structure

See [[_template]]. Required sections: `Goal`, `Decisions`, `Artefacts`, `Pending`, `Raw transcript`. Everything else optional.

## Session retrieval (for future Claude sessions)

When you start a new session and want to know "what did we last do":
1. Read `_sessions/_MOC.md` (this file) — see catalog
2. Read latest 1-3 sessions in order
3. If specific topic — grep `_sessions/**` for keyword
4. Raw transcript at `~/.claude/projects/d--CardChecker/<uuid>.jsonl` if needed (large files, only when summary insufficient)

## Convention for ending a session

User signals "we're moving to new session" → write summary in `_sessions/YYYY-MM-DD-slug.md` before closing. The `/save-session` skill (TBD) automates this.

Recurring failure mode: ending without summary → next session re-discovers everything → wasted tokens + wasted time.

## Catalog

```dataview
TABLE date, file.tags AS tags FROM "_sessions"
WHERE type = "session-log"
SORT date DESC
```

### Manual list (newest first)

- [[2026-05-24-vault-overhaul-multi-agent-subscription-mgmt]] — vault reality check + multi-agent infra + first /feature-flow test (webapp subscription management) + MCP setup. **Foundational session — read first when picking up CardChecker work.**

## Related

- Memory (auto, persists in Claude Code): `~/.claude/projects/d--CardChecker/memory/`
- Vault log (append-only journal, decisions only): [[../log]]
- Context packs (curated bundles for AI sessions): [[../_context-packs/]]
- ADRs (decisions documented formally): [[../30-Resources/adr/]]
