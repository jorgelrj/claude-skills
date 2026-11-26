#!/usr/bin/env python3
"""Check TEMPO artifacts against the document standard (structure only).

Usage: check_doc.py <file.md> [<file.md> ...]
Exit 0 = PASS, 1 = FAIL (findings printed as file:line: RULE: message), 2 = usage error.

The section list for each document type is read from the matching template in
../../artifact-templates/templates/, so editing a template changes what is checked.
Documents in the pre-0.6.0 ICAO layout are reported as LEGACY and pass.
A QA Report also gets rules METHOD, EVIDENCE, MISSING and RESULT: each criterion names a result
and a Method, a PASS cites its own qa/ file (qa/AC-n.* or qa/design/AC-n-*) that exists next to
the report, a + DESIGN line cites a qa/design/AC-n- file, Criteria results holds at least one
criterion line, and a PASS Result has no FAIL or BLOCKED criterion.
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
QA_AC_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+[*\[]*AC-\d+")  # any criterion-like line; QA_LINE_RE then rejects drift
QA_LINE_RE = re.compile(r"^\s*-\s+(AC-\d+):\s+(PASS|FAIL|BLOCKED)\.\s+Method:\s+"
                        r"(?:LIVE-API|LIVE-WEB|LIVE-MOBILE|LIVE-CLI|TEST \((?:cosmetic|additive|refactor|config|guard|docs|bar|race|external|fault)\))(?:\s*\+\s*(?:DESIGN-FLOW|DESIGN))?\.")
QA_EVIDENCE_RE = re.compile(r"Evidence:\s*(.*?)(?:\s+Supporting:|$)")
QA_PATH_RE = re.compile(r"qa/[^\s,;`'\")]+")


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

    if norm(m.group(1)) == "qa report":
        check_qa(lines, os.path.dirname(os.path.abspath(path)), add)
    return findings, False


def check_qa(lines, folder, add):
    """QA Report: each criterion line names a result and a Method, and a PASS cites its own saved qa/ file."""
    section, in_fence, crit_line, results, not_pass, result_pass = None, False, None, 0, [], None
    for i, line in enumerate(lines, start=1):
        if line.startswith("```"):
            in_fence = not in_fence
        if in_fence:
            continue
        if line.startswith("## "):
            s = SECTION_RE.match(line)
            section = norm(s.group(2)) if s else None
            if section == "criteria results":
                crit_line = i
            continue
        if section == "result" and result_pass is None and line.strip():
            result_pass = (i, bool(re.match(r"\s*PASS\b", line)))
        if section != "criteria results" or not QA_AC_RE.match(line):
            continue
        results += 1
        q = QA_LINE_RE.match(line)
        if not q:
            add(i, "METHOD", "criterion line must read '- AC-n: PASS|FAIL|BLOCKED. Method: "
                "LIVE-API|LIVE-WEB|LIVE-MOBILE|LIVE-CLI|TEST (<class>)[ + DESIGN| + DESIGN-FLOW]. ...'")
            continue
        tag = q.group(1)
        if q.group(2) != "PASS":
            not_pass.append(tag)
            continue
        e = QA_EVIDENCE_RE.search(line)
        paths = [p.rstrip(".") for p in QA_PATH_RE.findall(e.group(1))] if e else []
        # own files only: not qa/build-*, qa/progress.md, another criterion's file or an older round's qa/rN/
        own = re.compile(rf"qa/(?:design/)?{re.escape(tag)}[.-]")
        saved = [p for p in paths if own.match(p) and os.path.isfile(os.path.join(folder, p))]
        method = line.split("Method:", 1)[1].split(". ", 1)[0].strip()
        if not saved and method.startswith("TEST (") and re.search(r"\brun \S+ TREE [0-9a-f]{7,}", e.group(1) if e else ""):
            continue  # qa 2.1.1: a TEST criterion may cite a clean integrator run
        if not saved:
            add(i, "EVIDENCE", f"{tag} is PASS but its Evidence names no saved qa/{tag}.* or qa/design/{tag}-* "
                "file next to the report" + (f" (cited: {', '.join(paths)})" if paths else ""))
        elif "DESIGN" in line.split("Method:", 1)[1].split(". ", 1)[0] and not any(
                p.startswith(f"qa/design/{tag}-") for p in saved):
            add(i, "EVIDENCE", f"{tag} is PASS + DESIGN but cites no saved qa/design/{tag}-* file")
    if crit_line is not None and results == 0:
        add(crit_line, "MISSING", "Criteria results holds no '- AC-n:' criterion line")
    if result_pass and result_pass[1] and not_pass:
        add(result_pass[0], "RESULT", f"Result is PASS but {', '.join(not_pass)} are not")


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
