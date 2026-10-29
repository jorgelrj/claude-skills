#!/usr/bin/env python3
"""TEMPO guard: never push a tempo/ branch.

PreToolUse hook for Bash. Branches under tempo/ are TEMPO's local work branches
(work orders, repro). Up to 0.13.0 the task branch was tempo/<ticket> too and was
pushed, so remotes filled with tempo/... branches. The task branch now follows the
repo's convention (feat/..., fix/...), and this hook denies any `git push` whose
destination is under tempo/: a named refspec, `HEAD` or a bare push while a tempo/
branch is checked out, and `--all` or `--mirror` while a local tempo/ branch exists.
`git push origin tempo/x:feat/x` passes: the remote name is what counts. Anything it
cannot read ($VAR refspecs) passes. Any error in the hook lets the command through.
"""
import json
import os
import re
import shlex
import subprocess
import sys

PREFIX = "tempo/"
VALUE_OPTS = {"-o", "--push-option", "--repo", "--receive-pack", "--exec", "--recurse-submodules"}


def git(cwd, *args):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=2)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def short(ref):
    ref = ref.lstrip("+")
    for p in ("refs/heads/", "refs/remotes/"):
        if ref.startswith(p):
            return ref[len(p):]
    return ref


def bad_pushes(command, cwd):
    out, here = [], cwd
    for seg in re.split(r"&&|\|\||;|\||\n", command):
        try:
            words = shlex.split(seg)
        except ValueError:
            continue
        while words and words[0] in ("sudo", "command", "builtin", "nohup", "env"):
            words = words[1:]
        if not words:
            continue
        if words[0] == "cd" and len(words) > 1 and "$" not in words[1]:
            here = os.path.realpath(os.path.join(here, os.path.expanduser(words[1])))
            continue
        if os.path.basename(words[0]) != "git":
            continue
        # git [-C dir] [-c k=v] push ...
        i, where = 1, here
        while i < len(words) and words[i].startswith("-"):
            if words[i] in ("-C", "-c") and i + 1 < len(words):
                if words[i] == "-C":
                    where = os.path.realpath(os.path.join(where, os.path.expanduser(words[i + 1])))
                i += 2
            else:
                i += 1
        if i >= len(words) or words[i] != "push":
            continue
        args, flags, j = [], set(), i + 1
        while j < len(words):
            w = words[j]
            if w in VALUE_OPTS:
                j += 2
                continue
            if w.startswith("-"):
                flags.add(w.split("=", 1)[0])
            else:
                args.append(w)
            j += 1
        if "--delete" in flags or "-d" in flags:
            continue  # removing a pushed tempo/ branch is the cleanup, not the problem
        if flags & {"--all", "--mirror", "--branches"}:
            local = [b for b in git(where, "for-each-ref", "--format=%(refname:short)", "refs/heads").split() if b.startswith(PREFIX)]
            if local:
                out.append(f"--all would push {', '.join(local[:3])}")
            continue
        refspecs = args[1:]
        if not refspecs:
            refspecs = ["HEAD"]
        for spec in refspecs:
            if "$" in spec or "`" in spec:
                continue
            src, _, dst = spec.partition(":")
            dst = short(dst or src)
            if dst == "HEAD":
                dst = git(where, "rev-parse", "--abbrev-ref", "HEAD")
            if dst.startswith(PREFIX):
                out.append(dst)
    return out


def main():
    try:
        data = json.load(sys.stdin)
        command = (data.get("tool_input") or {}).get("command") or ""
        if not re.search(r"\bpush\b", command):
            return 0
        cwd = os.path.realpath(data.get("cwd") or os.getcwd())
        bad = bad_pushes(command, cwd)
    except Exception:
        return 0
    if bad:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "TEMPO guard: not pushing " + ", ".join(bad[:3]) + ". Branches under tempo/ are local work branches "
                "and never go to a remote. Push only the task branch, named by `tempo_config.py names` after the "
                "repo's convention (feat/..., fix/...). If the task branch itself is under tempo/, rename it first "
                "(orchestrator 3.12) and push the new name."
            ),
        }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
