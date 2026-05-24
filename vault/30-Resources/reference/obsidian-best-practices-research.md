---
type: reference
status: active
created: 2026-05-21
updated: 2026-05-21
area: [meta]
tags: [obsidian, knowledge-base, ai-context, research]
source: ai-research-2026-05-21
---

# Obsidian as Code + Product + AI Memory Vault — Pragmatic Guide for CardChecker

> Research compiled 2026-05-21 from practitioner blogs, Karpathy's LLM Wiki gist, Obsidian community guides, and AI-coding-assistant writeups (2024-2026).
> Tailored for: solo dev, CV/ML + mobile + business product, vault colocated with code at `D:\CardChecker\`.

## TL;DR — what I'd actually do

**Hybrid framework**: PARA-style folders (`10-Projects/`, `20-Areas/`, `30-Resources/`, `40-Archive/`) + LYT Maps of Content (one `_MOC.md` per area) + Karpathy LLM Wiki pattern (vault-root `index.md`, `log.md`, plus tight `CLAUDE.md`).

**Why**: PARA gives folders Claude can directory-walk. LYT MOCs give the LLM narrative context about how notes relate. Karpathy's `index.md`/`log.md` give the LLM a catalog + recent history without scanning 300 files. CLAUDE.md ≤120 lines points to all of it.

---

## 1. Framework comparison

| Framework | Strengths | Weaknesses for solo dev + AI |
|---|---|---|
| **PARA** (Forte) | Action-oriented, fast setup, separates active/reference | Pure PARA has no MOC concept; flattens code+product into same bin |
| **Zettelkasten** | Atomic notes + dense links; compounding insight | Heavy ceremony; terrible for "what does endpoint X do today?" |
| **LYT / MOCs** (Nick Milo) | MOCs act as topic index AI uses as a map | Needs discipline to keep MOCs alive |
| **Johnny Decimal** | Stable numeric IDs paste-able into code comments | Rigid; bad when scope shifts fast |
| **Karpathy LLM Wiki** | Designed for LLM-as-reader (`index.md`, `log.md`, schema doc) | New pattern, fewer templates around |

**The convergent consensus in 2024-2026**: hybrid wins. PARA shell + LYT MOCs inside it + Karpathy conventions at vault root.

---

## 2. Engineering / codebase docs

### ADRs (Architectural Decision Records) — use MADR-lite

Date-as-ID works better than numeric incrementing in Obsidian (per Matteo Paoli). Bare-minimum sections: **Title · Status · Context · Decision · Consequences**.

File: `30-Resources/adr/2026-05-21-clip-fallback-threshold.md`

```yaml
---
type: adr
status: accepted   # proposed | accepted | rejected | deprecated | superseded
date: 2026-05-21
supersedes:
superseded-by:
area: [recognition, ml]
tags: [adr, clip, ocr]
---
```

### API endpoints — one note per endpoint

`20-Areas/backend/api/identify-v2.md` with frontmatter `type: api-endpoint`, sections: Purpose · Request · Response · Pipeline · Failure modes · Recent changes. Link source via relative path `[card_matcher.py](../../../src/card_matcher.py)` — Claude resolves these natively.

### Modules

One note per significant module in `src/`. Sections: **What it does · Public surface · Internal flow · Dependencies · Open issues · Recent decisions (linked ADRs)**.

### Runbooks

`20-Areas/ops/runbooks/{db-rebuild,redeploy-hetzner,re-scrape-tag}.md`. Each: **Symptom · Diagnosis · Fix · Verify · Past incidents**.

### Linking code ↔ Obsidian

- From Obsidian → code: relative paths in markdown links. Claude resolves natively.
- From code → Obsidian: comments like `# Docs: 20-Areas/backend/api/identify-v2.md`. Skip `obsidian://` URLs — break in CI.

### Mermaid vs Excalidraw

- **Mermaid** for flows/sequences/state — inside markdown, Claude reads, diffs in git. Use 90% of the time.
- **Excalidraw** for hand-drawn architecture sketches. Files are markdown+JSON, parseable.

### What does NOT belong in Obsidian

- API contract truth — stays in OpenAPI/FastAPI
- Function-level comments — stay in code
- Test fixtures, model weights — already in `data/`, `models/`
- Anything Claude can regenerate cheaper than maintain

**Rule**: document what is non-obvious from the code — decisions, tradeoffs, "we tried X and it failed because Y."

---

## 3. Product / business knowledge

```
20-Areas/product/
├── _MOC.md
├── vision.md               (1 page, dated)
├── strategy.md
├── roadmap.md              (Dataview-driven)
├── monetization/
│   ├── tiers.md
│   └── pricing-log.md      (append-only)
├── personas/
├── competitors/            (one note each, same template)
├── research/
├── metrics/
│   └── dashboard.md        (Dataview pulls from daily notes)
└── decisions/              (business ADRs, same template as engineering)
```

Workflow: drop raw inputs (screenshots, links, interview notes) into `inbox/`, then have Claude compile periodically into structured notes.

Dashboards example:
````markdown
## Open product decisions
```dataview
TABLE status, date FROM "20-Areas/product/decisions"
WHERE status = "proposed"
SORT date DESC
```
````

---

## 4. AI-friendly structure (the part everyone misses)

### Frontmatter — small fixed set of keys, used consistently everywhere

```yaml
---
type: adr | api-endpoint | module | runbook | research | persona | competitor | decision | log | moc
status: draft | active | archived | superseded
created: 2026-05-21
updated: 2026-05-21
area: [backend, ml]
tags: [adr, clip]
source: src/card_matcher.py    # optional, links to actual code
related: [[other-note]]
---
```

LLMs use frontmatter heavily for filtering ("find all `type: adr` with `status: active` in `area: ml`"). Inconsistent tagging is the #1 vault rot symptom.

### Heading hygiene — chunking matters

Markdown-aware chunking on H2 boundaries boosts LLM retrieval accuracy 5-10% vs fixed-size splits.

- One concept per H2. If a section >400 lines, split to own note.
- Don't go deeper than H3 in technical notes.
- TL;DR in the first line below title — RAG grabs top of files preferentially.

### Atomic vs monolithic — the right unit is "one thing a question would be about"

- One note per API endpoint ✓
- One note per module ✓
- One note per ADR ✓
- NOT one note per OCR engine option — that's overcatalogued.

Each note should be able to "win a citation on its own merits" — if reading just this note answers a question, it's the right size.

### MOCs vs tags vs folders

- **Folders**: stable coarse buckets (PARA layer). Used by Claude to scope walks.
- **MOCs**: hand-curated topic indexes. Better than tags for AI — give *narrative context*.
- **Tags**: only for cross-cutting attributes (`#urgent`, `#blocked`). Don't use as second folder system.

### Context packs — highest-leverage AI pattern

`_context-packs/` folder with curated bundles:
```
_context-packs/
├── working-on-defect-detection.md
├── working-on-mobile-grading-flow.md
└── debugging-clip-fallback.md
```

Each pack = list of `![[transcluded notes]]` + 2-3 sentences framing. Session start becomes "Claude, read `_context-packs/working-on-defect-detection.md`" instead of letting it crawl 300 files. **Closest thing to a "prepared lecture" you can give an AI.**

### `index.md` + `log.md` — Karpathy LLM Wiki

`index.md` at vault root: hand-curated catalog of important notes, one-line summaries each, by category. LLM's table of contents.

`log.md` at vault root: append-only, one line per session/event:
```
## [2026-05-21] decision | raised CLIP fallback threshold to 0.32
## [2026-05-20] incident | TAG scraper broken after CDN migration
## [2026-05-18] session | added defect detection pipeline scaffold
```

Lets the LLM (and you) replay project history without scanning every file.

### CLAUDE.md — keep ~80-120 lines

Past 120 lines you're hurting Claude's instruction-following. Include:
- Vault layout (so Claude doesn't crawl `data/`, `node_modules/`)
- Frontmatter schema (so Claude writes consistent notes)
- Project-specific "always do X / never do Y" rules
- Pointer to `index.md` and `log.md`
- Skill invocation rules

Exclude: personality directives, generic engineering advice, explanations of what code does (Claude reads code).

---

## 5. Essential plugins — opinionated short list

| Plugin | Solves | Skip if |
|---|---|---|
| **Templater** | Reusable templates with dynamic fields. Keeps frontmatter consistent | Never skip |
| **Dataview** | Queries over frontmatter. Powers roadmaps, dashboards, orphan checks | Never skip |
| **Periodic Notes** | Daily/weekly notes scaffolded | Skip if won't do weekly reviews |
| ~~File Ignore~~ ⚠️ | ~~`.gitignore`-style patterns~~ | **DON'T install** — physically renames files with `.` prefix → breaks code (`venv/` → `.venv/` breaks Python). Use Obsidian's native "Excluded files" instead (Settings → Files & Links → Excluded files) |
| **Excalidraw** | Architecture sketches | Skip if Mermaid-only is fine |
| **Linter** | Auto-normalizes frontmatter, dates, whitespace. Prevents vault rot | Set-and-forget |
| **Tasks** | Aggregate `- [ ]` across vault | Skip if using GitHub Issues/Linear |

**Avoid**: Kanban, Calendar, Advanced URI, theme plugins, hotkey plugins. The most common Obsidian failure is "plugin crazy from day one."

### Excluded files patterns for CardChecker vault (Obsidian native, Settings → Files & Links → Excluded files)

```
node_modules/
venv/
.venv/
data/
models/
.git/
dist/
build/
*.pyc
__pycache__/
mobile/node_modules/
mobile/.expo/
runs/
*.zip
```

---

## 6. Concrete starter structure (see implementation note)

See proposed full skeleton in §6 of source research. Bootstrap exactly this — don't perfect, just create.

Top-level inside `D:\CardChecker\`:
```
CLAUDE.md             (existing — keep ~100 lines)
index.md              (NEW — vault catalog)
log.md                (NEW — append-only event log)
10-Projects/          (current sprints)
20-Areas/             (long-lived domains: backend, mobile, ml, ops, product, business)
30-Resources/         (ADRs, templates, reference, clippings)
40-Archive/           (done projects, deprecated)
_context-packs/       (curated note bundles for AI sessions)
_daily/               (Periodic Notes)
_weekly/              (Friday reviews)
assets/               (already exists — diagrams)
src/, mobile/, scripts/, data/, etc.   (existing code, untouched)
```

---

## 7. Anti-patterns (in priority order)

1. **Tag sprawl** — `#ml` vs `#ML` vs `#machine-learning`. Lock vocabulary, lint.
2. **Folder/tag duplication** — if folder `ml/` AND tag `#ml`, pick one. Folders win.
3. **Inbox that never gets processed** — solo devs don't have GTD discipline. Use `_context-packs/` instead.
4. **Orphan notes** — Friday Dataview: `LIST WHERE length(file.inlinks) = 0`. Link or archive.
5. **Plugin sprawl** — §5 list is ceiling, not floor.
6. **3000-line "everything I know about X"** notes — unsearchable, chunks poorly.
7. **Notes that rephrase code** — if Claude can produce it in 30s from reading code, don't write it.
8. **CLAUDE.md ballooning** — past 120 lines, hurts Claude.
9. **Frontmatter inconsistency** — 80% with `created`, 20% without. Lint.
10. **Vault separate from code** — colocate (already doing this).
11. **Daily-notes-as-journal becoming whole vault** — daily notes are capture surface; value lives in what you promote out.

---

## 8. Maintenance — two cadences only

### Friday 30-min review (weekly)

Templater file `_weekly/YYYY-Www.md`:

````markdown
## Decisions this week
```dataview
LIST file.link FROM "30-Resources/adr" WHERE date >= date(today) - dur(7 days)
```

## Notes touched
```dataview
LIST FROM "" WHERE file.mtime >= date(today) - dur(7 days)
SORT file.mtime DESC LIMIT 20
```

## Orphan check
```dataview
LIST FROM "" WHERE length(file.inlinks) = 0 AND file.folder != "_daily"
```

## Next week top 3
- [ ]
- [ ]
- [ ]
````

Then append one line to `log.md`.

### Quarterly 1-hour audit

- Archive completed projects (`10-Projects/` → `40-Archive/`)
- Re-read MOCs, prune dead links
- Update `vision.md` / `strategy.md` if changed
- Update `CLAUDE.md` based on patterns Claude has been getting wrong

**Skip**: daily reviews, monthly reviews, yearly reviews.

---

## 9. Week 1 bootstrap plan (strict order, ~6 hours total)

**Day 1 (1h)**:
1. Install plugins: Templater, Dataview, Periodic Notes, File Ignore, Linter. Skip rest.
2. Configure File Ignore with §5 exclude list. Verify Obsidian doesn't index `data/`, `node_modules/`.
3. Create empty folder skeleton from §6 (just mkdir).

**Day 2 (1h)**:
4. Write three Templater templates: `adr.md`, `api-endpoint.md`, `module.md`.
5. Create `index.md` + `log.md` at root. Write first log line.

**Day 3-4 (2h)**:
6. For each endpoint in `src/api.py`, have Claude create `20-Areas/backend/api/<endpoint>.md` from template based on source. Review 60s each.
7. Same for each module in `src/`. ~15 notes total.

**Day 5 (45 min)**:
8. Write 3 ADRs from memory — past decisions you'd hate to lose (e.g. SQLite vs Postgres, Gemini grading, React Native).
9. Write `20-Areas/backend/_MOC.md` and `20-Areas/ml/_MOC.md` — just list notes with one-line descriptions.

**Day 6 (30 min)**:
10. Update `CLAUDE.md` to mention vault structure, frontmatter convention, "read `index.md` + `log.md` at session start", "write ADRs for non-obvious decisions."
11. Have Claude regenerate `index.md` by walking the vault.

**Day 7 (30 min)**:
12. Create 3 `_context-packs/` files for active priorities (defect detection, mobile auth, JP/TW OCR).
13. Set up Friday weekly-review template.

**Then**: every non-obvious decision → ADR. Every Friday → 30-min review. Quarterly → 1h audit. Stop.

---

## Sources

- Karpathy LLM Wiki gist: https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f
- Bijit Ghosh — Complete Guide to CLAUDE.md: https://medium.com/@bijit211987/the-complete-guide-to-claude-md-memory-rules-loading-and-cross-tool-compression-97cc12ed037b
- Mart Kempenaar — Obsidian as AI-Native KB with Claude Code: https://medium.com/@martk/turning-obsidian-into-an-ai-native-knowledge-system-with-claude-code-27cb224404cf
- Mohit Aggarwal — Claude Code + Obsidian as PM: https://medium.com/all-about-claude/how-i-use-claude-code-obsidian-as-a-product-manager-4-workflows-that-actually-changed-my-work-bc04360b905d
- Matteo Paoli — Obsidian as ADR Tool: https://medium.com/@mttpla/using-obsidian-as-an-adr-tool-5f63d187de6b
- MADR specification: https://adr.github.io/madr/
- PARA + Zettelkasten combined: https://digital-garden.ontheagilepath.net/para-and-zettelkasten-combined
- LYT + AI guide (WenHao Yu): https://yu-wenhao.com/en/blog/lyt-framework-guide/
- LYT Maps blog: https://blog.linkingyourthinking.com/maps/
- Steph Ango — How I Use Obsidian: https://stephango.com/vault
- Tejaaswini Narendra — Vault rot diagnostic: https://tejnaren07.medium.com/my-obsidian-vault-was-rotting-so-i-wrote-a-plugin-to-diagnose-it-a1343830fbbb
- Atomic Content Architecture for RAG: https://blog.trysteakhouse.com/blog/atomic-content-architecture-rag-friendly-retrieval-chunks
- MachineLearningMastery — Chunking Techniques: https://machinelearningmastery.com/essential-chunking-techniques-for-building-better-llm-applications/
- Modem Guides — Local LLM Knowledge Base: https://www.modemguides.com/blogs/ai-infrastructure/local-llm-knowledge-base-obsidian-setup-guide
- Plaban Nayak — Beyond RAG (Karpathy Wiki): https://levelup.gitconnected.com/beyond-rag-how-andrej-karpathys-llm-wiki-pattern-builds-knowledge-that-actually-compounds-31a08528665e
- aimaker.substack — LLM Wiki walkthrough: https://aimaker.substack.com/p/llm-wiki-obsidian-knowledge-base-andrej-karphaty
- Sébastien Dubois — Must-have Obsidian Plugins 2026: https://www.dsebastien.net/the-must-have-obsidian-plugins-for-2026/
- Obsidian File Ignore plugin: https://github.com/Feng6611/Obsidian-File-Ignore
- Excalidraw plugin: https://github.com/zsviczian/obsidian-excalidraw-plugin
- VSCode Obsidian Links extension: https://marketplace.visualstudio.com/items?itemName=StefanSteinert.vscode-obsidian-links
- Christian Houmann — Weekly review in Obsidian: https://bagerbach.com/blog/weekly-review-obsidian/
- MakeUseOf — Pitfalls I wish I knew: https://www.makeuseof.com/i-wish-i-knew-these-before-creating-my-obsidian-vault/
- Best practices for Claude Code (Anthropic): https://code.claude.com/docs/en/best-practices
- Chase AI — Claude Code + Obsidian Persistent Memory: https://www.chaseai.io/blog/claude-code-obsidian-persistent-memory
