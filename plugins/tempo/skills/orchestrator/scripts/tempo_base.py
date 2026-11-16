#!/usr/bin/env python3
"""TEMPO base: bring the local base branch up to its remote before a task reads or builds on it.

On 2026-11-03 a /tempo:plan run in xipp explored and planned on a local `develop`
that was 51 commits behind origin/develop. Nothing fetched first, so the whole plan
was done against month-old code and had to be thrown away. Every TEMPO command now
runs `sync` on each repo it works in before triage reads any code.

`sync` fetches the base branch from its remote and fast-forwards the local branch:
  - not checked out anywhere: the ref moves (`git update-ref`, old value checked)
  - checked out in a worktree: `git merge --ff-only` there; git refuses when local
    changes would be overwritten, and then the script stops instead
It never merges, rebases, resets, stashes or pushes. Anything that is not a clean
fast-forward stops the run with the reason:
  - the fetch fails (network, auth, unknown branch)
  - the local branch has commits the remote lacks (ahead or diverged)
  - the checkout that holds the branch cannot fast-forward
With no remote at all the local branch is used as it is (a local-only repo).
`--offline` skips the fetch on purpose and says how far behind the last-known
remote ref the branch is.

It also reports where the repo's own checkout stands, because scouts read files
from it: CHECKOUT says whether that working tree is the base head.

Usage: tempo_base.py sync --repo R --branch B [--remote NAME] [--offline] [--timeout SEC]
Prints:
  BASE: OK <branch> <sha> (up to date | no remote | offline, ...)
  BASE: UPDATED <branch> <old>..<new> (<n> commits, ...)
  BASE: STOP <branch> <reason>
  CHECKOUT: BASE <path>                      the repo checkout is the base head
  CHECKOUT: OTHER <path> <branch|detached> <sha>   it is not: read the base elsewhere
  HEAD: <full sha>                           the base commit to record (not on STOP)
Exit 0 OK or UPDATED, 2 STOP, 1 usage or unexpected git error.
"""
import argparse
import subprocess
import sys

if sys.platform == "win32":  # the console code page cannot carry every character a task or a hook holds
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")


def git(repo, *args, timeout=60, check=True):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, timeout=timeout)
    if check and p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {(p.stderr or p.stdout).strip()}")
    return p


def rev(repo, ref):
    p = git(repo, "rev-parse", "--verify", "--quiet", ref + "^{commit}", check=False)
    return p.stdout.strip() if p.returncode == 0 else None


def count(repo, a, b):
    return int(git(repo, "rev-list", "--count", f"{a}..{b}").stdout.strip() or 0)


def worktrees(repo):
    """[(path, branch ref or None, head sha)] for every worktree of the repo."""
    out, cur = [], {}
    for line in git(repo, "worktree", "list", "--porcelain").stdout.splitlines() + [""]:
        if not line:
            if cur:
                out.append((cur.get("worktree"), cur.get("branch"), cur.get("HEAD")))
            cur = {}
            continue
        k, _, v = line.partition(" ")
        cur[k] = v
    return out


def pick_remote(repo, branch, wanted):
    if wanted:
        return wanted
    p = git(repo, "config", "--get", f"branch.{branch}.remote", check=False)
    if p.returncode == 0 and p.stdout.strip() and p.stdout.strip() != ".":
        return p.stdout.strip()
    remotes = git(repo, "remote").stdout.split()
    if "origin" in remotes:
        return "origin"
    return remotes[0] if len(remotes) == 1 else None


def stop(branch, reason):
    print(f"BASE: STOP {branch} {reason}")
    return 2


def checkout_line(repo, head):
    top = git(repo, "rev-parse", "--show-toplevel").stdout.strip()
    sha = git(repo, "rev-parse", "HEAD", check=False).stdout.strip()
    name = git(repo, "symbolic-ref", "--short", "-q", "HEAD", check=False).stdout.strip() or "detached"
    if sha == head:
        print(f"CHECKOUT: BASE {top}")
    else:
        print(f"CHECKOUT: OTHER {top} {name} {sha[:10]}")


def sync(a):
    repo, branch = a.repo, a.branch
    if git(repo, "rev-parse", "--git-dir", check=False).returncode != 0:
        print(f"not a git repository: {repo}", file=sys.stderr)
        return 1
    remote = pick_remote(repo, branch, a.remote)
    local = rev(repo, f"refs/heads/{branch}")
    if remote is None:
        if local is None:
            return stop(branch, "no such local branch and no remote to fetch it from")
        print(f"BASE: OK {branch} {local[:10]} (no remote; local branch used as it is)")
        checkout_line(repo, local)
        print(f"HEAD: {local}")
        return 0
    rref = f"refs/remotes/{remote}/{branch}"
    if a.offline:
        known = rev(repo, rref)
        base = local or known
        if base is None:
            return stop(branch, f"--offline and neither {branch} nor {remote}/{branch} exists locally")
        note = "offline, not fetched"
        if local and known and local != known:
            note += f"; {count(repo, local, known)} behind and {count(repo, known, local)} ahead of the last-fetched {remote}/{branch}"
        print(f"BASE: OK {branch} {base[:10]} ({note})")
        checkout_line(repo, base)
        print(f"HEAD: {base}")
        return 0
    try:
        p = git(repo, "fetch", "--quiet", remote, f"+refs/heads/{branch}:{rref}", timeout=a.timeout, check=False)
    except subprocess.TimeoutExpired:
        return stop(branch, f"git fetch {remote} {branch} timed out after {a.timeout}s; check the network, "
                            f"or rerun with --offline to plan on the local {branch} as it is")
    if p.returncode != 0:
        err = " ".join((p.stderr or p.stdout).split())[:300]
        return stop(branch, f"git fetch {remote} {branch} failed: {err}")
    theirs = rev(repo, rref)
    if theirs is None:
        return stop(branch, f"{remote}/{branch} not found after fetch")
    if local is None:
        git(repo, "branch", "--quiet", "--track", branch, f"{remote}/{branch}")
        print(f"BASE: UPDATED {branch} NIL..{theirs[:10]} (created from {remote}/{branch})")
        checkout_line(repo, theirs)
        print(f"HEAD: {theirs}")
        return 0
    if local == theirs:
        print(f"BASE: OK {branch} {local[:10]} (up to date with {remote}/{branch})")
        checkout_line(repo, local)
        print(f"HEAD: {local}")
        return 0
    ahead, behind = count(repo, theirs, local), count(repo, local, theirs)
    if ahead and behind:
        return stop(branch, f"diverged from {remote}/{branch}: {ahead} local commits not on the remote, "
                            f"{behind} remote commits not local. Push or drop the local commits, then run again")
    if ahead:
        return stop(branch, f"{ahead} commits ahead of {remote}/{branch} (not pushed). A PR against "
                            f"{remote}/{branch} would carry them. Push or drop them, then run again")
    holders = [w for w in worktrees(repo) if w[1] == f"refs/heads/{branch}"]
    if holders:
        path = holders[0][0]
        p = git(path, "merge", "--ff-only", "--quiet", rref, check=False, timeout=a.timeout)
        if p.returncode != 0:
            err = " ".join((p.stderr or p.stdout).split())[:300]
            return stop(branch, f"{behind} behind {remote}/{branch}, and the checkout at {path} cannot "
                                f"fast-forward: {err}. Commit or stash there, then run again")
        how = f"fast-forwarded the checkout at {path}"
    else:
        git(repo, "update-ref", f"refs/heads/{branch}", theirs, local)
        how = "branch ref moved; not checked out"
    print(f"BASE: UPDATED {branch} {local[:10]}..{theirs[:10]} ({behind} commits, {how})")
    checkout_line(repo, theirs)
    print(f"HEAD: {theirs}")
    return 0


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sync")
    s.add_argument("--repo", required=True)
    s.add_argument("--branch", required=True)
    s.add_argument("--remote")
    s.add_argument("--offline", action="store_true")
    s.add_argument("--timeout", type=int, default=90)
    a = ap.parse_args()
    try:
        return sync(a)
    except (RuntimeError, subprocess.TimeoutExpired) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
