#!/usr/bin/env python3
"""TEMPO task state: the only writer of .tempo/<task-id>/state.json and state.md.

state.json is the source of truth. state.md is rendered from it after every
change, in the ICAO layout of the state template, for Jorge and /tempo:resume.
Times come from this machine's clock, never from the caller.

Usage: tempo_state.py <command> <task-dir> [args]
  init      <dir> --task ID --flow FEATURE|BUG|WORKSPACE --title T --base-branch B --base-commit H
            [--task-branch NAME] [--mode FULL|PLAN-ONLY] [--parent DIR] [--review-limit N] [--qa-limit N]
  set       <dir> [--lane L] [--stage S] [--status S] [--next TEXT] [--mode M] [--title T]
            [--task-branch B] [--base-commit H] [--pr URL]
  log       <dir> STAGE ARTIFACT PASS|FAIL|BLOCKED
  bump      <dir> review|qa|reissue
  wo        <dir> WO-NN [--worktree P] [--branch B] [--status S]
  wait      <dir> ESC-FILE | --clear
  agent     <dir> start ID --label L --output PATH [--prompt FILE]
  agent     <dir> done ID
  child     <dir> REPO --folder DIR            (register a per-repo child task of a workspace task)
  tracker   <dir>                              (refresh children from their state.json, write tracker.md)
  show      <dir> [--json]
  adopt     <dir>                              (build state.json from a hand-written state.md)
Exit 0 ok, 1 error.
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

STAGES = ["TRIAGE", "EXPLORE", "INVESTIGATE", "REPRODUCE", "ROOT-CAUSE", "SPEC", "HANDOFF", "PLAN",
          "PLANNED", "BUILD", "INTEGRATE", "REVIEW", "QA", "SHIP", "REPOS", "JOINT-QA", "DONE"]
STATUSES = ["RUNNING", "WAITING-ON-JORGE", "FAILED", "DONE"]
RESULTS = ["PASS", "FAIL", "BLOCKED"]
WO_STATUSES = ["ISSUED", "READBACK OK", "BUILDING", "DONE", "BLOCKED"]


def now():
    return dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def load(d):
    p = Path(d) / "state.json"
    if not p.is_file():
        sys.exit(f"tempo_state: {p} not found. Run `init`, or `adopt` for a task started before v0.3.0.")
    return json.loads(p.read_text(encoding="utf-8"))


def save(d, s):
    d = Path(d)
    (d / "state.json").write_text(json.dumps(s, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (d / "state.md").write_text(render(s), encoding="utf-8")


def head(left, right, width=50):
    return left.ljust(width) + right


def render(s):
    L = []
    L.append(head("TASK STATE", s["task"]))
    L.append(f"FLOW: {s['flow']}          LANE: {s.get('lane') or 'TBD'}          OWNER: orchestrator")
    L.append(f"MODE: {s.get('mode', 'FULL')}")
    L.append("")

    def section(n, title, items):
        sep = "   " if n < 10 else "  "
        L.append(f"{n}{sep}{title}")
        if not items:
            items = ["NIL"]
        for i, text in enumerate(items, 1):
            num = f"{n}.{i}"
            L.append(f"{num}{' ' * max(2, 6 - len(num))}{text}")
        L.append("")

    section(1, "TASK", [
        f"{s['title'].rstrip('.')}.",
        f"Started: {s['started']}.",
        f"Base branch: {s['base_branch']} at {s['base_commit']}.",
        f"Task branch: {s.get('task_branch') or 'NIL'}.",
        f"Parent: {s.get('parent') or 'NIL'}.",
    ] + ([f"Pull request: {s['pr']}."] if s.get("pr") else []))
    section(2, "DEFINITIONS", [])
    section(3, "STAGE", [f"Current: {s['stage']}.", f"Status: {s['status']}."])
    section(4, "STAGE LOG", [f"{t} | {st} | {a} | {r}" for t, st, a, r in s["log"]])
    c = s["counters"]
    section(5, "LOOP COUNTERS", [f"Review rounds: {c['review']} of {c['review_limit']}.",
                                 f"QA rounds: {c['qa']} of {c['qa_limit']}.",
                                 f"Document re-issues: {c['reissue']}."])
    section(6, "WORK ORDERS", [f"{k} | {v.get('worktree') or 'TBD'} | {v.get('branch') or 'TBD'} | {v.get('status') or 'ISSUED'}"
                               for k, v in sorted(s["work_orders"].items())])
    section(7, "WAITING ON JORGE", [s["waiting"]] if s.get("waiting") else [])
    section(8, "NEXT ACTION", [s["next"].rstrip(".") + "."] if s.get("next") else [])
    section(9, "AGENTS IN FLIGHT", [f"{k} | {v['label']} | {v['output']} | {v.get('prompt') or 'NIL'} | started {v['started']}"
                                    for k, v in s["agents"].items()])
    section(10, "CHILD TASKS", [f"{k} | {v['folder']} | {v.get('stage') or 'TBD'} | {v.get('status') or 'TBD'} | {v.get('pr') or 'NIL'}"
                                for k, v in s["children"].items()])
    return "\n".join(L).rstrip() + "\n"


def tracker(d, s):
    rows = ["# Tracker " + s["task"], "", f"Generated {now()} by tempo_state.py from each child's state.json. Do not edit.", "",
            "| Repo | Stage | Status | Pull request | Next action |", "|---|---|---|---|---|"]
    for repo, ch in s["children"].items():
        f = Path(ch["folder"]) / "state.json"
        if f.is_file():
            cs = json.loads(f.read_text(encoding="utf-8"))
        elif (Path(ch["folder"]) / "state.md").is_file():
            cs = adopt(ch["folder"])  # task from before 0.3.0: read its state.md, write nothing
        else:
            cs = None
        if cs:
            ch.update(stage=cs["stage"], status=cs["status"], pr=cs.get("pr"), next=cs.get("next"))
        rows.append(f"| {repo} | {ch.get('stage') or 'NOT STARTED'} | {ch.get('status') or '-'} | {ch.get('pr') or '-'} | {ch.get('next') or '-'} |")
    (Path(d) / "tracker.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


def adopt(d):
    text = (Path(d) / "state.md").read_text(encoding="utf-8")
    def grab(pat, default=None):
        m = re.search(pat, text, re.M)
        return m.group(1).strip() if m else default
    s = new_state(task=grab(r"^TASK STATE\s+(\S+)", Path(d).name), flow=grab(r"^FLOW:\s*(\S+)", "FEATURE"),
                  title=grab(r"^1\.1\s+(.*?)\.?$", "Task"), base_branch=grab(r"Base branch:\s*(\S+) at", "NIL"),
                  base_commit=grab(r"Base branch:\s*\S+ at\s*([0-9a-f]+)", "NIL"))
    s["started"] = grab(r"Started:\s*(.*?)\.?$", now())
    s["lane"] = grab(r"LANE:\s*(\S+)")
    s["stage"] = grab(r"Current:\s*([A-Z-]+)", "TRIAGE")
    s["status"] = grab(r"Status:\s*([A-Z-]+)", "RUNNING")
    s["log"] = [list(map(str.strip, m.group(1).split("|"))) for m in re.finditer(r"^4\.\d+\s+(\d{4}-.*)$", text, re.M)]
    s["log"] = [x for x in s["log"] if len(x) == 4]
    m = re.search(r"Review rounds:\s*(\d+) of (\d+)", text)
    if m: s["counters"].update(review=int(m.group(1)), review_limit=int(m.group(2)))
    m = re.search(r"QA rounds:\s*(\d+) of (\d+)", text)
    if m: s["counters"].update(qa=int(m.group(1)), qa_limit=int(m.group(2)))
    for m in re.finditer(r"^6\.\d+\s+(WO-\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*$", text, re.M):
        s["work_orders"][m.group(1)] = {"worktree": m.group(2), "branch": m.group(3), "status": m.group(4)}
    nxt = grab(r"^8\.1\s+(.*)$")
    s["next"] = None if nxt in (None, "NIL") else nxt
    w = grab(r"^7\.1\s+(.*)$")
    s["waiting"] = None if w in (None, "NIL") else w
    return s


def new_state(task, flow, title, base_branch, base_commit, task_branch=None, mode="FULL", parent=None,
              review_limit=3, qa_limit=3):
    return {"version": 1, "task": task, "flow": flow, "lane": None, "mode": mode, "title": title,
            "started": now(), "base_branch": base_branch, "base_commit": base_commit,
            "task_branch": task_branch, "parent": parent, "pr": None, "stage": "TRIAGE", "status": "RUNNING",
            "log": [], "counters": {"review": 0, "review_limit": review_limit, "qa": 0, "qa_limit": qa_limit, "reissue": 0},
            "work_orders": {}, "waiting": None, "next": None, "agents": {}, "children": {}}


def main(argv=None):
    p = argparse.ArgumentParser(prog="tempo_state.py", description="TEMPO task state")
    sp = p.add_subparsers(dest="cmd", required=True)
    i = sp.add_parser("init"); i.add_argument("dir")
    for a in ("--task", "--title", "--base-branch", "--base-commit"):
        i.add_argument(a, required=True)
    i.add_argument("--flow", required=True, choices=["FEATURE", "BUG", "WORKSPACE"])
    i.add_argument("--mode", default="FULL", choices=["FULL", "PLAN-ONLY"])
    i.add_argument("--task-branch"); i.add_argument("--parent")
    i.add_argument("--review-limit", type=int, default=3); i.add_argument("--qa-limit", type=int, default=3)
    s_ = sp.add_parser("set"); s_.add_argument("dir")
    s_.add_argument("--lane", choices=["S", "M", "L", "TBD"]); s_.add_argument("--stage", choices=STAGES)
    s_.add_argument("--status", choices=STATUSES); s_.add_argument("--next"); s_.add_argument("--mode", choices=["FULL", "PLAN-ONLY"])
    s_.add_argument("--title"); s_.add_argument("--task-branch"); s_.add_argument("--base-commit"); s_.add_argument("--pr")
    l = sp.add_parser("log"); l.add_argument("dir"); l.add_argument("stage", choices=STAGES); l.add_argument("artifact"); l.add_argument("result", choices=RESULTS)
    b = sp.add_parser("bump"); b.add_argument("dir"); b.add_argument("counter", choices=["review", "qa", "reissue"])
    w = sp.add_parser("wo"); w.add_argument("dir"); w.add_argument("wo")
    w.add_argument("--worktree"); w.add_argument("--branch"); w.add_argument("--status", choices=WO_STATUSES)
    wt = sp.add_parser("wait"); wt.add_argument("dir"); wt.add_argument("file", nargs="?"); wt.add_argument("--clear", action="store_true")
    ag = sp.add_parser("agent"); ag.add_argument("dir"); ag.add_argument("action", choices=["start", "done"]); ag.add_argument("id")
    ag.add_argument("--label"); ag.add_argument("--output"); ag.add_argument("--prompt")
    ch = sp.add_parser("child"); ch.add_argument("dir"); ch.add_argument("repo"); ch.add_argument("--folder", required=True)
    tr = sp.add_parser("tracker"); tr.add_argument("dir")
    sh = sp.add_parser("show"); sh.add_argument("dir"); sh.add_argument("--json", action="store_true")
    ad = sp.add_parser("adopt"); ad.add_argument("dir")
    a = p.parse_args(argv)
    d = Path(a.dir)

    if a.cmd == "init":
        if (d / "state.json").exists():
            sys.exit(f"tempo_state: {d}/state.json exists; resume the task instead")
        d.mkdir(parents=True, exist_ok=True)
        st = new_state(a.task, a.flow, a.title, a.base_branch, a.base_commit, a.task_branch, a.mode,
                       a.parent, a.review_limit, a.qa_limit)
        st["next"] = "Run TRIAGE"
        save(d, st); print(f"STATE: {d}/state.md  STAGE: TRIAGE"); return 0

    if a.cmd == "adopt":
        st = adopt(d); save(d, st); print(f"STATE: {d}/state.json adopted from state.md  STAGE: {st['stage']}"); return 0

    st = load(d)
    if a.cmd == "set":
        for k in ("lane", "stage", "status", "next", "mode", "title", "pr"):
            v = getattr(a, k)
            if v is not None:
                st[k] = v
        if a.task_branch: st["task_branch"] = a.task_branch
        if a.base_commit: st["base_commit"] = a.base_commit
        if a.status == "DONE" or a.stage == "DONE":
            st["stage"], st["status"] = "DONE", "DONE"
    elif a.cmd == "log":
        st["log"].append([now(), a.stage, a.artifact, a.result])
    elif a.cmd == "bump":
        c = st["counters"]; c[a.counter] += 1
        lim = c.get(a.counter + "_limit")
        if lim and c[a.counter] > lim:
            save(d, st); print(f"LIMIT: {a.counter} rounds {c[a.counter]} of {lim}; raise LOOP-LIMIT"); return 1
    elif a.cmd == "wo":
        cur = st["work_orders"].setdefault(a.wo, {})
        for k in ("worktree", "branch", "status"):
            if getattr(a, k): cur[k] = getattr(a, k)
    elif a.cmd == "wait":
        if a.clear:
            st["waiting"], st["status"] = None, "RUNNING"
        elif a.file:
            st["waiting"], st["status"] = a.file, "WAITING-ON-JORGE"
        else:
            sys.exit("tempo_state: wait needs a file or --clear")
    elif a.cmd == "agent":
        if a.action == "start":
            if not (a.label and a.output):
                sys.exit("tempo_state: agent start needs --label and --output")
            st["agents"][a.id] = {"label": a.label, "output": a.output, "prompt": a.prompt, "started": now()}
        else:
            st["agents"].pop(a.id, None)
    elif a.cmd == "child":
        st["children"][a.repo] = {"folder": str(Path(a.folder).resolve()), "stage": None, "status": None, "pr": None}
        tracker(d, st)
    elif a.cmd == "tracker":
        tracker(d, st); save(d, st); print(f"TRACKER: {d}/tracker.md"); return 0
    elif a.cmd == "show":
        if a.json:
            print(json.dumps(st, indent=2, ensure_ascii=False))
        else:
            sys.stdout.write(render(st))
        return 0
    save(d, st)
    print(f"STATE: {d}/state.md  STAGE: {st['stage']}  STATUS: {st['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
