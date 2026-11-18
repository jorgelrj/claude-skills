#!/usr/bin/env python3
# /// script
# requires-python = ">=3.9"
# dependencies = ["pyyaml>=6", "jsonschema>=4.18"]
# ///
"""TEMPO config: check, resolve and render the YAML config files.

Files, later wins:
  1. <plugin>/skills/config/defaults.yaml
  2. <workspace>/.tempo/workspace.yaml  defaults:      (found by walking up)
  3. the toolchain named by the merged settings      (workspace toolchains:)
  4. <workspace>/.tempo/workspace.yaml  repos.<name>:  (matched by path)
  5. <repo>/.tempo/config.yaml
  6. <repo>/.tempo/config.local.yaml  this machine's own overrides (git-ignored; a linked worktree without one
                                      uses the main checkout's), e.g. limits.max_parallel_builders: 1

Run with `uv run tempo_config.py ...` (installs pyyaml and jsonschema on the fly)
or `python3 tempo_config.py ...` when both are installed.

Commands:
  check   [FILE ...]                     validate files (default: the ones that apply to --repo)
  resolve [--format json|yaml]           print the merged config for --repo (or the workspace)
  names   [--type T] [--ticket KEY] [--slug S] [--suffix X] [--branch B] [--wo N ...]
                                         print branch names, commit and PR title templates. Names carry the
                                         ticket key, else the slug; a local T-NNN id never leaves .tempo/.
                                         The task branch follows the repo's convention (config, else the
                                         prefixes of its remote branches, else {type}/{ticket}); tempo/ names
                                         are local work branches only and never name the task branch
  cmd     NAME [--var k=v ...]           print one command as a shell line, env exported first. Under
                                         gates.full_bars: ci, test_one prints commands.test_local when it is set
  targets [--paths P ...] [--ref REF] [--full] [--critical] [--final] [--scoped-only] [--verify]
                                         print the platform test runs for the changed paths: scoped to the
                                         tests those paths touch or mirror when a target has scoped_command.
                                         Targets with run: critical (advisory targets by default) print only
                                         with --critical or --full; run: final also with --final (the integrate
                                         after the last wave). --scoped-only: a target that would print
                                         its whole command prints `# DEFERRED whole suite` instead.
                                         Under gates.full_bars: ci a target prints `# DEFERRED to CI`, and a
                                         run: ci target never prints; both run their commands with --verify only
  bars    [--paths P ...] [--critical]   print the bars an integrate runs: BARS: FULL|NARROW and why. With
                                         gates.full_bars: verify it is NARROW, plus a DEFERRED: line when the
                                         change would have run the whole suite. With gates.full_bars: ci it is
                                         LOCAL plus a DEFERRED: ci line. Then one ALWAYS: line per
                                         tests.always file and one SLOW: line per tests.slow file the paths
                                         touch or mirror
  dupes   --ticket KEY --branch B ...    list open PRs and remote branches that already carry the ticket
                                         (DUPE: pr|branch <ref> <url>), other than the task's own branches
                                         and branches whose PRs all merged or closed; exit 3 when any. WARN and exit 0 when gh or the remote cannot answer
  setup   --worktree PATH                print the shell steps that prepare a new worktree
  teardown --worktree PATH               print the shell steps that release a worktree's resources
  repos                                  list workspace repos in dependency order
  docs    [--format list|json]           list the project's doc files (config docs:), index files first
  migrate FILE                           convert a legacy .tempo/config.md to YAML on stdout
  ticket  --text REQUEST                 print the ticket the request names first and its tracker
                                         (task.trackers, else task.tracker and task.ticket_pattern)
  sync    start|pr|merged --text REQUEST assign the request's ticket and move it to the status that tracker's
                                         sync: sets for the event (Jira via atlassian-multi's atl.py, GitHub
                                         via gh and its Projects board). Prints ASSIGNED:/MOVED:/WARN:/SYNC: OFF
                                         lines and exits 0 whatever the tracker answers
Common option: --repo PATH (default: current directory).
Exit codes: 0 ok, 1 invalid config or usage error, 2 missing dependency, 3 dupes found.
"""
import argparse
import copy
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

if sys.platform == "win32":  # the console code page cannot carry every character a task or a hook holds
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")

try:
    import yaml
    import jsonschema
except ImportError as e:  # pragma: no cover
    sys.stderr.write(
        f"tempo_config: missing Python package ({e.name}).\n"
        "Run it with uv:  uv run <this script> ...\n"
        "or install:      python3 -m pip install pyyaml jsonschema\n"
    )
    sys.exit(2)
if not hasattr(jsonschema, "Draft202012Validator"):  # pragma: no cover
    sys.stderr.write(
        f"tempo_config: jsonschema {getattr(jsonschema, '__version__', '?')} is too old (need 4.18+).\n"
        "Run it with uv:  uv run <this script> ...\n"
    )
    sys.exit(2)

HERE = Path(__file__).resolve().parent
CONFIG_DIR = HERE.parent
SCHEMA_PATH = CONFIG_DIR / "schema" / "tempo-config.schema.json"
DEFAULTS_PATH = CONFIG_DIR / "defaults.yaml"
REPO_FILE = Path(".tempo/config.yaml")
LOCAL_FILE = Path(".tempo/config.local.yaml")
LEGACY_FILE = Path(".tempo/config.md")
WORKSPACE_FILE = Path(".tempo/workspace.yaml")
DOC_SUFFIXES = {".md", ".mdx", ".markdown", ".rst", ".txt", ".adoc"}
DOC_SKIP_DIRS = {".git", ".tempo", "node_modules", "build", "dist", "target", ".dart_tool", ".idea", ".gradle", ".venv", "venv", "__pycache__"}
DEFAULT_INDEX = ["index.md", "README.md"]
INTERP = re.compile(r"\$\{(env:[A-Za-z_][A-Za-z0-9_]*|workspace|repo)\}")


class ConfigError(Exception):
    pass


# ---------- loading and validation ----------

def load_yaml(path):
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"{path}: not valid YAML: {e}")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path}: top level SHALL be a mapping")
    return data


def schema():
    with open(SCHEMA_PATH, encoding="utf-8") as f:
        return json.load(f)


def validate(data, path):
    """Return a list of 'path: location: message' strings."""
    full = schema()
    kind = "workspaceFile" if "workspace" in data else "repoFile"
    sub = {"$schema": full["$schema"], "$defs": full["$defs"], "$ref": f"#/$defs/{kind}"}
    validator = jsonschema.Draft202012Validator(sub)
    errors = []
    for err in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        loc = ".".join(str(p) for p in err.absolute_path) or "(top)"
        msg = err.message
        if err.validator == "unevaluatedProperties":
            msg = "unknown key(s): " + msg.split("(")[-1].rstrip(")").replace(" were unexpected", "").replace(" was unexpected", "")
        errors.append(f"{path}: {loc}: {msg}")
    errors.extend(lint(data, path))
    return errors


def lint(data, path):
    """Rules the schema cannot express."""
    out = []
    blocks = []
    if "workspace" in data:
        blocks.append(("defaults", data.get("defaults") or {}))
        for name, entry in (data.get("repos") or {}).items():
            blocks.append((f"repos.{name}", entry or {}))
        names = set((data.get("repos") or {}).keys())
        for name, entry in (data.get("repos") or {}).items():
            for dep in (entry or {}).get("depends_on", []) or []:
                if dep not in names:
                    out.append(f"{path}: repos.{name}.depends_on: unknown repo '{dep}'")
        chains = data.get("toolchains") or {}
        for name, tc in chains.items():
            seen, cur = {name}, (tc or {}).get("extends")
            while cur:
                if cur not in chains:
                    out.append(f"{path}: toolchains.{name}.extends: unknown toolchain '{cur}'")
                    break
                if cur in seen:
                    out.append(f"{path}: toolchains.{name}.extends: cycle through '{cur}'")
                    break
                seen.add(cur)
                cur = (chains[cur] or {}).get("extends")
        for loc, block in blocks:
            tc = block.get("toolchain")
            if tc and tc not in chains:
                out.append(f"{path}: {loc}.toolchain: unknown toolchain '{tc}'")
        try:
            repo_order(data)
        except ConfigError as e:
            out.append(f"{path}: repos: {e}")
    else:
        blocks.append(("", data))
    for loc, block in blocks:
        git = block.get("git") or {}
        wob = git.get("work_order_branch")
        if isinstance(wob, str) and wob.startswith("{branch}/"):
            out.append(f"{path}: {loc + '.' if loc else ''}git.work_order_branch: '{wob}' puts a branch below the task branch; git cannot hold both. Use '{{branch}}-wo-{{nn}}'.")
        br = git.get("branch")
        if isinstance(br, str) and not any(k in br for k in ("{task}", "{ticket}", "{slug}")):
            out.append(f"{path}: {loc + '.' if loc else ''}git.branch: '{br}' has no {{ticket}} or {{slug}}; every task would share one branch.")
        if isinstance(br, str) and br.startswith(LOCAL_PREFIX):
            out.append(f"{path}: {loc + '.' if loc else ''}git.branch: '{br}' is pushed and opens the PR; '{LOCAL_PREFIX}' names local work branches only. Use the repo's convention or '{{type}}/{{ticket}}'.")
        for key, val in (git.get("branch_types") or {}).items():
            if key not in BRANCH_TYPES:
                out.append(f"{path}: {loc + '.' if loc else ''}git.branch_types.{key}: not a conventional type ({', '.join(BRANCH_TYPES)}).")
            elif isinstance(val, str) and val.rstrip("/") == LOCAL_PREFIX.rstrip("/"):
                out.append(f"{path}: {loc + '.' if loc else ''}git.branch_types.{key}: '{val}' would push a tempo/ branch.")
        for key, tpl in (("git.commit.message", (git.get("commit") or {}).get("message")),
                         ("pr.title", (block.get("pr") or {}).get("title"))):
            if isinstance(tpl, str) and LOCAL_ID.search(tpl):
                out.append(f"{path}: {loc + '.' if loc else ''}{key}: '{tpl}' holds a local task id; use {{ticket}}.")
        task = block.get("task") or {}
        if task.get("trackers") and ("tracker" in task or "ticket_pattern" in task):
            out.append(f"{path}: {loc + '.' if loc else ''}task: trackers replaces tracker and ticket_pattern; remove those two.")
        for i, tr in enumerate(task.get("trackers") or [], 1):
            where = f"{path}: {loc + '.' if loc else ''}task.trackers[{i}]"
            try:
                re.compile(tr.get("ticket_pattern", ""))
            except re.error as e:
                out.append(f"{where}.ticket_pattern: not a regex ({e}).")
            sync = tr.get("sync") or {}
            if sync and tr.get("type") not in ("jira", "github"):
                out.append(f"{where}.sync: TEMPO syncs jira and github tickets only, not {tr.get('type')}.")
            if sync.get("project") and tr.get("type") != "github":
                out.append(f"{where}.sync.project: a GitHub Projects board; only a github tracker has one.")
    return out


# ---------- trackers ----------

def trackers(cfg):
    """task.trackers, or the older single task.tracker and task.ticket_pattern as a list of one."""
    t = cfg.get("task") or {}
    return t.get("trackers") or [{"type": t.get("tracker", "none"), "ticket_pattern": t.get("ticket_pattern")}]


def find_ticket(cfg, text):
    """(key, tracker) for the ticket that appears first in text; a tie goes to the earlier tracker."""
    best = None
    for tr in trackers(cfg):
        for m in re.finditer(tr.get("ticket_pattern") or r"(?!x)x", text):
            key = m.group(1) if m.groups() else m.group(0)
            if LOCAL_ID.fullmatch(key):
                continue  # a local T-NNN id is never a ticket
            if best is None or m.start() < best[0]:
                best = (m.start(), key, tr)
            break
    return (best[1], best[2]) if best else (None, None)


def _run(cmd, cwd):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
    if r.returncode:
        lines = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(lines[-1] if lines else f"exit {r.returncode}")
    return r.stdout


def find_dupes(ticket, own, prs, heads):
    """DUPE lines for open PRs (gh pr list JSON, any state) and remote heads (ls-remote text) that name the
    ticket, other than the task's own branches. A branch whose PRs are all merged or closed is stale, not a
    dupe. PD-12 never matches PD-123."""
    key = re.compile(r"(?<![A-Za-z0-9])" + re.escape(ticket) + r"(?![0-9])", re.I)
    out, seen = [], set(own)
    for pr in prs:
        ref = pr.get("headRefName") or ""
        if pr.get("state", "OPEN") != "OPEN":
            continue
        if ref not in seen and (key.search(ref) or key.search(pr.get("title") or "")):
            out.append(f"DUPE: pr {ref} {pr.get('url') or ''}".rstrip())
            seen.add(ref)
    seen |= {pr.get("headRefName") for pr in prs}  # an open one already printed; the rest ended
    for line in heads.splitlines():
        ref = line.split("\t", 1)[-1].removeprefix("refs/heads/")
        if ref not in seen and key.search(ref):
            out.append(f"DUPE: branch {ref}")
            seen.add(ref)
    return out


def atl_script():
    """The newest installed atlassian-multi atl.py, or None."""
    cache = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "plugins" / "cache"
    hits = list(cache.glob("*/atlassian-multi/*/skills/atlassian-multi/scripts/atl.py"))
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def github_move(cwd, number, project, status):
    owner, num = project.rsplit("/", 1)
    url = _run(["gh", "issue", "view", number, "--json", "url", "-q", ".url"], cwd).strip()
    # item-add returns the issue's existing item when it is already on the board
    item = json.loads(_run(["gh", "project", "item-add", num, "--owner", owner, "--url", url, "--format", "json"], cwd))["id"]
    pid = json.loads(_run(["gh", "project", "view", num, "--owner", owner, "--format", "json"], cwd))["id"]
    fields = json.loads(_run(["gh", "project", "field-list", num, "--owner", owner, "--format", "json", "--limit", "100"], cwd))["fields"]
    field = next((f for f in fields if f.get("name") == "Status" and f.get("options")), None)
    if not field:
        raise RuntimeError(f"project {project} has no Status field")
    opt = next((o for o in field["options"] if o["name"].lower() == status.lower()), None)
    if not opt:
        raise RuntimeError(f"no status '{status}' on {project}; it has: " + ", ".join(o["name"] for o in field["options"]))
    _run(["gh", "project", "item-edit", "--id", item, "--project-id", pid, "--field-id", field["id"],
          "--single-select-option-id", opt["id"]], cwd)


def sync_ticket(cfg, cwd, event, text):
    """Print what was done. Never raises: a tracker that refuses never stops a task."""
    key, tr = find_ticket(cfg, text)
    if not key:
        return ["SYNC: OFF (no ticket in the request)"]
    sync = tr.get("sync") or {}
    status = sync.get(event)
    if not sync or not (status or (event == "start" and sync.get("assign"))):
        return [f"SYNC: OFF ({tr['type']} {key}: nothing set for {event})"]
    out = []
    if tr["type"] == "jira":
        atl = atl_script()
        if not atl:
            return [f"WARN: {key} not synced: atlassian-multi is not installed (claude plugin install atlassian-multi@jorgelrj-skills)"]
        base = [sys.executable, str(atl), "jira"]
        assign = lambda: _run(base + ["assign", key, "me"], cwd)
        move = lambda: _run(base + ["move", key, status], cwd)
    else:
        assign = lambda: _run(["gh", "issue", "edit", key, "--add-assignee", "@me"], cwd)
        project = sync.get("project")
        move = lambda: github_move(cwd, key, project, status) if project else None
    if event == "start" and sync.get("assign"):
        try:
            assign(); out.append(f"ASSIGNED: {key} to you")
        except Exception as e:
            out.append(f"WARN: assigning {key} failed: {e}")
    if status:
        if tr["type"] == "github" and not sync.get("project"):
            out.append(f"WARN: {key} not moved: sync.project names no GitHub Projects board")
        else:
            try:
                move(); out.append(f"MOVED: {key} -> {status}")
            except Exception as e:
                hint = " (gh needs the project scope: gh auth refresh -s project)" if "scope" in str(e) else ""
                out.append(f"WARN: moving {key} to {status} failed: {e}{hint}")
    return out


# ---------- discovery and merge ----------

def git_root(start):
    try:
        out = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True)
        return Path(out.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


def local_file(repo):
    """This machine's override file: the repo's own, else the main checkout's when repo is a linked worktree."""
    if (repo / LOCAL_FILE).is_file():
        return repo / LOCAL_FILE
    try:
        common = subprocess.run(["git", "-C", str(repo), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, check=True).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None
    main = Path(common).parent / LOCAL_FILE
    return main if Path(common).name == ".git" and main.is_file() else None


def find_workspace(start):
    cur = Path(start).resolve()
    for d in [cur, *cur.parents]:
        if (d / WORKSPACE_FILE).is_file():
            return d
    return None


def deep_merge(base, over):
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def toolchain_layer(ws, name, seen=None):
    chains = ws.get("toolchains") or {}
    if name not in chains:
        raise ConfigError(f"unknown toolchain '{name}'")
    seen = seen or set()
    if name in seen:
        raise ConfigError(f"toolchain cycle through '{name}'")
    seen.add(name)
    tc = dict(chains[name] or {})
    parent = tc.pop("extends", None)
    base = toolchain_layer(ws, parent, seen) if parent else {}
    return deep_merge(base, tc)


def repo_order(ws):
    repos = ws.get("repos") or {}
    order, state = [], {}

    def visit(n, trail):
        if state.get(n) == 1:
            raise ConfigError("depends_on cycle: " + " -> ".join(trail + [n]))
        if state.get(n) == 2:
            return
        state[n] = 1
        for d in (repos.get(n) or {}).get("depends_on", []) or []:
            if d in repos:
                visit(d, trail + [n])
        state[n] = 2
        order.append(n)

    for n in repos:
        visit(n, [])
    return order


def interpolate(value, ctx, where, errors):
    if isinstance(value, dict):
        return {k: interpolate(v, ctx, f"{where}.{k}" if where else k, errors) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate(v, ctx, f"{where}[{i}]", errors) for i, v in enumerate(value)]
    if isinstance(value, str):
        def sub(m):
            key = m.group(1)
            if key.startswith("env:"):
                name = key[4:]
                if re.search(r"(^|\.)env\.", where):
                    return "${" + name + "}"  # inside an env map: left for the shell to expand
                if name not in os.environ:
                    errors.append(f"{where}: environment variable {name} is not set")
                    return m.group(0)
                return os.environ[name]
            if ctx.get(key) is None:
                errors.append(f"{where}: ${{{key}}} has no value here")
                return m.group(0)
            return str(ctx[key])
        return INTERP.sub(sub, value)
    return value


def resolve(repo_arg):
    """Return (config, info). info lists the files used and warnings."""
    start = Path(repo_arg or ".").resolve()
    repo = git_root(start)
    ws_root = find_workspace(repo or start)
    info = {"repo": str(repo) if repo else None, "workspace": str(ws_root) if ws_root else None,
            "repo_name": None, "files": [str(DEFAULTS_PATH)], "warnings": []}
    errors = []

    defaults = load_yaml(DEFAULTS_PATH)
    defaults.pop("version", None)
    layers_before_tc = [defaults]
    layers_after_tc = []
    doc_layers = []  # (root, docs block); paths in a block are relative to its root
    ws = None
    if ws_root:
        wpath = ws_root / WORKSPACE_FILE
        ws = load_yaml(wpath)
        errors += validate(ws, wpath)
        info["files"].append(str(wpath))
        layers_before_tc.append(ws.get("defaults") or {})
        if ws.get("docs"):
            doc_layers.append((ws_root, ws["docs"]))
        if repo:
            for name, entry in (ws.get("repos") or {}).items():
                if (ws_root / entry.get("path", "")).resolve() == repo:
                    info["repo_name"] = name
                    e = {k: v for k, v in entry.items() if k not in ("path", "depends_on", "description", "docs")}
                    if entry.get("docs"):
                        doc_layers.append((repo, entry["docs"]))
                    layers_after_tc.append(e)
                    info["depends_on"] = entry.get("depends_on", []) or []
                    break
            else:
                info["warnings"].append(f"{repo} is not listed under repos: in {wpath}")
    if repo:
        rpath = repo / REPO_FILE
        lpath = repo / LEGACY_FILE
        if rpath.is_file():
            rc = load_yaml(rpath)
            errors += validate(rc, rpath)
            rc.pop("version", None)
            if rc.get("docs"):
                doc_layers.append((repo, rc.pop("docs")))
            layers_after_tc.append(rc)
            info["files"].append(str(rpath))
            if lpath.is_file():
                info["warnings"].append(f"{lpath} is ignored because {rpath} exists; delete it when convenient")
        elif lpath.is_file():
            rc, unmapped = migrate_md(lpath.read_text(encoding="utf-8"))
            rc.pop("version", None)
            layers_after_tc.append(rc)
            info["files"].append(str(lpath) + " (legacy, converted on the fly)")
            info["warnings"].append(f"{lpath} is the legacy format; run `tempo_config.py migrate {lpath} > {rpath}`")
            for u in unmapped:
                info["warnings"].append(f"{lpath}: unmapped line kept out of the config: {u}")
        mpath = local_file(repo)
        if mpath:
            mc = load_yaml(mpath)
            mc.setdefault("version", 1)  # optional here: the file only overrides
            errors += validate(mc, mpath)
            mc.pop("version", None)
            layers_after_tc.append(mc)
            info["files"].append(str(mpath))
            tracked = subprocess.run(["git", "-C", str(mpath.parents[1]), "ls-files", "--error-unmatch", str(LOCAL_FILE)],
                                     capture_output=True, text=True)
            if tracked.returncode == 0:
                info["warnings"].append(f"{mpath} is committed; it holds one machine's settings, so untrack it (git rm --cached) and ignore it")

    merged = {}
    for layer in layers_before_tc + layers_after_tc:
        merged = deep_merge(merged, layer)
    tc_name = merged.pop("toolchain", None)
    if tc_name:
        if not ws:
            errors.append(f"toolchain '{tc_name}' is set but no workspace file defines toolchains")
        else:
            try:
                tc = toolchain_layer(ws, tc_name)
                merged = {}
                for layer in layers_before_tc + [tc] + layers_after_tc:
                    merged = deep_merge(merged, layer)
                merged.pop("toolchain", None)
                info["toolchain"] = tc_name
            except ConfigError as e:
                errors.append(str(e))
    merged.setdefault("pr", {}).setdefault("base", merged.get("git", {}).get("base_branch"))
    br = (merged.get("git") or {}).get("branch")
    if isinstance(br, str) and "{type}" not in br and br.split("/", 1)[0] in TYPE_OF_PREFIX and "/" in br:
        info["warnings"].append(f"git.branch '{br}' fixes the prefix: bug fixes and chores get '{br.split('/', 1)[0]}/' too. "
                                "Use '{type}/...' (and git.branch_types for words like feature/ or bugfix/).")
    merged["docs"] = merge_docs(doc_layers)
    ctx = {"workspace": info["workspace"], "repo": info["repo"]}
    merged = interpolate(merged, ctx, "", errors)
    if ws and not repo:
        info["repos"] = [{"name": n, "path": str((ws_root / ws["repos"][n]["path"]).resolve()),
                          "depends_on": ws["repos"][n].get("depends_on", []) or []}
                         for n in repo_order(ws)]
    if errors:
        raise ConfigError("\n".join(errors))
    return merged, info


# ---------- project docs ----------

def merge_docs(layers):
    """Combine docs blocks. Paths add up; index and rules come from the last block that sets them."""
    out = {"sources": [], "index": list(DEFAULT_INDEX), "rules": True}
    for root, block in layers:
        out["sources"].append({"root": str(root), "paths": list(block.get("paths") or []),
                               "exclude": list(block.get("exclude") or [])})
        if block.get("index"):
            out["index"] = list(block["index"])
        if "rules" in block:
            out["rules"] = bool(block["rules"])
    return out


def _walk_docs(base):
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = sorted(d for d in dirnames if d not in DOC_SKIP_DIRS)
        for f in sorted(filenames):
            if Path(f).suffix.lower() in DOC_SUFFIXES:
                yield Path(dirpath) / f


def _matches(rel, pattern):
    if pattern.startswith("re:"):
        return re.search(pattern[3:], rel) is not None
    return Path(rel).match(pattern) or fnmatch_path(rel, pattern)


def fnmatch_path(rel, pattern):
    import fnmatch
    return fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(rel, pattern.rstrip("/") + "/*")


def expand_docs(docs):
    """Return doc files as absolute paths, index files first, without duplicates."""
    found = []
    for src in docs.get("sources", []):
        root = Path(src["root"])
        hits = []
        for pat in src["paths"]:
            if pat.startswith("re:"):
                hits += [f for f in _walk_docs(root) if re.search(pat[3:], f.relative_to(root).as_posix())]
            elif any(ch in pat for ch in "*?["):
                hits += [f for f in sorted(root.glob(pat)) if f.is_file()]
            else:
                target = (root / pat)
                if target.is_dir():
                    hits += list(_walk_docs(target))
                elif target.is_file():
                    hits.append(target)
        for f in hits:
            rel = f.relative_to(root).as_posix() if f.is_relative_to(root) else str(f)
            if any(_matches(rel, x) for x in src["exclude"]):
                continue
            found.append(f.resolve())
    seen, unique = set(), []
    for f in found:
        if f not in seen:
            seen.add(f); unique.append(f)
    index = [n.lower() for n in docs.get("index", DEFAULT_INDEX)]
    first = [f for f in unique if f.name.lower() in index]
    return first + [f for f in unique if f.name.lower() not in index]


# ---------- rendering ----------

# Local task ids (T-001 ...) are numbered per checkout: another machine running TEMPO on the same
# project has its own T-001. They name .tempo/ folders only, never a branch, commit, PR or tracker text.
LOCAL_ID = re.compile(r"\bT-\d+\b")

# Branches under tempo/ are TEMPO's own local work branches (work orders, repro). They never leave the
# machine: the task branch, the one that is pushed and opens the PR, follows the repo's convention.
LOCAL_PREFIX = "tempo/"

# Conventional Commits types, and the prefix words repos use for them on branches.
BRANCH_TYPES = ["feat", "fix", "chore", "docs", "refactor", "test", "perf", "build", "ci", "style", "revert"]
TYPE_OF_PREFIX = {"feat": "feat", "feature": "feat", "features": "feat", "story": "feat",
                  "fix": "fix", "bugfix": "fix", "bug": "fix", "chore": "chore", "docs": "docs", "doc": "docs",
                  "refactor": "refactor", "test": "test", "tests": "test", "perf": "perf", "build": "build",
                  "ci": "ci", "style": "style", "revert": "revert"}


def local_name(name):
    """A task branch from before 0.14.0 is itself under tempo/: keep one prefix, not tempo/tempo/."""
    while name.startswith(LOCAL_PREFIX * 2):
        name = name[len(LOCAL_PREFIX):]
    return name


def remote_branch_types(repo, limit=200):
    """The prefix word the repo's remote branches use for each type, e.g. {'feat': 'story', 'fix': 'bugfix'}.

    Reads the most recent remote branches; a word wins when it is the type's most used one. tempo/ and any
    prefix that is not a known type word are ignored. Returns {} when no remote branch carries a type word."""
    try:
        refs = subprocess.run(["git", "-C", str(repo), "for-each-ref", "--sort=-committerdate", "--format=%(refname)",
                               "refs/remotes"], capture_output=True, text=True, check=True).stdout.split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return {}
    counts = {}
    for r in refs[:limit]:
        name = r.split("/", 3)[-1] if r.count("/") >= 3 else ""
        word = name.split("/", 1)[0] if "/" in name else ""
        if word in TYPE_OF_PREFIX:
            counts[word] = counts.get(word, 0) + 1
    best = {}
    for word, n in counts.items():
        t = TYPE_OF_PREFIX[word]
        if n > counts.get(best.get(t), 0):
            best[t] = word
    return best


def slugify(text, limit=40):
    words = re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).split()
    out = ""
    for w in words:
        if len(out) + len(w) + (1 if out else 0) > limit:
            break
        out = f"{out}-{w}" if out else w
    return out or None


def branch_taken(repo, name):
    """True when a local branch or any remote-tracking branch already has this name."""
    try:
        refs = subprocess.run(["git", "-C", str(repo), "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes"],
                              capture_output=True, text=True, check=True).stdout.split()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False
    return any(r == f"refs/heads/{name}" or (r.startswith("refs/remotes/") and r.split("/", 3)[-1] == name) for r in refs)


def tidy(text):
    """Drop what an empty {ticket} leaves in a message: '()', '[]', '(#)', a leading ': ', double spaces."""
    text = re.sub(r"\s*[(\[][\s#:/-]*[)\]]", "", text)
    text = re.sub(r"^[\s:#/-]+", "", text)
    text = re.sub(r"[\s:#/-]+$", "", text)
    return re.sub(r"\s{2,}", " ", text)


def fill(template, values):
    def sub(m):
        k = m.group(1)
        return str(values[k]) if values.get(k) is not None else m.group(0)
    return re.sub(r"\{([a-z_]+)\}", sub, template)


def env_prefix(env):
    if not env:
        return ""
    def dq(v):  # double quotes, so ${VAR} from an env map still expands in the shell
        return '"' + re.sub(r'(["\\`])', r"\\\1", v) + '"'
    return "export " + " ".join(f"{k}={dq(v)}" for k, v in env.items()) + "; "


# ---------- worktree setup ----------

# Git-ignored files a build usually needs and a new worktree lacks.
SETUP_NAMES = {".fvm", ".env", ".env.local", ".env.development", ".env.development.local", ".env.test",
               ".env.test.local", "local.properties", "key.properties", ".npmrc", "google-services.json",
               "GoogleService-Info.plist"}


def worktree_gaps(repo, cfg):
    """Warn about ignored setup files in the checkout that worktree.copy/link do not bring into a worktree."""
    if not repo:
        return []
    out = subprocess.run(["git", "-C", str(repo), "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return []
    w = cfg.get("worktree") or {}
    covered = [c.rstrip("/") for c in (w.get("copy") or []) + (w.get("link") or [])]
    gaps = []
    for rel in out.stdout.splitlines():
        rel = rel.rstrip("/")
        parts = rel.split("/")
        if parts[-1] not in SETUP_NAMES or parts[0] == ".tempo" or "node_modules" in parts:
            continue
        if not any(rel == c or rel.startswith(c + "/") for c in covered):
            gaps.append(rel)
    return [f"{g} is git-ignored, so a new worktree will not have it; add it to worktree.link (or worktree.copy)"
            for g in sorted(gaps)]


# ---------- platform targets ----------

TEST_GLOBS = ["*_test.*", "*.test.*", "*.spec.*", "test_*.py", "*Test.java", "*Test.kt"]  # files a runner runs
PACKAGE_MARKERS = ["pubspec.yaml", "package.json", "go.mod", "Cargo.toml", "pyproject.toml", "pom.xml", "build.gradle", "build.gradle.kts"]


def full_bars(cfg):
    return (cfg.get("gates") or {}).get("full_bars")


def ci_gaps(cfg):
    """Settings that make the local tier or CI-WAIT a trap."""
    out, rounds = [], (cfg.get("limits") or {}).get("ci_rounds") or 0
    if full_bars(cfg) == "ci" and not rounds:
        out.append("gates.full_bars is ci but limits.ci_rounds is 0: nothing waits for the CI that now runs the "
                   "whole suites; set limits.ci_rounds (3 is a start)")
    if rounds and (cfg.get("pr") or {}).get("draft"):
        out.append("limits.ci_rounds waits for the PR to merge, and a draft PR never merges; set pr.draft: false")
    if rounds and (cfg.get("pr") or {}).get("tool") == "none":
        out.append("limits.ci_rounds is set but pr.tool is none: there is no PR to wait on")
    return out


def tracked_files(repo, ref=None):
    args = ["git", "-C", str(repo), "ls-tree", "-r", "--name-only", ref] if ref else ["git", "-C", str(repo), "ls-files"]
    out = subprocess.run(args, capture_output=True, text=True)
    if out.returncode != 0:
        raise ConfigError(f"cannot list files ({' '.join(args[3:])}): {out.stderr.strip()}")
    return out.stdout.splitlines()


def is_test(rel, globs):
    name = rel.rsplit("/", 1)[-1]
    return any(_matches(rel, g) or (("/" not in g) and fnmatch_path(name, g)) for g in globs)


def package_of(rel, packages):
    """The deepest package directory holding rel ('' for the repo root)."""
    best = None
    for pkg in packages:
        if pkg == "" or rel.startswith(pkg + "/"):
            if best is None or len(pkg) > len(best):
                best = pkg
    return best


def scoped_runs(tg, changed, files):
    """Group the tests a target should run by package. Changed test files run as they are;
    a changed source file runs the tests whose name mirrors it (foo.dart -> foo_test.dart)."""
    globs = tg.get("test_globs") or TEST_GLOBS
    markers = tg.get("package_markers") or PACKAGE_MARKERS
    packages = {f.rsplit("/", 1)[0] if "/" in f else "" for f in files if f.rsplit("/", 1)[-1] in markers}
    present = set(files)
    tests_by_stem = {}
    for f in files:
        if is_test(f, globs):
            stem = f.rsplit("/", 1)[-1].split(".", 1)[0]
            tests_by_stem.setdefault(stem, []).append(f)
    picked, unmapped = {}, []
    for rel in changed:
        pkg = package_of(rel, packages)
        if is_test(rel, globs):
            if rel in present:
                picked.setdefault(pkg, set()).add(rel)
            continue
        if re.search(r"(^|/)(test|tests|__tests__|spec|integration_test)/", rel):
            unmapped.append(rel)  # a helper or fixture many tests load: no single test mirrors it
            continue
        stem = rel.rsplit("/", 1)[-1].split(".", 1)[0]
        mirrors = [t for c in (f"{stem}_test", f"test_{stem}", stem) for t in tests_by_stem.get(c, [])
                   if package_of(t, packages) == pkg and t != rel]
        if mirrors:
            picked.setdefault(pkg, set()).update(mirrors)
        else:
            unmapped.append(rel)
    runs = []
    for pkg in sorted(picked, key=lambda x: x or ""):
        cut = len(pkg) + 1 if pkg else 0
        runs.append((pkg, sorted(t[cut:] for t in picked[pkg])))
    return runs, unmapped


# ---------- legacy migration ----------

LEGACY_MAP = {
    "test": ("commands", "test"), "test-one": ("commands", "test_one"), "build": ("commands", "build"),
    "typecheck": ("commands", "typecheck"), "lint": ("commands", "lint"), "run-app": ("commands", "run_app"),
    "base-branch": ("git", "base_branch"), "worktree-root": ("git", "worktree_root"),
    "max-parallel-builders": ("limits", "max_parallel_builders"), "review-rounds": ("limits", "review_rounds"),
    "qa-rounds": ("limits", "qa_rounds"), "repro-hypotheses": ("limits", "repro_hypotheses"),
    "repro-minutes": ("limits", "repro_minutes"), "pr-tool": ("pr", "tool"),
}
ASSIGN = re.compile(r"^([A-Z_][A-Z0-9_]*)=(\S+)\s+")


def migrate_md(text):
    cfg = {"version": 1}
    unmapped = []
    env = {}
    for line in text.splitlines():
        m = re.match(r"^\s*-\s*([A-Za-z0-9_/ -]+?):\s*(.*?)\s*$", line)
        if not m:
            continue
        key, val = m.group(1), m.group(2)
        if key in LEGACY_MAP:
            sec, k = LEGACY_MAP[key]
            if val in ("NIL", "", "none"):
                v = None
            elif sec == "limits":
                v = int(re.match(r"\d+", val).group(0))
            else:
                v = val.replace("{{pattern}}", "{pattern}").replace("<module>", "{module}")
            if sec == "commands" and v:
                while ASSIGN.match(v):
                    a = ASSIGN.match(v)
                    env[a.group(1)] = a.group(2)
                    v = v[a.end():]
            cfg.setdefault(sec, {})[k] = v
        elif key == "branch-prefix":
            base = val.split(" (")[0].strip()
            base = re.sub(r"[A-Z][A-Z0-9]+-\d+", "{ticket}", base)
            cfg.setdefault("git", {})["branch"] = base + "{ticket}" if base.endswith("/") else base
            if "{ticket}" in base:
                cfg.setdefault("task", {})["id"] = "ticket"
        elif key == "open-as-draft":
            cfg.setdefault("pr", {})["draft"] = val.lower().startswith("y")
        elif key == "commit-flag":
            cfg.setdefault("git", {}).setdefault("commit", {})["extra_args"] = [val.split()[0]]
        else:
            unmapped.append(f"{key}: {val}")
    if env:
        cfg["env"] = env
    return cfg, unmapped


# ---------- CLI ----------

class Parser(argparse.ArgumentParser):
    # Usage errors exit 1; 2 is reserved for a missing dependency (the orchestrator's uv fallback).
    def error(self, message):
        self.print_usage(sys.stderr)
        self.exit(1, f"{self.prog}: error: {message}\n")


def main(argv=None):
    p = Parser(prog="tempo_config.py", description=__doc__.split("\n")[0])
    p.add_argument("--repo", default=".")
    # --repo is also accepted after the subcommand; SUPPRESS keeps a root value when it is absent there.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", default=argparse.SUPPRESS)
    sp = p.add_subparsers(dest="cmd", required=True)
    add = lambda name: sp.add_parser(name, parents=[common])
    c = add("check"); c.add_argument("files", nargs="*")
    r = add("resolve"); r.add_argument("--format", choices=["json", "yaml"], default="json")
    n = add("names")
    n.add_argument("--task", help="the local task id; accepted for logs, never used in a name")
    n.add_argument("--type", default="feat", choices=BRANCH_TYPES,
                   help="Conventional Commits type of the change: feat, fix, chore ... (default feat)")
    n.add_argument("--ticket"); n.add_argument("--slug")
    n.add_argument("--suffix", help="appended to the task branch, e.g. s2 for a split task's second slice")
    n.add_argument("--branch", help="an existing task branch (from state): derive work-order and repro names from it")
    n.add_argument("--wo", type=int, nargs="*", default=[])
    m = add("cmd"); m.add_argument("name"); m.add_argument("--var", action="append", default=[])
    t = add("targets"); t.add_argument("--paths", nargs="*")
    t.add_argument("--ref", help="find test files in this commit (default: the files git tracks in the checkout)")
    t.add_argument("--full", action="store_true", help="print each target's full command, never the scoped one")
    t.add_argument("--critical", action="store_true", help="include the targets that run for critical changes only")
    t.add_argument("--final", action="store_true", help="include run: final targets (the integrate after the last wave)")
    t.add_argument("--scoped-only", action="store_true", help="never print a whole command: a `# DEFERRED whole suite` line instead")
    t.add_argument("--verify", action="store_true", help="/tempo:verify only: print whole commands even under gates.full_bars: verify")
    bs = add("bars"); bs.add_argument("--paths", nargs="*", default=[]); bs.add_argument("--critical", action="store_true")
    s = add("setup"); s.add_argument("--worktree", required=True)
    td = add("teardown"); td.add_argument("--worktree", required=True)
    add("repos")
    dc = add("docs"); dc.add_argument("--format", choices=["list", "json"], default="list")
    g = add("migrate"); g.add_argument("file")
    tk = add("ticket"); tk.add_argument("--text", required=True)
    du = add("dupes"); du.add_argument("--ticket", required=True)
    du.add_argument("--branch", action="append", required=True, help="the task's own branch; repeat for a split task's slices")
    sy = add("sync"); sy.add_argument("event", choices=["start", "pr", "merged"]); sy.add_argument("--text", required=True)
    a = p.parse_args(argv)

    try:
        if a.cmd == "check":
            if a.files:
                errs = []
                for f in a.files:
                    errs += validate(load_yaml(f), f)
                if errs:
                    print("\n".join(errs)); print(f"FAIL: {len(errs)} finding(s)"); return 1
                print(f"PASS: {len(a.files)} file(s)"); return 0
            cfg, info = resolve(a.repo)
            if " " in (info.get("repo") or ""):
                info["warnings"].append(f"repo path '{info['repo']}' contains a space: melos splits it on Windows; "
                                        "a checkout path without spaces avoids that")
            for w in info["warnings"] + worktree_gaps(info.get("repo"), cfg) + ci_gaps(cfg):
                print("WARN: " + w)
            print("PASS: " + ", ".join(info["files"])); return 0

        if a.cmd == "migrate":
            cfg, unmapped = migrate_md(Path(a.file).read_text(encoding="utf-8"))
            out = "# Converted from " + a.file + " by tempo_config.py migrate.\n"
            out += "# yaml-language-server: $schema=" + str(SCHEMA_PATH) + "\n"
            out += yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=1000)
            for u in unmapped:
                out += f"# UNMAPPED (move by hand): {u}\n"
            sys.stdout.write(out)
            errs = validate(cfg, a.file + " (converted)")
            for e in errs:
                sys.stderr.write(e + "\n")
            return 1 if errs else 0

        cfg, info = resolve(a.repo)
        for w in info["warnings"]:
            sys.stderr.write("WARN: " + w + "\n")

        if a.cmd == "resolve":
            doc = {"config": cfg, "sources": info}
            if a.format == "json":
                print(json.dumps(doc, indent=2, ensure_ascii=False))
            else:
                sys.stdout.write(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=1000))
            return 0

        if a.cmd == "names":
            git, pr = cfg["git"], cfg["pr"]
            ticket = a.ticket if a.ticket and not LOCAL_ID.fullmatch(a.ticket) else None
            slug = slugify(a.slug)
            ref = ticket or slug or a.branch
            if not ref:
                print("names: no ticket key and no --slug. Pass --slug <a few words on the change>; "
                      "a local task id never names a branch.", file=sys.stderr)
                return 1
            # The repo's convention: the config when a file sets the branch, else its remote branches' words.
            types = {k: str(v).strip("/") for k, v in (git.get("branch_types") or {}).items()}
            defaults = load_yaml(DEFAULTS_PATH).get("git", {})
            if git["branch"] != defaults.get("branch") or types:
                convention = "config"
            else:
                types = remote_branch_types(info.get("repo") or a.repo)
                convention = ("remote branches: " + ", ".join(f"{w}/ for {t}" for t, w in sorted(types.items()))
                              if types else "default {type}/{ticket}")
            # {task} is kept for old configs and means the same as {ticket} here.
            vals = {"ticket": ref, "task": ref, "slug": slug or ref, "type": types.get(a.type, a.type)}
            branch = a.branch or fill(git["branch"], vals) + (f"-{a.suffix}" if a.suffix else "")
            if branch.startswith(LOCAL_PREFIX) and not a.branch:
                print(f"names: git.branch makes '{branch}'. The task branch is pushed and opens the PR, and "
                      f"'{LOCAL_PREFIX}' names local work branches only. Set git.branch to the repo's convention "
                      "or '{type}/{ticket}'.", file=sys.stderr)
                return 1
            if not ticket and not a.branch:
                # A slug is not unique the way a ticket key is: never reuse a branch someone already has.
                n, base = 2, branch
                while branch_taken(info.get("repo") or a.repo, branch):
                    branch, n = f"{base}-{n}", n + 1
            vals["branch"] = branch
            vals["name"] = branch.split("/", 1)[1] if "/" in branch else branch  # feat/AV-1 -> AV-1
            text = {"ticket": ticket or "", "task": ticket or "", "slug": slug or ""}
            out = {"type": a.type, "ticket": ticket, "slug": slug, "branch": branch, "integration_branch": branch,
                   "branch_convention": convention,
                   "local_only": branch.startswith(LOCAL_PREFIX),
                   "repro_branch": local_name(fill(git["repro_branch"], vals)),
                   "work_order_branches": {f"WO-{w:02d}": local_name(fill(git["work_order_branch"], {**vals, "nn": f"{w:02d}"})) for w in a.wo},
                   "worktree_root": git["worktree_root"],
                   "commit_message": tidy(fill(git["commit"]["message"], text)),
                   "commit_language": git["commit"].get("language"),
                   "commit_extra_args": git["commit"].get("extra_args", []),
                   "pr_title": tidy(fill(pr["title"], text)), "pr_language": pr.get("language"),
                   "pr_base": pr.get("base"), "pr_draft": pr.get("draft"), "pr_tool": pr.get("tool")}
            print(json.dumps(out, indent=2, ensure_ascii=False)); return 0

        if a.cmd == "cmd":
            commands = cfg.get("commands") or {}
            command = commands.get(a.name)
            if a.name == "test_one" and full_bars(cfg) == "ci" and commands.get("test_local"):
                command = commands["test_local"]  # the local tier: what CI runs is not run here
            if command is None:
                print(f"NIL: command '{a.name}' is not set", file=sys.stderr); return 1
            vals = dict(v.split("=", 1) for v in a.var)
            print(env_prefix(cfg.get("env")) + fill(command, vals)); return 0

        if a.cmd == "targets":
            files = None
            for tg in cfg.get("targets") or []:
                run = tg.get("run", "critical" if tg.get("advisory") else "routine")
                if run == "ci" and not a.verify:
                    continue  # never on this machine: the PR's CI runs it
                if not (a.critical or a.full) and (run == "critical" or (run == "final" and not a.final)):
                    continue
                tail = "\tadvisory" if tg.get("advisory") else ""
                full = f"{tg['name']}\t{env_prefix(cfg.get('env'))}{tg['command']}{tail}"
                if a.scoped_only or (full_bars(cfg) == "verify" and not a.verify):
                    full = f"{tg['name']}\t# DEFERRED whole suite{tail}"
                if full_bars(cfg) == "ci" and not a.verify:
                    full = f"{tg['name']}\t# DEFERRED to CI{tail}"  # not even scoped: the PR's CI runs it
                if a.paths is None:
                    print(full); continue
                hit = [f for f in a.paths if any(_matches(f, pat) for pat in tg["paths"])]
                if not hit:
                    continue
                if full_bars(cfg) == "ci" and not a.verify:
                    print(full); continue
                if a.full or not tg.get("scoped_command"):
                    print(full); continue
                if files is None:
                    files = tracked_files(info["repo"] or a.repo, a.ref)
                runs, unmapped = scoped_runs(tg, hit, files)
                for pkg, tests in runs:
                    cmd = fill(tg["scoped_command"], {"package": pkg or ".", "tests": " ".join(shlex.quote(t) for t in tests)})
                    print(f"{tg['name']}\t{env_prefix(cfg.get('env'))}{cmd}{tail}")
                if unmapped:
                    print(f"{tg['name']}\t# NO-TESTS for {len(unmapped)} changed file(s): {' '.join(unmapped[:10])}"
                          f"{' ...' if len(unmapped) > 10 else ''}{tail}")
            return 0

        if a.cmd == "bars":
            gates = cfg.get("gates") or {}
            hit = [f for f in a.paths if any(_matches(f, pat) for pat in gates.get("full_paths") or [])]
            if gates.get("full_bars") == "ci":  # the local tier: whole suites, build and targets run in the PR's CI
                print("BARS: LOCAL  WHY: gates.full_bars is ci")
                print("DEFERRED: ci" + (" (critical change)" if a.critical else ""))
            elif gates.get("full_bars") == "verify":  # the whole suite never runs inside the task
                print("BARS: NARROW  WHY: gates.full_bars is verify")
                if a.critical:
                    print("DEFERRED: critical change")
                elif hit:
                    print(f"DEFERRED: gates.full_paths matches {' '.join(hit[:5])}")
            elif gates.get("full_bars") == "integrate":
                print("BARS: FULL  WHY: gates.full_bars is integrate")
            elif a.critical:
                print("BARS: FULL  WHY: critical change")
            elif hit:
                print(f"BARS: FULL  WHY: gates.full_paths matches {' '.join(hit[:5])}")
            else:
                print("BARS: NARROW  WHY: routine change")
            tests = cfg.get("tests") or {}
            for f in tests.get("always") or []:
                print(f"ALWAYS: {f}")
            slow = tests.get("slow") or []
            if slow and a.paths:
                # A slow file runs whole when changed or when its mirror source (foo.dart -> foo_test.dart) changed.
                runs, _ = scoped_runs({}, a.paths, tracked_files(info["repo"] or a.repo) + slow)
                hit = set(a.paths) | {f"{pkg}/{t}" if pkg else t for pkg, ts in runs for t in ts}
                for f in slow:
                    if f in hit:
                        print(f"SLOW: {f}")
            return 0

        if a.cmd == "dupes":
            cwd = info.get("repo") or a.repo
            prs, heads = None, None
            try:
                prs = json.loads(_run(["gh", "pr", "list", "--state", "all", "--limit", "200", "--search", a.ticket,
                                       "--json", "number,headRefName,url,title,state"], cwd) or "[]")
            except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as e:
                print(f"WARN: open PRs not checked: gh did not answer ({e})")
            try:
                heads = _run(["git", "ls-remote", "--heads", "origin"], cwd)
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as e:
                print(f"WARN: remote branches not checked: origin did not answer ({e})")
            found = find_dupes(a.ticket, a.branch, prs or [], heads or "")
            for line in found:
                print(line)
            return 3 if found else 0

        if a.cmd == "teardown":
            wt = Path(a.worktree)
            w = cfg.get("worktree") or {}
            env = {**(cfg.get("env") or {}), **(w.get("env") or {})}
            name = re.sub(r"[^a-z0-9]+", "_", wt.name.lower()).strip("_")
            print("\n".join(f"(cd {shlex.quote(str(wt))} && {env_prefix(env)}{fill(c, {'worktree': name})})"
                            for c in w.get("teardown", [])) or "# no worktree teardown configured"); return 0

        if a.cmd == "setup":
            wt, repo = Path(a.worktree), Path(info["repo"] or ".")
            w = cfg.get("worktree") or {}
            steps = []
            for f in w.get("copy", []):
                steps.append(f"if [ -e {shlex.quote(str(repo / f))} ]; then mkdir -p {shlex.quote(str((wt / f).parent))} && cp -R {shlex.quote(str(repo / f))} {shlex.quote(str(wt / f))}; else echo 'WARN: missing {f}' >&2; fi")
            for f in w.get("link", []):
                steps.append(f"mkdir -p {shlex.quote(str((wt / f).parent))} && ln -sfn {shlex.quote(str(repo / f))} {shlex.quote(str(wt / f))}")
            env = {**(cfg.get("env") or {}), **(w.get("env") or {})}
            name = re.sub(r"[^a-z0-9]+", "_", wt.name.lower()).strip("_")
            for cmd in w.get("setup", []):
                steps.append(f"(cd {shlex.quote(str(wt))} && {env_prefix(env)}{fill(cmd, {'worktree': name})})")
            print("\n".join(steps) if steps else "# no worktree setup configured"); return 0

        if a.cmd == "docs":
            files = expand_docs(cfg.get("docs") or {})
            for src in (cfg.get("docs") or {}).get("sources", []):
                for pat in src["paths"]:
                    if not pat.startswith("re:") and not any(ch in pat for ch in "*?[") and not (Path(src["root"]) / pat).exists():
                        sys.stderr.write(f"WARN: docs path not found: {Path(src['root']) / pat}\n")
            if a.format == "json":
                print(json.dumps({"rules": cfg["docs"]["rules"], "files": [str(f) for f in files]}, indent=2, ensure_ascii=False))
            else:
                print("\n".join(str(f) for f in files))
            return 0

        if a.cmd == "ticket":
            key, tr = find_ticket(cfg, a.text)
            print(f"TICKET: {key}\nTRACKER: {tr['type']}" if key else "TICKET: NONE"); return 0

        if a.cmd == "sync":
            print("\n".join(sync_ticket(cfg, info.get("repo") or a.repo, a.event, a.text))); return 0

        if a.cmd == "repos":
            if not info.get("workspace"):
                print("NIL: no workspace file found", file=sys.stderr); return 1
            ws = load_yaml(Path(info["workspace"]) / WORKSPACE_FILE)
            for name in repo_order(ws):
                e = ws["repos"][name]
                deps = ", ".join(e.get("depends_on", []) or []) or "-"
                print(f"{name}\t{(Path(info['workspace']) / e['path']).resolve()}\tdepends_on: {deps}")
            return 0
    except ConfigError as e:
        print(str(e)); print("FAIL"); return 1
    return 1


if __name__ == "__main__":
    sys.exit(main())
