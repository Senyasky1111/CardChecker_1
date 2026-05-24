#!/usr/bin/env python
"""PostToolUse hook for CardChecker.

When a Bash command **actually invokes** a training script, emit a hint
suggesting `/review-run <latest runs/ folder>`. Hint goes to Claude;
no auto-spawn.

Hard rule: match only real invocations (python <script> | yolo train | etc),
not commands that merely *mention* training keywords (git commit messages,
echo, grep, cat, find...).
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys


# Verbs that read/quote text but never run training. Skip these wholesale
# even if the command line contains training-script names.
NON_EXECUTING_PREFIXES = (
    "git ",
    "echo ",
    "cat ",
    "grep ",
    "rg ",
    "head ",
    "tail ",
    "find ",
    "ls ",
    "less ",
    "more ",
    "diff ",
    "sed ",
    "awk ",
)

# Real training invocations. Anchored on the actual executable verb.
TRAINING_PATTERNS = [
    # python ... train_yolo*.py / train_defect_yolo*.py / finetune_clip*.py / dinov2*train*.py
    # Use \w* trailing instead of \b — script names like train_yolo_card.py have
    # word chars after the keyword and a strict \b would not match.
    re.compile(
        r"\b(?:python|python3|python\.exe)\b[^\n;&|]*?"
        r"\b(?:train_yolo\w*|train_defect_yolo\w*|finetune_clip\w*|dinov2\w*train\w*)",
        re.IGNORECASE,
    ),
    # `yolo train ...` (Ultralytics CLI)
    re.compile(r"(?:^|[\s;&|])yolo\s+train\b", re.IGNORECASE),
    # `lightning run ... train ...`
    re.compile(r"(?:^|[\s;&|])lightning\s+(?:run\s+)?train\b", re.IGNORECASE),
]


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    tool_input = payload.get("tool_input", {}) or {}
    cmd = (tool_input.get("command", "") or "").lstrip()

    # Cheap guard: read-only verbs never train anything.
    cmd_lower = cmd.lower()
    if any(cmd_lower.startswith(p) for p in NON_EXECUTING_PREFIXES):
        return

    if not any(p.search(cmd) for p in TRAINING_PATTERNS):
        return

    runs_dirs = sorted(
        (d for d in glob.glob("runs/*/") if os.path.isdir(d)),
        key=os.path.getmtime,
        reverse=True,
    )
    latest = runs_dirs[0].replace("\\", "/").rstrip("/") if runs_dirs else "runs/<exp>"

    hint = (
        f"[training-detected] A training invocation completed.\n"
        f"Audit it via:  /review-run {latest}\n"
        f"That spawns the model-reviewer subagent for a read-only post-mortem."
    )

    out = {
        "hookSpecificOutput": {
            "hookEventName": "PostToolUse",
            "additionalContext": hint,
        }
    }
    print(json.dumps(out))


if __name__ == "__main__":
    main()