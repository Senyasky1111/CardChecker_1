---
description: Orchestrated multi-agent workflow for feature/bug/refactor — spec → implementation → tests → code review → ui review (if frontend) → security review (if security-relevant). Pass description as argument. Use for any non-trivial change worth proper review.
---

# /feature-flow — Multi-Agent Development Workflow

You are the **orchestrator** for a structured development workflow. The user invoked you with a description of work to do. Run the workflow below, presenting checkpoints для user approval at key transitions.

## Workflow

### Stage 0 — Disambiguate (skip if clear)

If the user's description is genuinely vague, ask ONE clarifying question before kicking off. Otherwise proceed.

### Stage 1 — Spec (spec-writer subagent)

Spawn the `spec-writer` subagent with:
- The user's description
- Pointer to any obviously relevant files / past notes (use your knowledge of the codebase)

Wait for spec output. Show it to user. **Get explicit user approval** before proceeding ("approve / change scope / cancel").

If user requests changes — modify spec inline together with user, don't re-spawn spec-writer.

### Stage 2 — Implementation (you, main session)

Implement the spec. Use existing domain skills where relevant (`/cv-expert`, `/card-engine`, `/defect-grader`, `/mobile-dev`, `/data-engineer`, `/ml-strategy`, `/train-coach`, `/dataset-doctor`) for deep context if the work touches those domains.

Edit files, write code, run things. Standard work.

When done, summarise: which files changed, what was implemented vs spec. Show user before review stage.

### Stage 3 — Tests (tester subagent)

Spawn the `tester` subagent. It will:
- Read the diff
- Write tests for the changes
- Run tests
- Report results

If tests fail and the failure is in production code, tester reports it back — you fix, then re-spawn tester.

### Stage 4 — Code review (code-reviewer subagent)

Spawn the `code-reviewer` subagent (read-only). It returns ranked findings.

Address critical/important findings (you, main session). Skip minor unless trivial.

### Stage 5a — UI review (ui-reviewer subagent) — IF FRONTEND TOUCHED

If the diff includes `.tsx`, `.jsx`, `.css` files — spawn `ui-reviewer`. Address critical accessibility findings.

### Stage 5b — Security review (security-reviewer subagent) — IF SECURITY-RELEVANT

If the diff touches any of:
- Auth code, login, signup, session, token handling
- Payment / Stripe / billing / subscription
- User input handling (forms, file uploads, API params)
- Secrets / env vars
- External API calls
- DB queries

Spawn `security-reviewer` (uses Opus). Address block-merge and high findings.

### Stage 6 — Synthesis

Summarise to user:
- What was implemented
- What tests were written, results
- Findings addressed / deferred
- Recommended next step (merge / additional work / archive)

## Parallel mode (optional, for complex work)

If the change is large and review stages can run in parallel, ask user: "Run reviewers in parallel as an agent team?" If yes:

```
Have agents code-reviewer, ui-reviewer (if frontend), security-reviewer (if security-relevant) form a team to review PR #N. Have them discuss disagreements and synthesise findings.
```

Requires `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in settings.json (enabled in this repo).

## When NOT to use this workflow

- One-line typo fix → just edit
- Documentation-only change → just edit
- Reverting a commit → just revert
- Exploration / spike → run loose, no spec needed

Use this for work that **would benefit from a code review** if you had a teammate. Solo, this workflow simulates that team.

## Gotchas (learned from first test, 2026-05-24)

### Cross-repo permissions

When the work targets a sibling repo (e.g. `D:\amotrychenko\Desktop\CardChecker_MVP\` from a session in `d:\CardChecker\`):

- Subagents inherit a tighter permission scope than the main session.
- Even if `permissions.additionalDirectories` is set in `.claude/settings.json`, **subagents may need a session restart** to pick it up. Mid-session additions don't propagate.
- **Workaround without restart**: main session reads the relevant files first, inlines their contents inside the subagent prompt. Works for spec-writer / code-reviewer / security-reviewer. Less elegant but faster.

### No automated test framework

When the repo has no `npm test` / `pytest` / `vitest` configured (common for webapp MVPs):

- Tester subagent **adapts** — produces a structured manual test plan instead of running tests.
- Tester also recommends if Vitest setup is worth doing now (criteria: complex UI matrix that's hard to verify manually).
- Don't expect "tests passed" output — get a "test plan + spot-check findings" report instead.

### Parallel reviewers vs Agent Teams

- For **orthogonal review aspects** (UI accessibility / security / code quality / test coverage) — just spawn subagents in parallel. They don't need to talk to each other. Cheaper than Agent Teams.
- Use **Agent Teams** (`TeamCreate` + `SendMessage`) only when reviewers need to **resolve disagreements** between findings, or when one reviewer's output must inform another's input (e.g. spec writer → architect → security reviewer in sequence with discussion).

### Cross-validation as proof of bugs

Two reviewers (e.g. tester and code-reviewer) independently finding the same bug is **stronger evidence** than a single reviewer flagging it 5x. Prioritize cross-confirmed findings in synthesis.

### Subagent context inheritance

Subagents don't see this session's conversation. Always include in the prompt:
- The relevant files (or paths if permissions allow reading)
- Recent decisions / spec / ADRs
- What the user actually asked for (not what you inferred)
- Their role (read-only? can edit tests? can edit production?)

## Stages summary (visual)

```
User: /feature-flow "fix Stripe webhook validation"
         │
         ▼
Stage 1: spec-writer ──→ user approves spec
         │
         ▼
Stage 2: implementation (main session, uses domain skills)
         │
         ▼
Stage 3: tester ──→ run tests, fix failures, iterate
         │
         ▼
Stage 4: code-reviewer ──→ address findings
         │
         ▼
Stage 5a (if frontend): ui-reviewer ──→ address findings
Stage 5b (if security-relevant): security-reviewer ──→ address findings
         │
         ▼
Stage 6: synthesis + recommended next step
```

## Hard constraints

- **Always** get user approval after spec stage. Don't skip to implementation.
- **Never** skip tests on the assumption "this is too small" — if it's worth `/feature-flow`, it's worth tests.
- **Never** ignore a block-merge security finding without explicit user override.
- **Always** spawn reviewers as subagents (separate context), not inline в main session.
- If user wants a faster lightweight version: skip Stage 1 (spec) and run Stages 2-6 with the user's raw description. They'll lose grounding but ship faster.