#!/usr/bin/env python3
"""TEMPO distill: carry session rules forward in .tempo/rules.md and clear finished session folders.

Standard library only, plus `gh` to read a PR's state. Only this script writes .tempo/rules.md
and only it deletes or archives a session folder.

Usage: tempo_distill.py <command> --repo R [args]
  list     [--abandoned-after D] [--json]
                                         every session folder under R/.tempo (a folder with state.json):
                                         ELIGIBLE <id> <reason> | SOURCES: <files to read for rules>
                                         ABANDONED <id> <reason> | SOURCES: ...   (only with D above 0)
                                         KEPT <id> <reason>
                                         then TOTAL: <n> eligible, <n> abandoned, <n> kept
  apply    --task ID ... [--abandoned ID ... --abandoned-after D] (--delete | --archive)
                                         checks every task again and refuses the whole call (exit 1, nothing
                                         changes) when a --task is not ELIGIBLE, or an --abandoned is KEPT
                                         (--abandoned needs --archive: it is never deleted);
                                         deletes the folders, or moves them to .tempo/archive/<id> with an
                                         .archived stamp, and removes their task-registry records
                                         (~/.cache/tempo/tasks, see tempo_procs.py). Clears the DUE mark, so
                                         `due` can suggest distill again
  archive  --days N [--delete NAME ...]  OLD <name> <age>d for each folder under .tempo/archive/ archived N
                                         or more days ago, then TOTAL: <n> archived, <n> older than N days.
                                         N 0 prints ARCHIVE: PRUNING-OFF. --delete removes the named folders,
                                         and refuses the whole call when one is not OLD
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
Abandoned. With --abandoned-after D above 0, a session that never shipped and that nothing has written
for D days is ABANDONED instead of KEPT: FAILED or ABORTED, its PR closed without merge, or DONE with no PR.
It still needs no linked worktree, and it goes with its parent and slices (KEPT beats ABANDONED beats
ELIGIBLE). A running task, an open PR and a PR state gh cannot read are KEPT at any age.
Everything else is KEPT with the reason. gh missing or failing keeps the task.
Exit 0 ok, 1 error or refused, 3 duplicate rule.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

MAX_RULE = 200
MAX_RULES = 40
HEADER = ("# TEMPO rules\n"
          "Written by tempo_distill.py. Rules Jorge gave for every later task, one per line.\n"
          "The orchestrator reads this file at the start of every run. Edit it with `rules add` and `rules drop`.\n\n")
SOURCE_GLOBS = ("decisions.md", "esc-*.md", "task.md", "pr.md")
MARK = ".distill-due"
STAMP = ".archived"
DAY = 86400
RANK = {"ELIGIBLE": 0, "ABANDONED": 1, "KEPT": 2}


def registry_dir():
    """tempo_procs.py's task registry: <TEMPO_CACHE or ~/.cache/tempo>/tasks/<tag>.json, each {"dir": ...}."""
    return Path(os.environ.get("TEMPO_CACHE") or Path.home() / ".cache" / "tempo") / "tasks"


def unregister(folder):
    """Remove every registry record that points at `folder` or inside it. Returns how many. Never raises."""
    folder = Path(folder).resolve()
    reg, n = registry_dir(), 0
    for f in (reg.glob("*.json") if reg.is_dir() else []):
        try:
            d = Path(json.loads(f.read_text(encoding="utf-8"))["dir"]).resolve()
            if d == folder or folder in d.parents:
                f.unlink()
                n += 1
        except (OSError, ValueError, KeyError, TypeError):
            continue
    return n


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


def newest_write(d):
    """Seconds since the epoch of the last write to any file in folder d (the folder itself if empty)."""
    times = [d.stat().st_mtime]
    for root, _, files in os.walk(d):
        for f in files:
            try:
                times.append((Path(root) / f).stat().st_mtime)
            except OSError:
                continue
    return max(times)


def idle_days(d):
    return int((time.time() - newest_write(d)) // DAY)


def own_verdict(repo, d, s, worktrees, abandon_days=0, depth=0):
    """(verdict, reason) from the task's own state, before parent and child links.
    verdict is ELIGIBLE, ABANDONED or KEPT."""
    if s is None:
        return "KEPT", "no readable state.json"
    stage, status = s.get("stage"), s.get("status")
    unshipped = None  # the reason, when the task ended without shipping
    if status in ("FAILED", "ABORTED"):
        unshipped = f"status {status}: never shipped, can be resumed"
    elif stage != "DONE" and status != "DONE":
        return "KEPT", f"running: stage {stage}, status {status}"
    left = [w for w in worktrees if w.name == d.name or w.name.startswith(d.name + "-")]
    if left:
        return "KEPT", f"worktree still there: {left[0]}"
    if unshipped is None:
        pr = s.get("pr")
        if pr:
            state, err = pr_state(repo, pr)
            if err:
                return "KEPT", f"PR state unknown ({err})"
            if state == "MERGED":
                return "ELIGIBLE", "done, PR merged"
            if state != "CLOSED":
                return "KEPT", f"PR still {state or 'unknown'}: {pr}"
            unshipped = f"PR closed without merge: never shipped: {pr}"
        elif s.get("parent"):
            return "ELIGIBLE", "done, ships with its parent"
        elif s.get("children") and depth < 3:
            worst = ("ELIGIBLE", "done, every child shipped")
            for name, ch in s["children"].items():
                cd = Path(ch.get("folder", ""))
                if not cd.is_dir():
                    continue
                crepo = cd.parent.parent
                v, why = own_verdict(crepo, cd, load(cd), linked_worktrees(crepo), abandon_days, depth + 1)
                if RANK[v] > RANK[worst[0]]:
                    worst = (v, f"child {name} is {v.lower()}: {why}")
            return worst
        elif s.get("mode") == "PLAN-ONLY":
            return "ELIGIBLE", "done, plan delivered"
        else:
            unshipped = "done but no PR: never shipped"
    idle = idle_days(d)
    if abandon_days > 0 and idle >= abandon_days:
        return "ABANDONED", f"{unshipped}; idle {idle} days"
    return "KEPT", unshipped


def sessions(repo, abandon_days=0):
    """[(id, dir, verdict, reason)] for every folder under .tempo with a state.json, sorted by id.
    verdict is ELIGIBLE, ABANDONED (only when abandon_days is above 0) or KEPT."""
    root = tempo(repo)
    if not root.is_dir():
        return []
    dirs = sorted(e for e in root.iterdir() if e.is_dir() and (e / "state.json").exists())
    states = {d.name: load(d) for d in dirs}
    wts = linked_worktrees(repo)
    verdict = {d.name: own_verdict(repo, d, states[d.name], wts, abandon_days) for d in dirs}
    parent_of = {}
    for d in dirs:
        p = (states[d.name] or {}).get("parent")
        if p:
            pp = Path(p) if Path(p).is_absolute() else Path(repo).resolve() / p
            if pp.resolve().parent == root.resolve() and pp.name in verdict:
                parent_of[d.name] = pp.name
    changed = True
    while changed:  # a parent and its slices take the worst verdict of the group: KEPT, then ABANDONED
        changed = False
        for child, parent in parent_of.items():
            for a, b, who in ((child, parent, f"parent {parent}"), (parent, child, f"child {child}")):
                v = verdict[b][0]
                if RANK[verdict[a][0]] < RANK[v]:
                    verdict[a] = (v, f"{who} is {v.lower()}")
                    changed = True
    return [(d.name, d, *verdict[d.name]) for d in dirs]


def sources(d):
    found = []
    for g in SOURCE_GLOBS:
        found += sorted(p.name for p in d.glob(g))
    return list(dict.fromkeys(found))


def cmd_list(repo, abandon_days, as_json):
    rows = sessions(repo, abandon_days)
    if as_json:
        print(json.dumps([{"id": i, "verdict": v, "eligible": v == "ELIGIBLE", "reason": why,
                           "sources": sources(d) if v != "KEPT" else []}
                          for i, d, v, why in rows], indent=2))
        return 0
    for kind in ("ELIGIBLE", "ABANDONED", "KEPT"):
        for i, d, v, why in rows:
            if v == kind:
                print(f"{v} {i} {why}")
                if v != "KEPT":
                    print(f"  SOURCES: {' '.join(str(d / f) for f in sources(d)) or 'NIL'}")
    n = {k: sum(1 for r in rows if r[2] == k) for k in RANK}
    print(f"TOTAL: {n['ELIGIBLE']} eligible, {n['ABANDONED']} abandoned, {n['KEPT']} kept")
    return 0


def cmd_apply(repo, tasks, abandoned, abandon_days, archive):
    if abandoned and (abandon_days <= 0 or not archive):
        print("REFUSED: --abandoned needs --abandoned-after D above 0 (distill.abandoned_after_days) and --archive:"
              " an abandoned session can still be resumed, so it is archived, never deleted")
        print("Nothing was changed.")
        return 1
    rows = {i: (d, v, why) for i, d, v, why in sessions(repo, abandon_days if abandoned else 0)}
    bad = []
    for t, allowed in [(t, ("ELIGIBLE",)) for t in tasks] + [(t, ("ELIGIBLE", "ABANDONED")) for t in abandoned]:
        if t not in rows:
            bad.append(f"REFUSED {t}: no such session")
        elif rows[t][1] not in allowed:
            why = rows[t][2] + (" (abandoned: pass it with --abandoned)" if rows[t][1] == "ABANDONED" else "")
            bad.append(f"REFUSED {t}: {why}")
    if bad:
        print("\n".join(bad))
        print("Nothing was changed.")
        return 1
    root = tempo(repo)
    for t in dict.fromkeys(tasks + abandoned):
        d = rows[t][0]
        unregister(d)  # the tag is the folder's path: a moved or deleted folder leaves its record stale
        if archive:
            dest = root / "archive" / t
            n = 2
            while dest.exists():
                dest = root / "archive" / f"{t}-{n}"
                n += 1
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(d), str(dest))
            (dest / STAMP).write_text(datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") + "\n",
                                      encoding="utf-8")
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
    n = sum(1 for r in sessions(repo) if r[2] == "ELIGIBLE") if threshold > 0 and not (root / MARK).exists() else 0
    print(f"DISTILL: DUE {n} finished sessions" if threshold > 0 and n >= threshold else "DISTILL: NOT-DUE")
    return 0


def archived_at(d):
    """When folder d moved to the archive: its .archived stamp, else its last write (archived before 0.33.0)."""
    try:
        text = (d / STAMP).read_text(encoding="utf-8").strip()
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc).timestamp()
    except (OSError, ValueError):
        return newest_write(d)


def old_archives(repo, days):
    """([(name, age in days)] older than days, how many archived folders there are)."""
    root = tempo(repo) / "archive"
    dirs = sorted(e for e in root.iterdir() if e.is_dir()) if root.is_dir() else []
    ages = [(d.name, int((time.time() - archived_at(d)) // DAY)) for d in dirs]
    return [(n, a) for n, a in ages if a >= days], len(dirs)


def cmd_archive(repo, days, delete):
    if days <= 0:
        print("ARCHIVE: PRUNING-OFF (distill.archive_days is 0)")
        if delete:
            print("REFUSED: nothing is deleted while pruning is off")
            return 1
        return 0
    old, total = old_archives(repo, days)
    if delete:
        names, bad = dict(old), []
        for n in delete:
            if n not in names:  # only plain folder names under archive/ are ever in `old`
                where = tempo(repo) / "archive" / n
                plain = "/" not in n and n not in (".", "..")
                why = "not in .tempo/archive" if not plain or not where.is_dir() else f"archived under {days} days ago"
                bad.append(f"REFUSED {n}: {why}")
        if bad:
            print("\n".join(bad))
            print("Nothing was changed.")
            return 1
        for n in dict.fromkeys(delete):
            shutil.rmtree(tempo(repo) / "archive" / n)
            print(f"DELETED archive/{n}")
        return 0
    for n, a in old:
        print(f"OLD {n} {a}d")
    print(f"TOTAL: {total} archived, {len(old)} older than {days} days")
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
    ls.add_argument("--abandoned-after", type=int, default=0, metavar="DAYS")
    ap = sub.add_parser("apply")
    ap.add_argument("--task", action="append", default=[])
    ap.add_argument("--abandoned", action="append", default=[], metavar="ID")
    ap.add_argument("--abandoned-after", type=int, default=0, metavar="DAYS")
    how = ap.add_mutually_exclusive_group(required=True)
    how.add_argument("--delete", action="store_true")
    how.add_argument("--archive", action="store_true")
    ar = sub.add_parser("archive")
    ar.add_argument("--days", type=int, required=True)
    ar.add_argument("--delete", nargs="+", default=[], metavar="NAME")
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
    for sp in (ls, ap, ar, du, ru):
        sp.add_argument("--repo", default=".")
    for sp in (rs.choices.values()):
        sp.add_argument("--repo", default=argparse.SUPPRESS)
    a = p.parse_args(argv)
    if a.cmd == "list":
        return cmd_list(a.repo, a.abandoned_after, a.json)
    if a.cmd == "apply":
        if not a.task and not a.abandoned:
            p.error("apply needs --task or --abandoned")
        return cmd_apply(a.repo, a.task, a.abandoned, a.abandoned_after, a.archive)
    if a.cmd == "archive":
        return cmd_archive(a.repo, a.days, a.delete)
    if a.cmd == "due":
        return cmd_due(a.repo, a.threshold, a.mark)
    return cmd_rules(a.repo, a)


if __name__ == "__main__":
    sys.exit(main())
