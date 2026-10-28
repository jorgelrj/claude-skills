#!/usr/bin/env python3
"""TEMPO guard: ask before rm deletes something outside the working tree.

PreToolUse hook for Bash. A builder once ran `rm -rf /tmp/x` on a file it had
not made. This hook does not block: it turns such a command into a permission
prompt. Allowed without asking: paths inside the session's working directory
(worktrees live there), mktemp directories (`tmp.*`) and `tempo-*` scratch
directories under the temp folders, and targets it cannot resolve ($VAR).
Any error in the hook lets the command through.
"""
import json
import os
import re
import shlex
import sys

TEMP_ROOTS = [os.path.realpath(p) for p in {"/tmp", "/private/tmp", "/var/folders", os.environ.get("TMPDIR", "/tmp")}]


def inside(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def scratch(path):
    if not any(inside(path, r) for r in TEMP_ROOTS):
        return False
    return any(part.startswith(("tmp.", "tempo-")) for part in path.split("/"))


def risky_targets(command, cwd):
    out, here = [], cwd
    for seg in re.split(r"&&|\|\||;|\||\n", command):
        try:
            words = shlex.split(seg)
        except ValueError:
            continue
        while words and words[0] in ("sudo", "command", "builtin", "nohup"):
            words = words[1:]
        if not words:
            continue
        if words[0] == "cd" and len(words) > 1 and "$" not in words[1]:
            here = os.path.realpath(os.path.join(here, os.path.expanduser(words[1])))
            continue
        if os.path.basename(words[0]) != "rm":
            continue
        for w in words[1:]:
            if w.startswith("-") or "$" in w or "`" in w:
                continue
            p = os.path.realpath(os.path.join(here, os.path.expanduser(w)))
            if inside(p, cwd) or scratch(p):
                continue
            out.append(p)
    return out


def main():
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") or ""
        if "rm" not in command:
            return 0
        cwd = os.path.realpath(data.get("cwd") or os.getcwd())
        targets = risky_targets(command, cwd)
    except Exception:
        return 0
    if targets:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": "TEMPO guard: rm outside the working directory: " + ", ".join(targets[:3]),
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
