#!/usr/bin/env python3
"""TEMPO report: file a GitHub issue on the TEMPO repo when TEMPO misbehaves mid-run.

/tempo:report runs it. Standard library only; `gh` is used when it is installed and signed in.

Usage: tempo_report.py <command> [args]
  context  [--repo DIR] [--task ID]
           Print a markdown block with the run's context: plugin version, machine, repo, branch,
           the task (newest state.json under <repo>/.tempo, or --task), its state.md, its artifacts,
           other recent tasks, and the session transcript path. Reads only; changes nothing.
  file     --title T --body-file F [--label L ...] [--target OWNER/NAME] [--snapshot TASK_DIR] [--dry-run]
           File the issue. --snapshot first copies the task folder's documents (not worktrees) to
           ~/.cache/tempo/reports/<stamp>/ and adds that path to the body, so the evidence outlives
           /tempo:cleanup. With gh: ensures the `tempo` label exists, runs `gh issue create`, prints
           `ISSUE: <url>`. Without gh, or when it fails: saves the body next to the snapshot and prints
           `FALLBACK: <prefilled new-issue url>` and `BODY: <file>` (exit 2).

The target repo is --target, else $TEMPO_REPORT_REPO, else `repository` in the plugin's plugin.json.
Exit 0 filed, 1 error, 2 fallback (not filed: open the URL).
"""
import argparse
import datetime as dt
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import urllib.parse
from pathlib import Path

if sys.platform == "win32":  # the console code page cannot carry every character a task or a hook holds
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")

PLUGIN_ROOT = Path(__file__).resolve().parents[3]
REPORTS = Path.home() / ".cache" / "tempo" / "reports"
STATE_MD_CAP = 8000
URL_CAP = 7000  # GitHub refuses very long new-issue URLs; keep well under 8 KB
SKIP_DIRS = {"worktrees", "__pycache__", ".git", "node_modules"}
SNAPSHOT_FILE_CAP = 2 * 1024 * 1024
DEFAULT_LABELS = ["tempo", "bug"]


def run(cmd, cwd=None, timeout=30):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip(), p.stderr.strip()
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, "", str(e)


def plugin_meta():
    try:
        return json.loads((PLUGIN_ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def target_repo(arg):
    if arg:
        return arg
    if os.environ.get("TEMPO_REPORT_REPO"):
        return os.environ["TEMPO_REPORT_REPO"]
    url = str(plugin_meta().get("repository", ""))
    m = re.search(r"github\.com[:/]([^/]+)/([^/.\s]+)", url)
    return f"{m.group(1)}/{m.group(2)}" if m else None


def git_root(path):
    code, out, _ = run(["git", "rev-parse", "--show-toplevel"], cwd=path)
    return Path(out) if code == 0 and out else None


def find_tempo_root(repo):
    """The .tempo folder of the repo, or of the workspace folder when cwd is not in a repo."""
    start = Path(repo).resolve()
    root = git_root(start)
    if root and (root / ".tempo").is_dir():
        return root / ".tempo"
    for p in [start, *start.parents]:
        if (p / ".tempo").is_dir():
            return p / ".tempo"
    return None


def task_dirs(tempo):
    found = []
    for sj in tempo.glob("*/state.json"):
        if sj.parent.name in SKIP_DIRS:
            continue
        try:
            st = json.loads(sj.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            st = {}
        found.append((sj.stat().st_mtime, sj.parent, st))
    found.sort(key=lambda t: t[0], reverse=True)
    return found


def transcript_path(cwd):
    """Newest Claude Code transcript for this folder: most likely the current session."""
    base = Path.home() / ".claude" / "projects"
    if not base.is_dir():
        return None
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(Path(cwd).resolve()))
    d = base / slug
    files = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True) if d.is_dir() else []
    return files[0] if files else None


def artifacts(task):
    rows = []
    for p in sorted(task.rglob("*")):
        rel = p.relative_to(task)
        if any(part in SKIP_DIRS for part in rel.parts) or not p.is_file():
            continue
        st = p.stat()
        rows.append((str(rel), st.st_size, dt.datetime.fromtimestamp(st.st_mtime).strftime("%m-%d %H:%M")))
    return rows


def fmt_size(n):
    return f"{n} B" if n < 1024 else f"{n / 1024:.1f} KB"


def cmd_context(a):
    cwd = Path(a.repo or os.getcwd()).resolve()
    meta = plugin_meta()
    out = ["## Context (collected by /tempo:report)", ""]
    out.append(f"- TEMPO: {meta.get('version', '?')} at `{PLUGIN_ROOT}`")
    out.append(f"- Machine: {platform.node()} ({platform.system()} {platform.release()}), "
               f"python {platform.python_version()}")
    out.append(f"- Reported: {dt.datetime.now().strftime('%Y-%m-%d %H:%M %Z').strip()}")
    root = git_root(cwd)
    if root:
        _, branch, _ = run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
        _, head, _ = run(["git", "log", "-1", "--format=%h %s"], cwd=root)
        _, dirty, _ = run(["git", "status", "--porcelain"], cwd=root)
        n = len([x for x in dirty.splitlines() if x.strip()])
        out.append(f"- Repo: `{root}` on `{branch}` at {head} ({n} changed files)")
    else:
        out.append(f"- Folder: `{cwd}` (not a git repo: workspace task or no task)")
    tr = transcript_path(cwd)
    if tr:
        out.append(f"- Session transcript (newest for this folder): `{tr}`")

    tempo = find_tempo_root(cwd)
    if not tempo:
        out += ["", "No `.tempo/` folder found: the report is not tied to a task."]
        print("\n".join(out))
        return 0
    tasks = task_dirs(tempo)
    chosen = None
    if a.task:
        chosen = next((t for t in tasks if t[1].name == a.task), None)
        if not chosen and (tempo / a.task).is_dir():
            chosen = (0, tempo / a.task, {})
        if not chosen:
            print(f"ERROR: no task {a.task} under {tempo}", file=sys.stderr)
            return 1
    elif tasks:
        chosen = tasks[0]

    if chosen:
        _, d, st = chosen
        out += ["", f"### Task `{d.name}` (local id on {platform.node()})", ""]
        out.append(f"- Folder: `{d}`")
        if st:
            keys = ["flow", "mode", "lane", "stage", "status", "stage_since", "task_branch", "base_branch",
                    "pr", "autopilot", "waiting", "next"]
            out.append("- " + ", ".join(f"{k}: {st.get(k)}" for k in keys if st.get(k) not in (None, "", [])))
            agents = st.get("agents") or []
            if agents:
                out.append(f"- Agents in flight: {len(agents)}")
            if st.get("parent"):
                out.append(f"- Parent: `{st['parent']}`")
        sm = d / "state.md"
        if sm.is_file():
            text = sm.read_text(errors="replace", encoding="utf-8")
            cut = len(text) > STATE_MD_CAP
            text = text[:STATE_MD_CAP]
            out += ["", "<details><summary>state.md" + (" (cut)" if cut else "") + "</summary>", "",
                    "```markdown", text.rstrip(), "```", "", "</details>"]
        rows = artifacts(d)
        if rows:
            out += ["", "<details><summary>Artifacts (" + str(len(rows)) + ")</summary>", "",
                    "| file | size | modified |", "|---|---|---|"]
            out += [f"| {r} | {fmt_size(s)} | {m} |" for r, s, m in rows[:80]]
            if len(rows) > 80:
                out.append(f"| ... {len(rows) - 80} more | | |")
            out += ["", "</details>"]
    others = [t for t in tasks if not chosen or t[1] != chosen[1]][:5]
    if others:
        out += ["", "Other recent tasks: " + "; ".join(
            f"`{d.name}` {st.get('stage', '?')}/{st.get('status', '?')}" for _, d, st in others)]
    print("\n".join(out))
    return 0


def snapshot(task, stamp):
    dest = REPORTS / stamp / Path(task).name
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    for p in Path(task).rglob("*"):
        rel = p.relative_to(task)
        if any(part in SKIP_DIRS for part in rel.parts) or not p.is_file():
            continue
        if p.stat().st_size > SNAPSHOT_FILE_CAP:
            continue
        (dest / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest / rel)
        copied += 1
    return dest, copied


def ensure_label(repo):
    """Create the label; gh fails harmlessly when it already exists."""
    run(["gh", "label", "create", "tempo", "--repo", repo, "--color", "5319e7",
         "--description", "TEMPO plugin: reported from a run"])


def fallback_url(repo, title, body, labels, body_file):
    base = f"https://github.com/{repo}/issues/new?"
    q = {"title": title, "labels": ",".join(labels)}
    url = base + urllib.parse.urlencode({**q, "body": body})
    if len(url) <= URL_CAP:
        return url
    note = (f"\n\n---\nThe full report did not fit the link. It is saved at `{body_file}` on "
            f"{platform.node()}: paste it here.")
    keep = len(body)
    while keep > 200:
        keep = int(keep * 0.8)
        url = base + urllib.parse.urlencode({**q, "body": body[:keep] + "\n\n[...]" + note})
        if len(url) <= URL_CAP:
            return url
    return base + urllib.parse.urlencode({**q, "body": note.strip()})


def cmd_file(a):
    repo = target_repo(a.target)
    if not repo:
        print("ERROR: no target repo: pass --target OWNER/NAME or set TEMPO_REPORT_REPO", file=sys.stderr)
        return 1
    body = Path(a.body_file).read_text(encoding="utf-8")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    labels = a.label or DEFAULT_LABELS
    if a.snapshot and a.dry_run:
        print(f"DRY RUN: would copy {a.snapshot} to {REPORTS / stamp}")
    elif a.snapshot:
        dest, n = snapshot(Path(a.snapshot), stamp)
        body += (f"\n\n- Snapshot of the task folder ({n} files, worktrees left out): `{dest}` "
                 f"on {platform.node()}\n")
        print(f"SNAPSHOT: {dest} ({n} files)")
    if a.dry_run:
        print(f"DRY RUN: would file on {repo} with labels {','.join(labels)}: {a.title}")
        print(body)
        return 0

    reason = "gh is not installed"
    if shutil.which("gh"):
        code, _, err = run(["gh", "auth", "status", "--hostname", "github.com"])
        if code != 0:
            reason = "gh is not signed in to github.com"
        else:
            if "tempo" in labels:
                ensure_label(repo)
            tmp = REPORTS / stamp / "issue.md"
            tmp.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(body, encoding="utf-8")
            base = ["gh", "issue", "create", "--repo", repo, "--title", a.title, "--body-file", str(tmp)]
            code, out, err = run(base + sum((["--label", lab] for lab in labels), []), timeout=60)
            if code != 0 and "label" in err.lower():
                print(f"WARNING: labels refused ({err.splitlines()[-1] if err else ''}); filing without them")
                code, out, err = run(base, timeout=60)
            if code == 0:
                url = next((x for x in out.splitlines() if x.startswith("https://")), out)
                print(f"ISSUE: {url}")
                return 0
            reason = f"gh issue create failed: {err.splitlines()[-1] if err else code}"

    saved = REPORTS / stamp / "issue.md"
    saved.parent.mkdir(parents=True, exist_ok=True)
    saved.write_text(f"# {a.title}\n\n{body}", encoding="utf-8")
    print(f"NOT FILED: {reason}")
    print(f"BODY: {saved}")
    print(f"FALLBACK: {fallback_url(repo, a.title, body, labels, saved)}")
    return 2


def main():
    ap = argparse.ArgumentParser(description="File a TEMPO issue from a run")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("context")
    c.add_argument("--repo")
    c.add_argument("--task")
    f = sub.add_parser("file")
    f.add_argument("--title", required=True)
    f.add_argument("--body-file", required=True)
    f.add_argument("--label", action="append")
    f.add_argument("--target")
    f.add_argument("--snapshot")
    f.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    return cmd_context(a) if a.cmd == "context" else cmd_file(a)


if __name__ == "__main__":
    sys.exit(main())
