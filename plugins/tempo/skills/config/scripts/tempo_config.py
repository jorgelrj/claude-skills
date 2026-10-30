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
  names   [--type T] [--ticket KEY] [--slug S] [--suffix X] [--branch B] [--wo N ...]
                                         print branch names, commit and PR title templates. Names carry the
                                         ticket key, else the slug; a local T-NNN id never leaves .tempo/.
                                         The task branch follows the repo's convention (config, else the
                                         prefixes of its remote branches, else {type}/{ticket}); tempo/ names
                                         are local work branches only and never name the task branch
  cmd     NAME [--var k=v ...]           print one command as a shell line, env exported first
  targets [--paths P ...] [--ref REF] [--full] [--critical]
                                         print the platform test runs for the changed paths: scoped to the
                                         tests those paths touch or mirror when a target has scoped_command.
                                         Targets with run: critical (advisory targets by default) print only
                                         with --critical or --full
  bars    [--paths P ...] [--critical]   print the bars an integrate runs: BARS: FULL|NARROW and why
  setup   --worktree PATH                print the shell steps that prepare a new worktree
  teardown --worktree PATH               print the shell steps that release a worktree's resources
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
    bs = add("bars"); bs.add_argument("--paths", nargs="*", default=[]); bs.add_argument("--critical", action="store_true")
    s = add("setup"); s.add_argument("--worktree", required=True)
    td = add("teardown"); td.add_argument("--worktree", required=True)
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
            for w in info["warnings"] + worktree_gaps(info.get("repo"), cfg):
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
            command = (cfg.get("commands") or {}).get(a.name)
            if command is None:
                print(f"NIL: command '{a.name}' is not set", file=sys.stderr); return 1
            vals = dict(v.split("=", 1) for v in a.var)
            print(env_prefix(cfg.get("env")) + fill(command, vals)); return 0

        if a.cmd == "targets":
            files = None
            for tg in cfg.get("targets") or []:
                if not (a.critical or a.full) and tg.get("run", "critical" if tg.get("advisory") else "routine") == "critical":
                    continue
                tail = "\tadvisory" if tg.get("advisory") else ""
                full = f"{tg['name']}\t{env_prefix(cfg.get('env'))}{tg['command']}{tail}"
                if a.paths is None:
                    print(full); continue
                hit = [f for f in a.paths if any(_matches(f, pat) for pat in tg["paths"])]
                if not hit:
                    continue
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
            if gates.get("full_bars") == "integrate":
                print("BARS: FULL  WHY: gates.full_bars is integrate")
            elif a.critical:
                print("BARS: FULL  WHY: critical change")
            elif hit:
                print(f"BARS: FULL  WHY: gates.full_paths matches {' '.join(hit[:5])}")
            else:
                print("BARS: NARROW  WHY: routine change")
            return 0

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
