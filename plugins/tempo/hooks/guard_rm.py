#!/usr/bin/env python3
"""TEMPO guard: block rm outside the project and the temp folders, without asking.

PreToolUse hook for Bash. A builder once ran `rm -rf /tmp/x` on a file it had
not made. Up to 0.8.0 this hook turned every rm outside the working directory
into a permission prompt, which fired on scratchpads, other worktrees and
non-TEMPO sessions. It never asks now. Allowed without a word: anything inside
the project (the main checkout and every worktree, found through
`git rev-parse --git-common-dir`) and anything under the temp folders. Denied,
with a reason the model reads and works around: the project root itself, its
`.git`, the home folder, and any other path. Targets it cannot resolve ($VAR,
globs left to the shell) pass. Any error in the hook lets the command through.
"""
import json
import os
import re
import shlex
import subprocess
import sys

TEMP_ROOTS = [os.path.realpath(p) for p in {"/tmp", "/private/tmp", "/var/folders", "/private/var/folders", os.environ.get("TMPDIR") or "/tmp"}]


def inside(path, root):
    return path == root or path.startswith(root.rstrip("/") + "/")


def project_root(cwd):
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=cwd, capture_output=True, text=True, timeout=2,
        )
        common = out.stdout.strip()
        if out.returncode == 0 and common:
            common = os.path.realpath(common)
            return os.path.dirname(common) if os.path.basename(common) == ".git" else common
    except Exception:
        pass
    return cwd


def blocked(path, root):
    """Return why `path` may not be removed, or None."""
    if path in ("/", os.path.realpath(os.path.expanduser("~"))):
        return "the root or home folder"
    if path == root or inside(path, os.path.join(root, ".git")):
        return "the project root or its .git"
    if inside(path, root) or any(inside(path, t) and path != t for t in TEMP_ROOTS):
        return None
    return "outside the project and the temp folders"


def blocked_targets(command, cwd, root):
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
            why = blocked(p, root)
            if why:
                out.append(f"{p} ({why})")
    return out


def main():
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") or ""
        if not re.search(r"\brm\b", command):
            return 0
        cwd = os.path.realpath(data.get("cwd") or os.getcwd())
        targets = blocked_targets(command, cwd, project_root(cwd))
    except Exception:
        return 0
    if targets:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "TEMPO guard: not removing " + ", ".join(targets[:3]) + ". "
                "Delete only inside the project or a temp folder (mktemp -d). "
                "Do not ask the user: leave the path in place, carry on, and name it in your report or final message."
            ),
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
