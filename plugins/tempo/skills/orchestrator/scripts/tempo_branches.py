#!/usr/bin/env python3
"""TEMPO branches: delete local work-order and repro branches once the task branch holds their work,
and the task branch itself once its PR merged.

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

`shipped` deletes the task branch after its PR merged. A squash or rebase merge leaves
its commits outside the base branch, so no ancestry check can prove it; the PR can.
It deletes with `-D` only when the PR (read with `gh pr view`) is MERGED, its head
branch is this branch, the local tip equals the PR's headRefOid, every remote copy of
the branch is gone or at that same commit, and no worktree has it checked out.

Usage: tempo_branches.py <command> [args]
  prune  --repo R --task-branch B [--base-branch X] [--branch NAME ...] [--glob PATTERN ...]
         [--from SHA ...] [--dry-run]
         check and delete the named branches and the ones matching the globs
         (default globs: tempo/N-wo-*, tempo/N-repro with N = B without its type word, the 0.14
         tempo/B-wo-*, tempo/B-repro, and the pre-0.14 B-wo-*, B-repro; --glob takes {branch}, {name})
  sweep  --repo R [--wo-pattern P ...] [--repro-pattern P ...] [--dry-run]
         prune for every task in R/.tempo/ whose stage is DONE; patterns take {branch} and {name}
         (defaults: the globs above); then shipped for the task branch when the state has a pr
  shipped --repo R --branch B [--pr URL|NUMBER] [--dry-run]
         delete the task branch B when its PR (default: the PR gh finds for B) merged with B's tip
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

if sys.platform == "win32":  # the console code page cannot carry every character a task or a hook holds
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")


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


def pr_view(repo, pr):
    try:
        r = subprocess.run(["gh", "pr", "view", pr, "--json", "state,headRefOid,headRefName"], cwd=repo,
                           capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)
    if r.returncode != 0:
        return None, r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"exit {r.returncode}"
    return json.loads(r.stdout), None


def shipped(repo, branch, pr, dry):
    tip = sha(repo, f"refs/heads/{branch}")
    if tip is None:
        print(f"SKIPPED {branch} (branch not found)")
        return
    if branch in checked_out(repo):
        print(f"KEPT {branch} (checked out in a worktree)")
        return
    data, err = pr_view(repo, pr or branch)
    if err:
        print(f"KEPT {branch} (gh pr view failed: {err})")
        return
    head = data.get("headRefOid") or ""
    if data.get("state") != "MERGED":
        print(f"KEPT {branch} (PR {str(data.get('state')).lower()}, not merged)")
    elif data.get("headRefName") != branch:
        print(f"KEPT {branch} (the PR's head branch is {data.get('headRefName')})")
    elif tip != head:
        n = out(repo, "rev-list", "--count", tip, f"^{head}") if sha(repo, head) else "unknown"
        print(f"KEPT {branch} (local tip {tip[:10]} is not the PR head {head[:10]}; {n} commits not in the PR)")
    elif any(sha(repo, r) != head for r in out(repo, "for-each-ref", "--format=%(refname)", "refs/remotes").splitlines()
             if r.count("/") >= 3 and r.split("/", 3)[-1] == branch):
        print(f"KEPT {branch} (a remote copy is not at the PR head)")
    elif dry:
        print(f"WOULD-DELETE {branch} {tip[:10]} (shipped)")
    elif sha(repo, f"refs/heads/{branch}") != tip:
        print(f"KEPT {branch} (moved while checking)")
    else:
        git(repo, "branch", "-D", branch)
        print(f"DELETED {branch} {tip[:10]} (shipped)")


# tempo/{name} since 0.15.0 ({name}: the task branch without its type word), tempo/{branch} in 0.14.0,
# <task>-wo-NN before that.
WO_PATTERNS = ["tempo/{name}-wo-*", "tempo/{branch}-wo-*", "{branch}-wo-*"]
REPRO_PATTERNS = ["tempo/{name}-repro", "tempo/{branch}-repro", "{branch}-repro"]


def fill(pattern, task):
    name = task.split("/", 1)[1] if "/" in task else task
    return pattern.replace("{branch}", task).replace("{name}", name)
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
    sh = sp.add_parser("shipped")
    sh.add_argument("--repo", default=".")
    sh.add_argument("--branch", required=True)
    sh.add_argument("--pr")
    sh.add_argument("--dry-run", action="store_true")
    pu = sp.add_parser("pushed")
    pu.add_argument("--repo", default=".")
    a = p.parse_args()
    repo = Path(a.repo)
    try:
        if a.cmd == "prune":
            globs = [fill(g, a.task_branch) for g in a.glob] or ([] if a.branch else [fill(g, a.task_branch) for g in WO_PATTERNS + REPRO_PATTERNS])
            prune(repo, a.task_branch, a.base_branch, a.branch, globs, a.extra, a.dry_run)
        elif a.cmd == "shipped":
            shipped(repo, a.branch, a.pr, a.dry_run)
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
                globs = list(dict.fromkeys(fill(g, task) for g in patterns))
                prune(repo, task, s.get("base_branch"), [], globs, [], a.dry_run)
                if s.get("pr"):
                    shipped(repo, task, s["pr"], a.dry_run)
    except RuntimeError as e:
        print(f"ERROR {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
