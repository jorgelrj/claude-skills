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

Run with `uv run tempo_config.py ...` (installs pyyaml and jsonschema on the fly)
or `python3 tempo_config.py ...` when both are installed.

Commands:
  check   [FILE ...]                     validate files (default: the ones that apply to --repo)
  resolve [--format json|yaml]           print the merged config for --repo (or the workspace)
  names   --task ID [--ticket KEY] [--wo N ...]   print branch names, commit and PR title templates
  cmd     NAME [--var k=v ...]           print one command as a shell line, env exported first
  targets [--paths P ...]               print the platform test targets that apply to the changed paths
  setup   --worktree PATH                print the shell steps that prepare a new worktree
  repos                                  list workspace repos in dependency order
  docs    [--format list|json]           list the project's doc files (config docs:), index files first
  migrate FILE                           convert a legacy .tempo/config.md to YAML on stdout
Common option: --repo PATH (default: current directory).
Exit codes: 0 ok, 1 invalid config or usage error, 2 missing dependency.
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
        if isinstance(br, str) and "{task}" not in br and "{ticket}" not in br:
            out.append(f"{path}: {loc + '.' if loc else ''}git.branch: '{br}' has no {{task}} or {{ticket}}; every task would share one branch.")
    return out


# ---------- discovery and merge ----------

def git_root(start):
    try:
        out = subprocess.run(["git", "-C", str(start), "rev-parse", "--show-toplevel"],
                             capture_output=True, text=True, check=True)
        return Path(out.stdout.strip()).resolve()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None


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
            cfg.setdefault("git", {})["branch"] = base + "{task}" if base.endswith("/") else base
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
    n.add_argument("--task", required=True); n.add_argument("--ticket"); n.add_argument("--slug")
    n.add_argument("--wo", type=int, nargs="*", default=[])
    m = add("cmd"); m.add_argument("name"); m.add_argument("--var", action="append", default=[])
    t = add("targets"); t.add_argument("--paths", nargs="*")
    s = add("setup"); s.add_argument("--worktree", required=True)
    add("repos")
    dc = add("docs"); dc.add_argument("--format", choices=["list", "json"], default="list")
    g = add("migrate"); g.add_argument("file")
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
            for w in info["warnings"]:
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
            vals = {"task": a.task, "ticket": a.ticket or a.task, "slug": a.slug}
            branch = fill(git["branch"], vals)
            vals["branch"] = branch
            out = {"branch": branch, "integration_branch": branch,
                   "repro_branch": fill(git["repro_branch"], vals),
                   "work_order_branches": {f"WO-{w:02d}": fill(git["work_order_branch"], {**vals, "nn": f"{w:02d}"}) for w in a.wo},
                   "worktree_root": git["worktree_root"],
                   "commit_message": fill(git["commit"]["message"], vals),
                   "commit_language": git["commit"].get("language"),
                   "commit_extra_args": git["commit"].get("extra_args", []),
                   "pr_title": fill(pr["title"], vals), "pr_language": pr.get("language"),
                   "pr_base": pr.get("base"), "pr_draft": pr.get("draft"), "pr_tool": pr.get("tool")}
            print(json.dumps(out, indent=2, ensure_ascii=False)); return 0

        if a.cmd == "cmd":
            command = (cfg.get("commands") or {}).get(a.name)
            if command is None:
                print(f"NIL: command '{a.name}' is not set", file=sys.stderr); return 1
            vals = dict(v.split("=", 1) for v in a.var)
            print(env_prefix(cfg.get("env")) + fill(command, vals)); return 0

        if a.cmd == "targets":
            for tg in cfg.get("targets") or []:
                if a.paths is None or any(_matches(f, pat) for f in a.paths for pat in tg["paths"]):
                    print(f"{tg['name']}\t{env_prefix(cfg.get('env'))}{tg['command']}")
            return 0

        if a.cmd == "setup":
            wt, repo = Path(a.worktree), Path(info["repo"] or ".")
            w = cfg.get("worktree") or {}
            steps = []
            for f in w.get("copy", []):
                steps.append(f"if [ -e {shlex.quote(str(repo / f))} ]; then mkdir -p {shlex.quote(str((wt / f).parent))} && cp -R {shlex.quote(str(repo / f))} {shlex.quote(str(wt / f))}; else echo 'WARN: missing {f}' >&2; fi")
            for f in w.get("link", []):
                steps.append(f"mkdir -p {shlex.quote(str((wt / f).parent))} && ln -sfn {shlex.quote(str(repo / f))} {shlex.quote(str(wt / f))}")
            env = {**(cfg.get("env") or {}), **(w.get("env") or {})}
            for cmd in w.get("setup", []):
                steps.append(f"(cd {shlex.quote(str(wt))} && {env_prefix(env)}{cmd})")
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
