#!/usr/bin/env python3
"""TEMPO distill: carry session rules forward in .tempo/rules.md and clear finished session folders.

Standard library only, plus `gh` to read a PR's state. Only this script writes .tempo/rules.md
and only it deletes or archives a session folder.

Usage: tempo_distill.py <command> --repo R [args]
  list     [--json]                      every session folder under R/.tempo (a folder with state.json):
                                         ELIGIBLE <id> <reason> | SOURCES: <files to read for rules>
                                         KEPT <id> <reason>
                                         then TOTAL: <n> eligible, <n> kept
  apply    --task ID ... (--delete | --archive)
                                         checks every task again and refuses a KEPT one (exit 1, nothing
                                         changes); deletes the folders, or moves them to .tempo/archive/<id>.
                                         Clears the DUE mark, so `due` can suggest distill again later
  due      --threshold N [--mark]        DISTILL: DUE <n> finished sessions (exit 0) once ELIGIBLE reaches N,
                                         else DISTILL: NOT-DUE (also when N is 0, or the mark is set).
                                         --mark records that Jorge was told, so DUE prints once per pile
  rules    show                          .tempo/rules.md as numbered lines, or RULES: NONE
  rules    add --text T [--from ID]      appends one rule; DUPLICATE (exit 3) when a saved rule says the
                                         same words, TOO-LONG (exit 1) past 200 characters,
                                         FULL (exit 1) at 40 rules
  rules    drop N ...                    removes the numbered rules (from `rules show`)

Eligibility. A session is ELIGIBLE only when all of these hold:
  - its stage or status is DONE (a FAILED or ABORTED task never shipped and can be resumed);
  - it has a PR and gh says MERGED; or it has no PR and is a child (a slice ships with its parent's PR),
    a parent whose every child folder is eligible, or PLAN-ONLY (a plan delivered). An open PR,
    a PR closed without merge, and any other DONE task with no PR are KEPT;
  - git lists no linked worktree named after it (<id> or <id>-...);
  - it is not a child whose parent is under the same .tempo and KEPT, and no child under the same
    .tempo is KEPT (a parent and its slices go together).
Everything else is KEPT with the reason. gh missing or failing keeps the task.
Exit 0 ok, 1 error or refused, 3 duplicate rule.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

MAX_RULE = 200
MAX_RULES = 40
HEADER = ("# TEMPO rules\n"
          "Written by tempo_distill.py. Rules Jorge gave for every later task, one per line.\n"
          "The orchestrator reads this file at the start of every run. Edit it with `rules add` and `rules drop`.\n\n")
SOURCE_GLOBS = ("decisions.md", "esc-*.md", "task.md", "pr.md")
MARK = ".distill-due"


def tempo(repo):
    return Path(repo).resolve() / ".tempo"


def load(d):
    try:
        return json.loads((d / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def pr_state(repo, url):
    try:
        r = subprocess.run(["gh", "pr", "view", url, "--json", "state"], cwd=repo,
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"gh failed: {e}"
    if r.returncode:
        return None, f"gh pr view failed: {(r.stderr or r.stdout).strip().splitlines()[-1:] or ['?']}"
    try:
        return json.loads(r.stdout).get("state"), None
    except ValueError:
        return None, "gh gave no JSON"


def linked_worktrees(repo):
    """Paths of the repo's linked worktrees (git worktree list), wherever git.worktree_root puts them."""
    try:
        r = subprocess.run(["git", "-C", str(repo), "worktree", "list", "--porcelain"],
                           capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return []
    paths = [Path(line[9:]) for line in r.stdout.splitlines() if line.startswith("worktree ")]
    return paths[1:]  # the first is the main checkout


def own_verdict(repo, d, s, worktrees, depth=0):
    """(eligible, reason) from the task's own state, before parent and child links."""
    if s is None:
        return False, "no readable state.json"
    stage, status = s.get("stage"), s.get("status")
    if status in ("FAILED", "ABORTED"):
        return False, f"status {status}: never shipped, can be resumed"
    if stage != "DONE" and status != "DONE":
        return False, f"running: stage {stage}, status {status}"
    left = [w for w in worktrees if w.name == d.name or w.name.startswith(d.name + "-")]
    if left:
        return False, f"worktree still there: {left[0]}"
    pr = s.get("pr")
    if pr:
        state, err = pr_state(repo, pr)
        if err:
            return False, f"PR state unknown ({err})"
        if state == "MERGED":
            return True, "done, PR merged"
        if state == "CLOSED":
            return False, f"PR closed without merge: never shipped: {pr}"
        return False, f"PR still {state or 'unknown'}: {pr}"
    if s.get("parent"):
        return True, "done, ships with its parent"
    if s.get("children") and depth < 3:
        for name, ch in s["children"].items():
            cd = Path(ch.get("folder", ""))
            if not cd.is_dir():
                continue
            crepo = cd.parent.parent
            ok, why = own_verdict(crepo, cd, load(cd), linked_worktrees(crepo), depth + 1)
            if not ok:
                return False, f"child {name} is kept: {why}"
        return True, "done, every child shipped"
    if s.get("mode") == "PLAN-ONLY":
        return True, "done, plan delivered"
    return False, "done but no PR: never shipped"


def sessions(repo):
    """[(id, dir, eligible, reason)] for every folder under .tempo with a state.json, sorted by id."""
    root = tempo(repo)
    if not root.is_dir():
        return []
    dirs = sorted(e for e in root.iterdir() if e.is_dir() and (e / "state.json").exists())
    states = {d.name: load(d) for d in dirs}
    wts = linked_worktrees(repo)
    verdict = {d.name: own_verdict(repo, d, states[d.name], wts) for d in dirs}
    parent_of = {}
    for d in dirs:
        p = (states[d.name] or {}).get("parent")
        if p:
            pp = Path(p) if Path(p).is_absolute() else Path(repo).resolve() / p
            if pp.resolve().parent == root.resolve() and pp.name in verdict:
                parent_of[d.name] = pp.name
    changed = True
    while changed:  # a KEPT parent keeps its children, a KEPT child keeps its parent
        changed = False
        for child, parent in parent_of.items():
            for a, b, why in ((child, parent, f"parent {parent} is kept"), (parent, child, f"child {child} is kept")):
                if verdict[a][0] and not verdict[b][0]:
                    verdict[a] = (False, why)
                    changed = True
    return [(d.name, d, *verdict[d.name]) for d in dirs]


def sources(d):
    found = []
    for g in SOURCE_GLOBS:
        found += sorted(p.name for p in d.glob(g))
    return list(dict.fromkeys(found))


def cmd_list(repo, as_json):
    rows = sessions(repo)
    if as_json:
        print(json.dumps([{"id": i, "eligible": ok, "reason": why, "sources": sources(d) if ok else []}
                          for i, d, ok, why in rows], indent=2))
        return 0
    for i, d, ok, why in rows:
        if ok:
            print(f"ELIGIBLE {i} {why}")
            print(f"  SOURCES: {' '.join(str(d / f) for f in sources(d)) or 'NIL'}")
    for i, d, ok, why in rows:
        if not ok:
            print(f"KEPT {i} {why}")
    n = sum(1 for r in rows if r[2])
    print(f"TOTAL: {n} eligible, {len(rows) - n} kept")
    return 0


def cmd_apply(repo, tasks, archive):
    rows = {i: (d, ok, why) for i, d, ok, why in sessions(repo)}
    bad = [f"REFUSED {t}: {'no such session' if t not in rows else rows[t][2]}"
           for t in tasks if t not in rows or not rows[t][1]]
    if bad:
        print("\n".join(bad))
        print("Nothing was changed.")
        return 1
    root = tempo(repo)
    for t in dict.fromkeys(tasks):
        d = rows[t][0]
        if archive:
            dest = root / "archive" / t
            n = 2
            while dest.exists():
                dest = root / "archive" / f"{t}-{n}"
                n += 1
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(dest))
            print(f"ARCHIVED {t} -> {dest}")
        else:
            shutil.rmtree(d)
            print(f"DELETED {t}")
    (root / MARK).unlink(missing_ok=True)
    return 0


def cmd_due(repo, threshold, mark):
    root = tempo(repo)
    if mark:
        root.mkdir(parents=True, exist_ok=True)
        (root / MARK).write_text("suggested\n", encoding="utf-8")
        print("DISTILL: MARKED")
        return 0
    n = sum(1 for r in sessions(repo) if r[2]) if threshold > 0 and not (root / MARK).exists() else 0
    print(f"DISTILL: DUE {n} finished sessions" if threshold > 0 and n >= threshold else "DISTILL: NOT-DUE")
    return 0


RULE = re.compile(r"^- (.+?)(?:  \(from [^)]*\))?$")


def norm(text):
    return re.sub(r"[^\w]+", " ", text.casefold()).strip()


def read_rules(path):
    if not path.exists():
        return []
    return [m.group(0) for line in path.read_text(encoding="utf-8").splitlines() if (m := RULE.match(line))]


def write_rules(path, lines):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + "".join(line + "\n" for line in lines), encoding="utf-8")


def cmd_rules(repo, a):
    path = tempo(repo) / "rules.md"
    lines = read_rules(path)
    if a.action == "show":
        print("\n".join(f"{n}. {line[2:]}" for n, line in enumerate(lines, 1)) or "RULES: NONE")
        return 0
    if a.action == "add":
        text = " ".join(a.text.split()).lstrip("- ")
        if not text:
            print("EMPTY: give the rule text")
            return 1
        if len(text) > MAX_RULE:
            print(f"TOO-LONG: {len(text)} characters, at most {MAX_RULE}. Say it in one short sentence.")
            return 1
        for n, line in enumerate(lines, 1):
            if norm(RULE.match(line).group(1)) == norm(text):
                print(f"DUPLICATE: rule {n} already says it: {line[2:]}")
                return 3
        if len(lines) >= MAX_RULES:
            print(f"FULL: {MAX_RULES} rules saved. Drop or merge one first (`rules drop N`).")
            return 1
        line = f"- {text}" + (f"  (from {a.source})" if a.source else "")
        write_rules(path, lines + [line])
        print(f"ADDED {len(lines) + 1}. {line[2:]}")
        return 0
    drop = set(a.numbers)
    if not drop or any(n < 1 or n > len(lines) for n in drop):
        print(f"NO-SUCH-RULE: give numbers from 1 to {len(lines)}")
        return 1
    write_rules(path, [line for n, line in enumerate(lines, 1) if n not in drop])
    for n in sorted(drop):
        print(f"DROPPED {n}. {lines[n - 1][2:]}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--json", action="store_true")
    ap = sub.add_parser("apply")
    ap.add_argument("--task", action="append", required=True)
    how = ap.add_mutually_exclusive_group(required=True)
    how.add_argument("--delete", action="store_true")
    how.add_argument("--archive", action="store_true")
    du = sub.add_parser("due")
    du.add_argument("--threshold", type=int, default=0)
    du.add_argument("--mark", action="store_true")
    ru = sub.add_parser("rules")
    rs = ru.add_subparsers(dest="action", required=True)
    rs.add_parser("show")
    ra = rs.add_parser("add")
    ra.add_argument("--text", required=True)
    ra.add_argument("--from", dest="source")
    rd = rs.add_parser("drop")
    rd.add_argument("numbers", type=int, nargs="+")
    for sp in (ls, ap, du, ru):
        sp.add_argument("--repo", default=".")
    for sp in (rs.choices.values()):
        sp.add_argument("--repo", default=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.cmd == "list":
        return cmd_list(a.repo, a.json)
    if a.cmd == "apply":
        return cmd_apply(a.repo, a.task, a.archive)
    if a.cmd == "due":
        return cmd_due(a.repo, a.threshold, a.mark)
    return cmd_rules(a.repo, a)


if __name__ == "__main__":
    sys.exit(main())
