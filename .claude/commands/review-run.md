---
name: review-run
description: Manual entry point to invoke the model-reviewer subagent on a finished training run. Usage — `/review-run runs/expN`.
---

# /review-run — Spawn model-reviewer on a training run

Usage: `/review-run runs/exp42` (or any path to a Ultralytics / HuggingFace / Lightning run folder).

When invoked:

1. Verify the path exists and contains at least one of: `results.csv`, `metrics.json`, `confusion_matrix.png`, `args.yaml`.
2. Spawn the `model-reviewer` subagent via the Agent tool with the run path as input.
3. Wait for its report.
4. Surface the report to the user verbatim, with a one-line TL;DR added on top.

If the path is missing or the run is malformed, ask the user to point at a valid run folder. Don't try to interpret partial results yourself.

If no `runs/` directory exists at all, suggest the user run a training script first via `/train-coach`.

This skill is a thin wrapper — the actual reviewing logic lives in [.claude/agents/model-reviewer.md](../agents/model-reviewer.md).