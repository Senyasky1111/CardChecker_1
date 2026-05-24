#!/usr/bin/env python
"""PostToolUse hook for CardChecker.

When a Bash command that looks like a training invocation completes,
emit a hint suggesting the user invoke the model-reviewer subagent on
the freshest `runs/` folder. No auto-spawning — Claude sees the hint
and decides.

Matches: train_yolo, train_defect_yolo, `yolo train`, finetune_clip,
dinov2 train, lightning train.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return

    tool_input = payload.get("tool_input", {}) or {}
    cmd = tool_input.get("command", "") or ""

    pattern = re.compile(
        r"\b(train_yolo|train_defect_yolo|finetune_clip|dinov2[^\s]*train|"
        r"yolo\s+train|yolov8[^\s]*\s+train|lightning\s+train)\b",
        re.IGNORECASE,
    )
    if not pattern.search(cmd):
        return

    runs_dirs = sorted(
        (d for d in glob.glob("runs/*/") if os.path.isdir(d)),
        key=os.path.getmtime,
        reverse=True,
    )
    latest = runs_dirs[0].rstrip(os.sep) if runs_dirs else "runs/<exp>"

    hint = (
        f"[training-detected] A training command appears to have run.\n"
        f"When it finishes, audit it via:  /review-run {latest}\n"
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