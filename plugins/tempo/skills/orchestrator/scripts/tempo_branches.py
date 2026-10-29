#!/usr/bin/env python3
"""TEMPO branches: delete local work-order and repro branches once the task branch holds their work.

`git branch -d` only deletes a branch merged into HEAD or its upstream. TEMPO's
work-order branches are merged into the task branch, not into the base branch the
main checkout sits on, so `-d` always refuses. This script checks each branch
against the task branch itself and deletes it with `-D` only when nothing on it
would be lost.

A branch is deleted only when one of these holds:
  merged   its tip is an ancestor of the task branch (local, or its remote copy)
  patches  every commit it has that the task branch lacks has an equal patch there (git cherry)
  folded   its tip is an ancestor of an earlier tip of the task branch (reflog or --from)
           whose tree is the tree of a commit the task branch still has: FOLD squashed
           the fixups and kept the content
A branch is always kept when it is the task or base branch, is checked out in a
worktree, has an upstream, or exists on a remote under the same name. Remote
branches are never touched.

Usage: tempo_branches.py <command> [args]
  prune  --repo R --task-branch B [--base-branch X] [--branch NAME ...] [--glob PATTERN ...]
         [--from SHA ...] [--dry-run]
         check and delete the named branches and the ones matching the globs
         (default globs: tempo/B-wo-*, tempo/B-repro, and the pre-0.14 B-wo-*, B-repro)
  sweep  --repo R [--wo-pattern P ...] [--repro-pattern P ...] [--dry-run]
         prune for every task in R/.tempo/ whose stage is DONE; patterns take {branch}
         (defaults: the four globs above with {branch} for B)
  pushed --repo R
         list remote branches under tempo/. Those names are TEMPO's local work branches and
         should never have been pushed; the script only reports them, it never touches a remote
Prints one line per branch: DELETED <branch> <sha> (<why>), WOULD-DELETE (--dry-run) or
KEPT <branch> (<reason>); SKIPPED <task branch> when it does not exist; PUSHED <remote>/<branch>.
Exit 0 ok, 1 error.
"""
import argparse
import fnmatch
import json
import subprocess
import sys
from pathlib import Path


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r


def out(repo, *args):
    return git(repo, *args).stdout.strip()


def ok(repo, *args):
    return git(repo, *args, check=False).returncode == 0


def sha(repo, ref):
    r = git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False)
    return r.stdout.strip() if r.returncode == 0 else None


def local_branches(repo):
    return out(repo, "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines()


def checked_out(repo):
    names = set()
    for line in out(repo, "worktree", "list", "--porcelain").splitlines():
        if line.startswith("branch refs/heads/"):
            names.add(line[len("branch refs/heads/"):])
    return names


def on_remote(repo, name):
    refs = out(repo, "for-each-ref", "--format=%(refname)", "refs/remotes").splitlines()
    return any(r.split("/", 3)[-1] == name for r in refs if r.count("/") >= 3)


def has_upstream(repo, name):
    return ok(repo, "rev-parse", "--verify", "--quiet", f"{name}@{{upstream}}")


def task_tips(repo, task):
    """The task branch's tips: local, each remote copy."""
    tips = [sha(repo, f"refs/heads/{task}")]
    for r in out(repo, "for-each-ref", "--format=%(refname)", "refs/remotes").splitlines():
        if r.count("/") >= 3 and r.split("/", 3)[-1] == task:
            tips.append(sha(repo, r))
    return [t for t in tips if t]


def task_trees(repo, tips):
    """Trees of the task branch's latest commits (capped; a fold rewrites only the task's own)."""
    return set(out(repo, "log", "--format=%T", "-n", "2000", *tips).splitlines())


def earlier_tips(repo, task, extra):
    r = git(repo, "reflog", "show", "--format=%H", f"refs/heads/{task}", check=False)
    seen, tips = set(), []
    for h in [*extra, *(r.stdout.split() if r.returncode == 0 else [])]:
        full = sha(repo, h)
        if full and full not in seen:
            seen.add(full)
            tips.append(full)
    return tips


def contained(repo, tip, task, tips, extra):
    for t in tips:
        if ok(repo, "merge-base", "--is-ancestor", tip, t):
            return "merged"
    for t in tips:
        lines = out(repo, "cherry", t, tip).splitlines()
        if lines and all(l.startswith("-") for l in lines):
            return "patches"
    trees = task_trees(repo, tips)
    for r in earlier_tips(repo, task, extra):
        if ok(repo, "merge-base", "--is-ancestor", tip, r) and out(repo, "rev-parse", r + "^{tree}") in trees:
            return "folded"
    return None


def unshipped(repo, tip, tips):
    return out(repo, "rev-list", "--count", tip, *[f"^{t}" for t in tips])


def prune(repo, task, base, names, globs, extra, dry):
    tips = task_tips(repo, task)
    if not tips:
        print(f"SKIPPED {task} (task branch not found; nothing checked)")
        return
    have = local_branches(repo)
    cands = []
    for n in names:
        if n not in cands:
            cands.append(n)
    for g in globs:
        for n in have:
            if fnmatch.fnmatchcase(n, g) and n not in cands:
                cands.append(n)
    busy = checked_out(repo)
    for n in cands:
        tip = sha(repo, f"refs/heads/{n}")
        if tip is None:
            continue
        if n in (task, base):
            print(f"KEPT {n} (task or base branch)")
        elif n in busy:
            print(f"KEPT {n} (checked out in a worktree)")
        elif has_upstream(repo, n) or on_remote(repo, n):
            print(f"KEPT {n} (pushed or tracking a remote branch)")
        else:
            why = contained(repo, tip, task, tips, extra)
            if not why:
                print(f"KEPT {n} ({unshipped(repo, tip, tips)} commits not in {task})")
            elif dry:
                print(f"WOULD-DELETE {n} {tip[:10]} ({why})")
            elif sha(repo, f"refs/heads/{n}") != tip:
                print(f"KEPT {n} (moved while checking)")
            else:
                git(repo, "branch", "-D", n)
                print(f"DELETED {n} {tip[:10]} ({why})")


# tempo/ names are local work branches (0.14.0); before that work orders were <task>-wo-NN.
WO_PATTERNS = ["tempo/{branch}-wo-*", "{branch}-wo-*"]
REPRO_PATTERNS = ["tempo/{branch}-repro", "{branch}-repro"]
LOCAL_PREFIX = "tempo/"


def pushed_local(repo):
    for r in out(repo, "for-each-ref", "--format=%(refname)", "refs/remotes").splitlines():
        parts = r.split("/", 3)
        if len(parts) == 4 and parts[3].startswith(LOCAL_PREFIX):
            print(f"PUSHED {parts[2]}/{parts[3]}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sp = p.add_subparsers(dest="cmd", required=True)
    pr = sp.add_parser("prune")
    pr.add_argument("--repo", default=".")
    pr.add_argument("--task-branch", required=True)
    pr.add_argument("--base-branch")
    pr.add_argument("--branch", action="append", default=[])
    pr.add_argument("--glob", action="append", default=[])
    pr.add_argument("--from", dest="extra", action="append", default=[])
    pr.add_argument("--dry-run", action="store_true")
    sw = sp.add_parser("sweep")
    sw.add_argument("--repo", default=".")
    sw.add_argument("--wo-pattern", action="append")
    sw.add_argument("--repro-pattern", action="append")
    sw.add_argument("--dry-run", action="store_true")
    pu = sp.add_parser("pushed")
    pu.add_argument("--repo", default=".")
    a = p.parse_args()
    repo = Path(a.repo)
    try:
        if a.cmd == "prune":
            globs = a.glob or ([] if a.branch else [g.replace("{branch}", a.task_branch) for g in WO_PATTERNS + REPRO_PATTERNS])
            prune(repo, a.task_branch, a.base_branch, a.branch, globs, a.extra, a.dry_run)
        elif a.cmd == "pushed":
            pushed_local(repo)
        else:
            patterns = (a.wo_pattern or WO_PATTERNS) + (a.repro_pattern or REPRO_PATTERNS)
            root = Path(out(repo, "rev-parse", "--show-toplevel"))
            for f in sorted((root / ".tempo").glob("*/state.json")):
                s = json.loads(f.read_text(encoding="utf-8"))
                task = s.get("task_branch")
                if s.get("stage") != "DONE" or not task:
                    continue
                print(f"# {f.parent.name} {task}")
                globs = [g.replace("{branch}", task) for g in patterns]
                prune(repo, task, s.get("base_branch"), [], globs, [], a.dry_run)
    except RuntimeError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
