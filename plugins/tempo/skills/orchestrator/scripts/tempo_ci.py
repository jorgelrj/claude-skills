#!/usr/bin/env python3
"""TEMPO CI wait: watch an open PR's checks until it merges, and collect what a red check says.

Used by the CI-WAIT stage (orchestrator 3.12.1), which runs after SHIP when `limits.ci_rounds` is above 0.
TEMPO never merges: the repo's CI (or Jorge) does. This script only reads the PR with `gh`.

Usage: tempo_ci.py <command> --pr N [--repo DIR]
  watch   --pr N [--poll S] [--max S]   poll `gh pr view` and `gh pr checks` every --poll seconds (default 60)
                                        for at most --max seconds (default 3600), then print one line and exit 0:
                                          MERGED: <url>            the PR merged; the task may end
                                          CLOSED: <url>            closed without a merge
                                          CONFLICT: <url>          the PR conflicts with its base (CI does not run)
                                          DRAFT: <url>             a draft never merges: `gh pr ready`
                                          RED: <check>, ...        a check failed or was cancelled
                                          TIMEOUT: green|pending <checks>   nothing decided within --max
                                        The orchestrator runs it as a background Bash command; the spawn guard
                                        allows it by name (the whole command only). --max 100 runs it in the
                                        foreground under the 110 s cap instead.
  collect --pr N --out FILE [--lines N] [--artifact NAME]
                                        write the evidence of the red checks to FILE: the last --lines lines
                                        (default 80) of `gh run view --log-failed` per failed job, and the
                                        CRITICAL and HIGH findings of the review JSON in the artifact NAME
                                        (default ai-review) of a run on the PR head. Prints
                                        `CI: FILE  FAILED: <n>  BLOCKING: <n>  NO-EVIDENCE: <checks or NIL>`.
Exit 0 ok, 1 gh failed or usage error.
"""
import argparse
import json
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

if sys.platform == "win32":  # the console code page cannot carry every character a task or a hook holds
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")

BLOCKING = ("CRITICAL", "HIGH")
RUN_LINK = re.compile(r"/actions/runs/(\d+)(?:/job/(\d+))?")


def gh(cwd, *args, ok=(0,)):
    r = subprocess.run(["gh", *args], cwd=cwd, capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    if r.returncode not in ok:
        lines = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(f"gh {args[0]} {args[1] if len(args) > 1 else ''}: {lines[-1] if lines else f'exit {r.returncode}'}")
    return r.stdout


def pr_view(cwd, pr):
    return json.loads(gh(cwd, "pr", "view", str(pr), "--json", "state,isDraft,mergeStateStatus,headRefOid,url"))


def pr_checks(cwd, pr):
    # exit 1: a check failed, 8: checks pending; both still print the JSON. No checks yet is an error with no JSON.
    try:
        out = gh(cwd, "pr", "checks", str(pr), "--json", "name,state,bucket,link,workflow", ok=(0, 1, 8))
    except RuntimeError as e:
        if "no checks" in str(e).lower():
            return []
        raise
    return json.loads(out or "[]")


def verdict(pr, checks):
    """(KIND, text) once the PR's fate is decided or needs TEMPO, else None (keep waiting)."""
    url = pr.get("url") or ""
    if pr.get("state") == "MERGED":
        return "MERGED", url
    if pr.get("state") == "CLOSED":
        return "CLOSED", url
    if pr.get("mergeStateStatus") == "DIRTY":  # GitHub runs no pull_request workflow on a conflicting PR
        return "CONFLICT", url
    if pr.get("isDraft"):
        return "DRAFT", url
    red = [c["name"] for c in checks if c.get("bucket") in ("fail", "cancel")]
    if red:
        return "RED", ", ".join(red)
    return None


def waiting(checks):
    pending = [c["name"] for c in checks if c.get("bucket") == "pending"]
    if pending or not checks:
        return "pending " + (", ".join(pending) or "(no checks reported yet)")
    return "green (every check passed; the PR is not merged yet)"


def watch(cwd, pr, poll, max_s):
    end = time.time() + max_s
    while True:
        try:
            checks = pr_checks(cwd, pr)
            v = verdict(pr_view(cwd, pr), checks)
            state = waiting(checks)
        except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
            v, state = None, f"pending (gh did not answer: {e})"  # a network blip is not a verdict
        if v:
            print(f"{v[0]}: {v[1]}"); return 0
        if time.time() + poll > end:
            print(f"TIMEOUT: {state}"); return 0
        time.sleep(poll)


def review_findings(data):
    """CRITICAL and HIGH findings from a review JSON: a list, or an object with a findings list."""
    items = data.get("findings", []) if isinstance(data, dict) else data
    return [f for f in items or [] if isinstance(f, dict) and str(f.get("severity", "")).upper() in BLOCKING]


def collect(cwd, pr, out, lines, artifact):
    head = pr_view(cwd, pr)
    failed = [c for c in pr_checks(cwd, pr) if c.get("bucket") in ("fail", "cancel")]
    md = [f"# CI evidence: PR {head.get('url')}", f"Head: {head.get('headRefOid')}", ""]
    no_evidence = []
    for c in failed:
        md.append(f"## Check {c['name']} ({c.get('state')}) {c.get('link') or ''}".rstrip())
        m = RUN_LINK.search(c.get("link") or "")
        log = ""
        if m:
            try:
                args = ["--job", m.group(2)] if m.group(2) else [m.group(1)]
                log = gh(cwd, "run", "view", *args, "--log-failed")
            except RuntimeError as e:
                log = ""
                md.append(f"- log not read: {e}")
        tail = log.strip().splitlines()[-lines:]
        if tail:
            md += ["```", *tail, "```"]
        else:
            no_evidence.append(c["name"])
        md.append("")
    blocking = []
    try:
        runs = json.loads(gh(cwd, "run", "list", "--commit", head.get("headRefOid") or "", "--limit", "30",
                             "--json", "databaseId,workflowName") or "[]")
    except RuntimeError as e:
        runs = []
        md.append(f"- runs on the head not listed: {e}")
    found = False
    for run in runs:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                gh(cwd, "run", "download", str(run["databaseId"]), "-n", artifact, "-D", tmp)
            except RuntimeError:
                continue  # this run has no such artifact
            found = True
            for f in sorted(Path(tmp).rglob("*.json")):
                try:
                    blocking += review_findings(json.loads(f.read_text(encoding="utf-8")))
                except ValueError:
                    md.append(f"- {f.name} in {artifact} is not JSON")
        if found:
            break
    md.append(f"## Review findings, CRITICAL and HIGH ({artifact})")
    if not found:
        md.append(f"- NIL: no run on the head has an artifact named {artifact}")
    for f in blocking:
        where = f"{f.get('file') or '?'}:{f.get('line') or '?'}"
        md.append(f"- {str(f.get('severity')).upper()} {where} {f.get('title') or ''}: {f.get('detail') or f.get('message') or ''}"
                  f"{' Suggestion: ' + f['suggestion'] if f.get('suggestion') else ''}".rstrip())
    if found and not blocking:
        md.append("- NIL")
    if blocking:  # a failed review check whose findings are here has its evidence
        no_evidence = [n for n in no_evidence if artifact not in n]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")
    print(f"CI: {out}  FAILED: {len(failed)}  BLOCKING: {len(blocking)}  NO-EVIDENCE: {', '.join(no_evidence) or 'NIL'}")
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog="tempo_ci.py", description="TEMPO CI wait")
    sp = p.add_subparsers(dest="cmd", required=True)
    for name in ("watch", "collect"):
        s = sp.add_parser(name)
        s.add_argument("--pr", required=True)
        s.add_argument("--repo", default=".")
        if name == "watch":
            s.add_argument("--poll", type=float, default=60)
            s.add_argument("--max", type=float, default=3600)
        else:
            s.add_argument("--out", required=True)
            s.add_argument("--lines", type=int, default=80)
            s.add_argument("--artifact", default="ai-review")
    a = p.parse_args(argv)
    try:
        if a.cmd == "watch":
            return watch(a.repo, a.pr, a.poll, a.max)
        return collect(a.repo, a.pr, a.out, a.lines, a.artifact)
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
        print(f"ERROR: {e}"); return 1


if __name__ == "__main__":
    sys.exit(main())
