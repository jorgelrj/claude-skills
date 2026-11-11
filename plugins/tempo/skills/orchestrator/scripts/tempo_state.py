#!/usr/bin/env python3
"""TEMPO task state: the only writer of .tempo/<task-id>/state.json and state.md.

state.json is the source of truth. state.md is rendered from it after every
change, in the layout of the state template, for Jorge and /tempo:resume.
Every command that changes state also appends one line to events.jsonl, the history tempo_dash.py shows.
Times come from this machine's clock, never from the caller.

Usage: tempo_state.py <command> <task-dir> [args]
  claim     <tempo-root> [--id KEY]          (reserve a task folder atomically and print its ID. Without --id: the
                                              next T-NNN after the highest one in <tempo-root>, safe when tasks
                                              start in parallel. With --id: that folder; exit 3 and EXISTS when it
                                              is already there, so the caller resumes it)
  init      <dir> --task ID --flow FEATURE|BUG|WORKSPACE --title T --base-branch B --base-commit H
            [--task-branch NAME] [--mode FULL|PLAN-ONLY] [--parent DIR] [--review-limit N] [--qa-limit N]
            [--review-extensions N] [--autopilot]
  set       <dir> [--lane L] [--stage S] [--status S] [--next TEXT] [--mode M] [--title T]
            [--task-branch B] [--base-commit H] [--pr URL] [--review-limit N] [--review-extensions N]
            [--autopilot on|off] [--critical on|off] [--pattern on|off]
                                                 (DONE clears the agents still listed in flight. Stage DONE and
                                                  status DONE, FAILED or ABORTED tear the task down: every process
                                                  it started stops, see tempo_procs.py)
  decide    <dir> KIND --question Q --choice C --why W [--from FILE] [--not-a-source WHY]
                                                 (record a decision autopilot accepted; writes decisions.md.
                                                  Refuses the stop kinds of orchestrator 4.5.1, and a question
                                                  that reads like a missing source unless --not-a-source)
  log       <dir> STAGE ARTIFACT PASS|FAIL|BLOCKED   (logging findings-rN.md raises the review count to N;
                                                   records start and end, closes the agent that wrote ARTIFACT
                                                   (EXPLORE also closes the scouts, REVIEW the round's reviewers);
                                                   the same stage and artifact again right after extends that entry;
                                                   warns when STAGE is not the current stage)
  bump      <dir> review|qa|reissue               (exit 1: past the limit, raise LOOP-LIMIT;
                                                   exit 2: past limit + extensions, HARD STOP)
  wo        <dir> WO-NN [--worktree P] [--branch B] [--status S]
                                                 (an order issued again after DONE starts a new timed run)
  wait      <dir> ESC-FILE | --clear            (a wait stops the task's services: tempo_procs.py teardown --services-only)
  agent     <dir> start ID --label L --output PATH [--prompt FILE]
                                                 (refuses a label or output with an unfilled placeholder)
  agent     <dir> done ID
  child     <dir> NAME --folder DIR            (register a child task: a repo of a workspace task, or a slice S-n)
  tracker   <dir>                              (refresh children from their state.json, write tracker.md)
  show      <dir> [--json]
  adopt     <dir>                              (build state.json from a hand-written state.md)
Exit 0 ok, 1 error, 3 claim: the folder exists.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tempo_procs  # noqa: E402


def teardown(d, services_only):
    """Stop what the task started (orchestrator section 10). Never fails the state change."""
    try:
        lines, bad = tempo_procs.teardown(d, services_only=services_only, quiet=True)
        for line in lines:
            print(line)
        if bad:
            print(f"TEARDOWN: {bad} process(es) could not be stopped; run /tempo:sweep", file=sys.stderr)
    except Exception as e:
        print(f"TEARDOWN: error {e}; run /tempo:sweep", file=sys.stderr)

STAGES = ["TRIAGE", "EXPLORE", "INVESTIGATE", "REPRODUCE", "ROOT-CAUSE", "SPEC", "HANDOFF", "PLAN",
          "PLANNED", "SLICES", "BUILD", "INTEGRATE", "REVIEW", "QA", "SHIP", "REPOS", "JOINT-QA", "DONE"]
STATUSES = ["RUNNING", "WAITING-ON-JORGE", "FAILED", "ABORTED", "DONE"]
ENDED = ("DONE", "FAILED", "ABORTED")
RESULTS = ["PASS", "FAIL", "BLOCKED"]
WO_STATUSES = ["ISSUED", "BUILDING", "DONE", "BLOCKED"]
# A label or output left with a template hole: "scout-", "explore/.md", "<LENS>".
UNFILLED = re.compile(r"<[A-Za-z_-]+>|\{[A-Za-z_]+\}|[-_/]$|(^|/)\.md$|[-_]\.md$")
# Stops autopilot never accepts (orchestrator 4.5.1). decide refuses them, and refuses a question
# that reads like a source the ticket names could not be opened: a stand-in for it is not a decision.
STOP_KINDS = {"NO-REPRO", "BEHAVIOUR-CHANGE", "OUT-OF-ORDER-DECISION", "HARD-TO-UNDO", "MISSING-SOURCE", "GATE-PR"}
MISSING_SOURCE = re.compile(
    r"not (found|available|accessible|visible|reachable)|\b40[134]\b|no access|access denied|"
    r"can(not|'t|\u2019t) (open|access|find|fetch|see)|missing (source|asset|attachment|design|prototype|file|image|icon)|"
    r"(asset|attachment|prototype|design|figma)s? (is |are )?(missing|unavailable)|only (an )?(older|newer|other) version",
    re.IGNORECASE)


def now():
    return dt.datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")


def minutes(start, end):
    try:
        f = "%Y-%m-%d %H:%M"
        return int((dt.datetime.strptime(end, f) - dt.datetime.strptime(start, f)).total_seconds() // 60)
    except (TypeError, ValueError):
        return None


def log_line(e):
    if len(e) == 4:  # entries from before 0.7.0 carry the end time only
        return " | ".join(e)
    start, end, stage, artifact, result = e
    m = minutes(start, end)
    return f"{start} → {end[11:]} ({m} min) | {stage} | {artifact} | {result}" if m is not None else f"{end} | {stage} | {artifact} | {result}"


def wo_line(k, v):
    took = ""
    if v.get("started"):
        m = minutes(v["started"], v.get("finished") or now())
        earlier = [minutes(a, b) for a, b in v.get("runs", [])]
        if m is not None:
            took = f" | {v['started'][11:]}, {m} min{'' if v.get('finished') else ' so far'}"
            if earlier:
                took += f" (run {len(earlier) + 1}; earlier runs {' + '.join(str(x) for x in earlier if x is not None)} min)"
    return f"{k} | {v.get('worktree') or 'TBD'} | {v.get('branch') or 'TBD'} | {v.get('status') or 'ISSUED'}{took}"


def load(d):
    p = Path(d) / "state.json"
    if not p.is_file():
        sys.exit(f"tempo_state: {p} not found. Run `init`, or `adopt` for a task started before v0.3.0.")
    return json.loads(p.read_text(encoding="utf-8"))


def save(d, s):
    d = Path(d)
    for name, text in (("state.json", json.dumps(s, indent=2, ensure_ascii=False) + "\n"), ("state.md", render(s))):
        tmp = d / f".{name}.{os.getpid()}.tmp"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, d / name)  # the dashboard reads both while a task runs: never a half-written file


def render(s):
    L = [f"# Task State: {s['task']}",
         f"Flow: {s['flow']} · Lane: {s.get('lane') or 'TBD'} · Mode: {s.get('mode', 'FULL')}"
         f"{' · Autopilot: ON' if s.get('autopilot') else ''}{' · Critical' if s.get('critical') else ''}"
         f"{' · Pattern' if s.get('pattern') else ''} · Owner: orchestrator",
         "Rendered by tempo_state.py from state.json. Do not edit.", ""]

    def section(n, title, items):
        L.append(f"## {n} {title}")
        L.extend(f"- {text}" for text in (items or ["NIL"]))
        L.append("")

    section(1, "Task", [
        s['title'].rstrip('.'),
        f"Started: {s['started']}",
        f"Base branch: {s['base_branch']} at {s['base_commit']}",
        f"Task branch: {s.get('task_branch') or 'NIL'}",
        f"Parent: {s.get('parent') or 'NIL'}",
    ] + ([f"Pull request: {s['pr']}"] if s.get("pr") else []))
    section(2, "Stage", [f"Current: {s['stage']}", f"Status: {s['status']}"])
    section(3, "Stage log", [log_line(e) for e in s["log"]] +
            ([f"{s['stage']} running since {s['stage_since']}"] if s.get("stage_since") and s["status"] == "RUNNING" else []))
    c = s["counters"]
    section(4, "Loop counters", [f"Review rounds: {c['review']} of {c['review_limit']}. Extensions: {c.get('review_extensions', 1)}",
                                 f"QA rounds: {c['qa']} of {c['qa_limit']}",
                                 f"Document re-issues: {c['reissue']}"])
    section(5, "Work orders", [wo_line(k, v) for k, v in sorted(s["work_orders"].items())])
    section(6, "Waiting on Jorge", [s["waiting"]] if s.get("waiting") else [])
    section(7, "Next action", [s["next"]] if s.get("next") else [])
    section(8, "Agents in flight", [f"{k} | {v['label']} | {v['output']} | {v.get('prompt') or 'NIL'} | started {v['started']}"
                                    for k, v in s["agents"].items()])
    section(9, "Child tasks", [f"{k} | {v['folder']} | {v.get('stage') or 'TBD'} | {v.get('status') or 'TBD'} | {v.get('pr') or 'NIL'}"
                               + child_time(v) for k, v in s["children"].items()])
    return "\n".join(L).rstrip() + "\n"


def child_time(v):
    if not v.get("started"):
        return ""
    end = v.get("ended") or now()
    m = minutes(v["started"], end)
    return f" | {v['started'][11:]} → {end[11:]} ({m} min{'' if v.get('status') == 'DONE' else ' so far'})" if m is not None else ""


def render_decisions(s):
    L = [f"# Autopilot decisions: {s['task']}",
         "Rendered by tempo_state.py from state.json. Do not edit. Each line is a stop TEMPO answered with its own",
         "recommendation instead of asking Jorge. Review them at the pull request.", "",
         "## 1 Decisions"]
    L.extend(f"- D-{n} | {e['at']} | {e['kind']} | {e['question']} | Chose: {e['choice']} | Why: {e['why']}"
             + (f" | From: {e['from']}" if e.get("from") else "")
             for n, e in enumerate(s.get("decisions", []), 1))
    if not s.get("decisions"):
        L.append("- NIL")
    return "\n".join(L) + "\n"


def tracker(d, s):
    rows = ["# Tracker " + s["task"], "", f"Generated {now()} by tempo_state.py from each child's state.json. Do not edit.", "",
            "| Repo or slice | Stage | Status | Pull request | Next action |", "|---|---|---|---|---|"]
    for repo, ch in s["children"].items():
        f = Path(ch["folder"]) / "state.json"
        if f.is_file():
            cs = json.loads(f.read_text(encoding="utf-8"))
        elif (Path(ch["folder"]) / "state.md").is_file():
            cs = adopt(ch["folder"])  # task from before 0.3.0: read its state.md, write nothing
        else:
            cs = None
        if cs:
            ends = [e[-4] for e in cs.get("log", []) if len(e) == 5]
            ch.update(stage=cs["stage"], status=cs["status"], pr=cs.get("pr"), next=cs.get("next"),
                      started=cs.get("started"), ended=(ends[-1] if ends and cs["status"] == "DONE" else None))
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
    m = re.search(r"Extensions:\s*(\d+)", text)
    if m: s["counters"]["review_extensions"] = int(m.group(1))
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
              review_limit=3, qa_limit=3, review_extensions=1, autopilot=False):
    return {"version": 1, "task": task, "flow": flow, "lane": None, "mode": mode, "title": title,
            "started": now(), "stage_since": now(), "base_branch": base_branch, "base_commit": base_commit,
            "task_branch": task_branch, "parent": parent, "pr": None, "stage": "TRIAGE", "status": "RUNNING",
            "log": [], "counters": {"review": 0, "review_limit": review_limit, "review_extensions": review_extensions,
                         "qa": 0, "qa_limit": qa_limit, "reissue": 0},
            "work_orders": {}, "waiting": None, "next": None, "agents": {}, "children": {},
            "autopilot": autopilot, "decisions": []}


LOCAL_ID = re.compile(r"^T-(\d+)")


def claim(root, key=None, owner=0):
    """Reserve <root>/<id>/ with an atomic mkdir. Returns (id, created).

    Two sessions that scan .tempo/ at the same moment both see T-004 as free; only one
    mkdir of T-004 succeeds, and the other moves on to T-005. Folders with any T-NNN
    prefix (a T-003-s1 slice, a T-002-wo-01 worktree) count as taken, so no old id comes back.
    """
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    note = json.dumps({"claimed": now(), "pid": os.getpid(), "owner": owner}) + "\n"
    if key:
        try:
            (root / key).mkdir()
        except FileExistsError:
            return key, False
        (root / key / ".claim").write_text(note)
        return key, True
    used = [int(m.group(1)) for e in root.iterdir() if (m := LOCAL_ID.match(e.name))]
    n = max(used, default=0)
    while True:
        n += 1
        tid = f"T-{n:03d}"
        try:
            (root / tid).mkdir()
        except FileExistsError:
            continue
        (root / tid / ".claim").write_text(note)
        return tid, True


def main(argv=None):
    p = argparse.ArgumentParser(prog="tempo_state.py", description="TEMPO task state")
    sp = p.add_subparsers(dest="cmd", required=True)
    cl = sp.add_parser("claim"); cl.add_argument("dir"); cl.add_argument("--id", dest="key")
    i = sp.add_parser("init"); i.add_argument("dir")
    for a in ("--task", "--title", "--base-branch", "--base-commit"):
        i.add_argument(a, required=True)
    i.add_argument("--flow", required=True, choices=["FEATURE", "BUG", "WORKSPACE"])
    i.add_argument("--mode", default="FULL", choices=["FULL", "PLAN-ONLY"])
    i.add_argument("--task-branch"); i.add_argument("--parent")
    i.add_argument("--review-limit", type=int, default=3); i.add_argument("--qa-limit", type=int, default=3)
    i.add_argument("--review-extensions", type=int, default=1); i.add_argument("--autopilot", action="store_true")
    s_ = sp.add_parser("set"); s_.add_argument("dir")
    s_.add_argument("--lane", choices=["S", "M", "L", "TBD"]); s_.add_argument("--stage", choices=STAGES)
    s_.add_argument("--status", choices=STATUSES); s_.add_argument("--next"); s_.add_argument("--mode", choices=["FULL", "PLAN-ONLY"])
    s_.add_argument("--title"); s_.add_argument("--task-branch"); s_.add_argument("--base-commit"); s_.add_argument("--pr")
    s_.add_argument("--review-limit", type=int); s_.add_argument("--review-extensions", type=int)
    s_.add_argument("--autopilot", choices=["on", "off"])
    s_.add_argument("--critical", choices=["on", "off"]); s_.add_argument("--pattern", choices=["on", "off"])
    dc = sp.add_parser("decide"); dc.add_argument("dir"); dc.add_argument("kind")
    for x in ("--question", "--choice", "--why"):
        dc.add_argument(x, required=True)
    dc.add_argument("--from", dest="source")
    dc.add_argument("--not-a-source", help="why a question that mentions something missing is not a source of truth")
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
    if a.cmd == "claim":
        owner = tempo_procs.find_owner()
        tid, created = claim(d, a.key, owner)
        if not created:
            print(f"EXISTS: {d / tid}  TASK: {tid}  (resume it, or pick another ID)"); return 3
        tempo_procs.register(d / tid, owner)
        print(f"TASK: {tid}  DIR: {d / tid}"); return 0
    tempo_procs.register(d, tempo_procs.find_owner())  # marks this session as a TEMPO session for the hooks
    closed = None  # agent ids this command took off the in-flight list

    def emit(st):
        given = {k: v for k, v in vars(a).items() if k not in ("dir", "cmd") and v is not None and v is not False}
        if closed is not None:
            given["closed"] = closed
        tempo_procs.event(d, ev=a.cmd, **given, state=f"{st['stage']}/{st['status']}")

    if a.cmd == "init":
        if (d / "state.json").exists():
            sys.exit(f"tempo_state: {d}/state.json exists; resume the task instead")
        d.mkdir(parents=True, exist_ok=True)
        st = new_state(a.task, a.flow, a.title, a.base_branch, a.base_commit, a.task_branch, a.mode,
                       a.parent, a.review_limit, a.qa_limit, a.review_extensions, a.autopilot)
        st["next"] = "Run TRIAGE"
        save(d, st); emit(st); print(f"STATE: {d}/state.md  STAGE: TRIAGE"); return 0

    if a.cmd == "adopt":
        st = adopt(d); save(d, st); print(f"STATE: {d}/state.json adopted from state.md  STAGE: {st['stage']}"); return 0

    st = load(d)
    if a.cmd == "set":
        if a.stage and a.stage != st["stage"]:
            st["stage_since"] = now()
        for k in ("lane", "stage", "status", "next", "mode", "title", "pr"):
            v = getattr(a, k)
            if v is not None:
                st[k] = v
        if a.task_branch: st["task_branch"] = a.task_branch
        if a.base_commit: st["base_commit"] = a.base_commit
        if a.review_limit is not None: st["counters"]["review_limit"] = a.review_limit
        if a.review_extensions is not None: st["counters"]["review_extensions"] = a.review_extensions
        if a.autopilot: st["autopilot"] = a.autopilot == "on"
        if a.critical: st["critical"] = a.critical == "on"
        if a.pattern: st["pattern"] = a.pattern == "on"
        if a.status == "DONE" or a.stage == "DONE":
            st["stage"], st["status"] = "DONE", "DONE"
        if st["status"] in ENDED:
            if st["agents"]:
                print(f"CLEARED: {len(st['agents'])} agent(s) still listed in flight: {', '.join(v['label'] for v in st['agents'].values())}")
            closed = list(st["agents"])
            st["agents"] = {}
    elif a.cmd == "log":
        if a.stage != st["stage"]:
            print(f"WARNING: logging {a.stage} while the current stage is {st['stage']}. Its start time is when "
                  f"{st['stage']} began. Run `set --stage {a.stage}` when that stage starts, so its time is its own.",
                  file=sys.stderr)
        prev = st["log"][-1][-4] if st["log"] else st["started"]  # end of the previous entry
        last = st["log"][-1] if st["log"] else None
        if last and len(last) == 5 and last[2] == a.stage and last[3] == a.artifact and st.get("stage_since") == last[1]:
            last[1], last[4] = now(), a.result  # the same stage redid its artifact (an amend): one entry
        else:
            st["log"].append([st.get("stage_since") or prev, now(), a.stage, a.artifact, a.result])
        st["stage_since"] = now()
        name = Path(a.artifact).name
        rnd = re.search(r"-r(\d+)\.md$", a.artifact)

        def done_with(out):
            o = Path(out or "")
            if o.name == name:
                return True
            if a.stage == "EXPLORE" and o.parent.name == "explore":  # context.md merges every scout
                return True
            if a.stage == "REVIEW" and rnd and o.parent.name == "review" and o.name.endswith(f"-r{rnd.group(1)}.md"):
                return True  # the round's findings close its reviewers
            return False
        closed = [k for k, v in st["agents"].items() if done_with(v.get("output"))]
        for aid in closed:
            st["agents"].pop(aid)  # its output is logged, so it is no longer in flight
        st["next"] = None  # the caller sets the next step; a stale one never survives a log
        m = re.search(r"findings-r(\d+)\.md$", a.artifact)
        if a.stage == "REVIEW" and m:  # the findings file is the round's record; the counter never lags it
            st["counters"]["review"] = max(st["counters"]["review"], int(m.group(1)))
    elif a.cmd == "bump":
        c = st["counters"]; c[a.counter] += 1
        lim = c.get(a.counter + "_limit")
        ext = c.get("review_extensions", 1) if a.counter == "review" else 0  # tasks from before 0.4.0 lack the key
        if lim and c[a.counter] > lim + ext:
            save(d, st); emit(st)
            print(f"HARD STOP: {a.counter} rounds {c[a.counter]} of {lim} plus {ext} extensions; ship open findings as known risks")
            return 2
        if lim and c[a.counter] > lim:
            save(d, st); emit(st); print(f"LIMIT: {a.counter} rounds {c[a.counter]} of {lim}; raise LOOP-LIMIT"); return 1
    elif a.cmd == "wo":
        cur = st["work_orders"].setdefault(a.wo, {})
        for k in ("worktree", "branch", "status"):
            if getattr(a, k): cur[k] = getattr(a, k)
        if a.status in ("ISSUED", "BUILDING") and cur.get("finished"):
            cur.setdefault("runs", []).append([cur["started"], cur["finished"]])  # a fix run after DONE
            cur["started"] = now()
        if a.status in ("ISSUED", "BUILDING") and not cur.get("started"):
            cur["started"] = now()
        if a.status in ("DONE", "BLOCKED"):
            cur["finished"] = now()
        elif a.status:
            cur.pop("finished", None)
    elif a.cmd == "wait":
        if a.clear:
            st["waiting"], st["status"] = None, "RUNNING"
        elif a.file:
            st["waiting"], st["status"] = a.file, "WAITING-ON-JORGE"
        else:
            sys.exit("tempo_state: wait needs a file or --clear")
    elif a.cmd == "decide":
        kind = a.kind.upper()
        if kind in STOP_KINDS:
            sys.exit(f"tempo_state: autopilot does not accept {kind} (orchestrator 4.5.1). Write the esc file, "
                     f"run `wait`, and ask Jorge.")
        if not a.not_a_source and MISSING_SOURCE.search(f"{a.question} {a.choice}"):
            sys.exit("tempo_state: this reads like a missing source (orchestrator 4.5.1.1). A stand-in for something "
                     "the ticket names is not a decision: raise MISSING-SOURCE and ask Jorge. If the missing thing is "
                     "not a source of truth (a git-ignored local file, a tool), pass --not-a-source \"<why>\".")
        st.setdefault("decisions", []).append({"at": now(), "kind": a.kind, "question": a.question,
                                               "choice": a.choice, "why": a.why, "from": a.source})
        (d / "decisions.md").write_text(render_decisions(st), encoding="utf-8")
    elif a.cmd == "agent":
        if a.action == "start":
            if not (a.label and a.output):
                sys.exit("tempo_state: agent start needs --label and --output")
            hole = [x for x in (a.label, a.output) if UNFILLED.search(x)]
            if hole:
                sys.exit(f"tempo_state: agent start: '{hole[0]}' has an unfilled part (a lens, a number). "
                         "Pass the agent's real label and output path, e.g. --label scout-CODE-PATHS "
                         "--output .tempo/T-001/explore/CODE-PATHS.md")
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
    emit(st)
    print(f"STATE: {d}/state.md  STAGE: {st['stage']}  STATUS: {st['status']}")
    if a.cmd == "set" and st["status"] in ENDED:
        teardown(d, services_only=False)
    elif a.cmd == "wait" and a.file:
        teardown(d, services_only=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
