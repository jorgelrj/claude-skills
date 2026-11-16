#!/usr/bin/env python3
"""Check TEMPO artifacts against the document standard (structure only).

Usage: check_doc.py <file.md> [<file.md> ...]
Exit 0 = PASS, 1 = FAIL (findings printed as file:line: RULE: message), 2 = usage error.

The section list for each document type is read from the matching template in
../../artifact-templates/templates/, so editing a template changes what is checked.
Documents in the pre-0.6.0 ICAO layout are reported as LEGACY and pass.
"""
import os
import re
import sys

if sys.platform == "win32":  # the console code page cannot carry every character a task or a hook holds
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "artifact-templates", "templates"))

TITLE_RE = re.compile(r"^#\s+([^:#]+?)\s*:")
SECTION_RE = re.compile(r"^##\s+(\d{1,2})\s+(.+?)\s*$")
CHANGES_RE = re.compile(r"^##\s+Changes\s*$", re.IGNORECASE)
LEGACY_RE = re.compile(r"^[A-Z][A-Z ]+[A-Z]\s{2,}.*\bAMDT\s+\d+")
PLACEHOLDER_RE = re.compile(r"\{\{[^}]*\}\}")
AC_DEF_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+\[(AC-\d+)\]")


def norm(title):
    return re.sub(r"\s+", " ", title).strip().lower()


def load_templates():
    types = {}
    if not os.path.isdir(TEMPLATE_DIR):
        return types
    for name in sorted(os.listdir(TEMPLATE_DIR)):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(TEMPLATE_DIR, name), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        m = TITLE_RE.match(lines[0]) if lines else None
        if not m:
            continue
        sections = [(int(s.group(1)), s.group(2)) for s in map(SECTION_RE.match, lines) if s]
        types[norm(m.group(1))] = {"template": name, "sections": sections}
    return types


def check_file(path, templates):
    findings = []

    def add(lineno, rule, msg):
        findings.append(f"{path}:{lineno}: {rule}: {msg}")

    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        return [f"{path}:0: IO: {exc}"], False
    if not lines:
        add(1, "SHAPE", "document is empty")
        return findings, False
    if LEGACY_RE.match(lines[0]):
        return [], True

    m = TITLE_RE.match(lines[0])
    spec = templates.get(norm(m.group(1))) if m else None
    if spec is None:
        known = ", ".join(sorted(t.title() for t in templates)) or "none (templates missing)"
        add(1, "TITLE", f"line 1 must be '# <Type>: <task-id>' with a known type. Known: {known}")
        return findings, False

    # Collect ## sections, skipping fenced code.
    found, in_fence, current = [], False, None
    for i, line in enumerate(lines, start=1):
        if line.startswith("```"):
            in_fence = not in_fence
        if in_fence:
            if current:
                current["body"].append(line)
            continue
        s = SECTION_RE.match(line)
        if s or CHANGES_RE.match(line) or line.startswith("## "):
            current = {"num": int(s.group(1)) if s else None, "title": s.group(2) if s else line[3:].strip(),
                       "line": i, "body": [], "changes": bool(CHANGES_RE.match(line))}
            found.append(current)
        elif current:
            current["body"].append(line)
        if PLACEHOLDER_RE.search(line):
            add(i, "PLACEHOLDER", f"leftover template placeholder {PLACEHOLDER_RE.search(line).group(0)}")

    expected = spec["sections"]
    numbered = [f for f in found if not f["changes"]]
    for f in numbered:
        if f["num"] is None or (f["num"], norm(f["title"])) not in {(n, norm(t)) for n, t in expected}:
            add(f["line"], "SECTION", f"'{f['title']}' is not a section of {spec['template']}. Allowed extra: '## Changes'")
    got = [(f["num"], norm(f["title"])) for f in numbered]
    for n, t in expected:
        if (n, norm(t)) not in got:
            add(1, "SECTION", f"missing section '## {n} {t}' (template {spec['template']})")
    order = [g for g in got if g in {(n, norm(t)) for n, t in expected}]
    if order != sorted(order, key=lambda g: g[0]):
        add(1, "ORDER", "sections are not in template order")
    changes = [f for f in found if f["changes"]]
    if changes and found[-1] is not changes[-1]:
        add(changes[-1]["line"], "SECTION", "'## Changes' must be the last section")

    for f in found:
        if not any(b.strip() for b in f["body"]):
            add(f["line"], "EMPTY", f"section '{f['title']}' is empty. Write NIL")

    seen = {}
    for i, line in enumerate(lines, start=1):
        a = AC_DEF_RE.match(line)
        if a:
            if a.group(1) in seen:
                add(i, "TAG", f"{a.group(1)} is defined twice (first at line {seen[a.group(1)]})")
            seen.setdefault(a.group(1), i)
    return findings, False


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    templates = load_templates()
    all_findings, legacy = [], []
    for path in argv[1:]:
        f, is_legacy = check_file(path, templates)
        all_findings += f
        if is_legacy:
            legacy.append(path)
    for line in all_findings:
        print(line)
    for path in legacy:
        print(f"{path}: LEGACY: pre-0.6.0 ICAO layout, not checked")
    if all_findings:
        print(f"RESULT: FAIL ({len(all_findings)} findings)")
        return 1
    print("RESULT: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
