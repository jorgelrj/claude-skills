#!/usr/bin/env python3
"""Check TEMPO artifacts against the ICAO-style document standard.

Usage: check_doc.py <file.md> [<file.md> ...]
Exit 0 = PASS, 1 = FAIL (findings printed as file:line: RULE: message), 2 = usage error.

The section list for each document type is read from the matching template in
../../artifact-templates/templates/, so editing a template changes what is checked.
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.normpath(os.path.join(HERE, "..", "..", "artifact-templates", "templates"))

SECTION_RE = re.compile(r"^(\d{1,2})\s{2,}([A-Z][A-Z0-9 &/'-]*[A-Z0-9])(\s{2,}.*)?\s*$")
PARA_RE = re.compile(r"^\s*(\d{1,2}(?:\.\d+)+)\s+(.*)$")
AMDT_HEADER_RE = re.compile(r"\bAMDT\s+(\d+)\b")
AMDT_LOG_RE = re.compile(r"^AMDT\s+(\d+)\s{2,}(\d{4}-\d{2}-\d{2})\s{2,}\S")
WAIVE_RE = re.compile(r"<!--\s*icao-waive:\s*([A-Z0-9.-]+)")
PLACEHOLDER_RE = re.compile(r"\{\{[^}]*\}\}")
GUIDE_RE = re.compile(r"<!--(?!\s*icao-waive).*?-->")

OBLIGATION_WORDS = [r"must", r"need to", r"needs to", r"have to", r"has to", r"required to", r"ought to"]
VAGUE_WORDS = [
    # quality
    "fast", "slow", "quickly", "properly", "correctly", "appropriate", "appropriately",
    "reasonable", "robust", "clean", "nice", "good", "better", "simple", "easy",
    "intuitive", "user-friendly", "seamless", "seamlessly",
    # quantity
    "some", "several", "many", "few", "a lot", "various", "a bit", "minor",
    # scope
    "as needed", "if needed", "where necessary", "as appropriate", "and so on", "etc",
    "other stuff",
    # hedges
    "should probably", "maybe", "perhaps", "might want to", "try to", "ideally", "hopefully",
]
LOWER_NORMATIVE_RE = re.compile(r"\b(shall not|shall|should|may)\b")


def words_re(words):
    return re.compile(r"(?<![\w-])(" + "|".join(re.escape(w) if " " not in w and "-" not in w else w.replace(" ", r"\s+") for w in words) + r")(?![\w-])", re.IGNORECASE)


OBLIGATION_RE = re.compile(r"(?<![\w-])(" + "|".join(w.replace(" ", r"\s+") for w in OBLIGATION_WORDS) + r")(?![\w-])", re.IGNORECASE)
VAGUE_RE = words_re(VAGUE_WORDS)


def strip_inline(text):
    """Remove code spans, quoted strings, HTML comments and AC tags before word checks."""
    text = GUIDE_RE.sub("", text)
    text = re.sub(r"`[^`]*`", "", text)
    text = re.sub(r"\"[^\"]*\"", "", text)
    text = re.sub(r"\[[A-Z]+-\d+\]", "", text)
    return text


def load_templates():
    types = {}
    if not os.path.isdir(TEMPLATE_DIR):
        return types
    for name in sorted(os.listdir(TEMPLATE_DIR)):
        if not name.endswith(".md"):
            continue
        with open(os.path.join(TEMPLATE_DIR, name), encoding="utf-8") as fh:
            lines = fh.read().splitlines()
        if not lines:
            continue
        doc_type = re.split(r"\s{2,}", lines[0].strip())[0]
        sections = []
        in_fence = False
        has_log = False
        for line in lines:
            if line.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            m = SECTION_RE.match(line)
            if m:
                sections.append((int(m.group(1)), m.group(2).strip()))
            if line.strip() == "AMENDMENT LOG":
                has_log = True
        types[doc_type] = {"template": name, "sections": sections, "has_log": has_log}
    return types


def check_file(path, templates):
    findings = []

    def add(lineno, rule, msg, raw=""):
        w = WAIVE_RE.search(raw)
        if w and w.group(1) in (rule, rule.split(".")[0]):
            return
        findings.append(f"{path}:{lineno}: {rule}: {msg}")

    try:
        with open(path, encoding="utf-8") as fh:
            lines = fh.read().splitlines()
    except OSError as exc:
        return [f"{path}:0: IO: {exc}"]
    if not lines:
        return [f"{path}:1: 2.2: document is empty"]

    # 1 Header
    doc_type = re.split(r"\s{2,}", lines[0].strip())[0]
    spec = templates.get(doc_type)
    if spec is None:
        add(1, "1.1", f"unknown document type '{doc_type}'. Known: {', '.join(sorted(templates)) or 'none (templates missing)'}")
        return findings

    # Collect sections and their bodies, skipping fenced code
    found = []  # (number, title, lineno, body_lines)
    in_fence = False
    log_start = None
    current = None
    for i, line in enumerate(lines, start=1):
        if line.startswith("```"):
            in_fence = not in_fence
            if current is not None:
                current[3].append((i, line, True))
            continue
        if line.strip() == "AMENDMENT LOG" and not in_fence:
            log_start = i
            current = None
            continue
        m = SECTION_RE.match(line) if not in_fence else None
        if m and log_start is None:
            current = [int(m.group(1)), m.group(2).strip(), i, []]
            found.append(current)
            continue
        if current is not None:
            current[3].append((i, line, in_fence))

    # 2.2 sections present, in order, with template numbers
    expected = spec["sections"]
    found_keys = [(n, t) for n, t, _, _ in found]
    for num, title in expected:
        if (num, title) not in found_keys:
            add(1, "2.2", f"missing section '{num}  {title}' (template {spec['template']})")
    exp_order = [k for k in found_keys if k in expected]
    if exp_order != [k for k in expected if k in found_keys]:
        add(1, "2.2", "sections are out of template order")
    for n, t, ln, _ in found:
        if (n, t) not in expected:
            add(ln, "2.2", f"section '{n}  {t}' is not in template {spec['template']}")

    # 2.3 empty section
    for n, t, ln, body in found:
        content = [l for _, l, _ in body if GUIDE_RE.sub("", l).strip()]
        if not content:
            add(ln, "2.3", f"section {n} {t} is empty. Write NIL if there is nothing to say.")

    # Line checks
    in_fence = False
    section_title = None
    for i, line in enumerate(lines, start=1):
        if line.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or i <= 3:
            continue
        sm = SECTION_RE.match(line)
        if sm:
            section_title = sm.group(2)
            continue
        if PLACEHOLDER_RE.search(line):
            add(i, "2.2", f"template placeholder left in document: {PLACEHOLDER_RE.search(line).group(0)}", line)
        text = strip_inline(line)
        if not text.strip():
            continue
        # 3.2 obligation words
        for m in OBLIGATION_RE.finditer(text):
            add(i, "3.2", f"'{m.group(1)}' used for obligation. Use SHALL / SHALL NOT / SHOULD / MAY.", line)
        # 3.1 normative words in lower case
        for m in LOWER_NORMATIVE_RE.finditer(text):
            add(i, "3.1", f"normative word '{m.group(1)}' SHALL be in capitals.", line)
        # 5.5 / 6.2 vague words
        for m in VAGUE_RE.finditer(text):
            rule = "5.5" if m.group(1).lower() in ("etc", "and so on") else "6.2"
            add(i, rule, f"unbound word '{m.group(1)}'. Name the thing, value or unit.", line)
        # 5.3 sentence length on numbered paragraphs
        pm = PARA_RE.match(line)
        if pm:
            count = len(re.findall(r"[A-Za-z0-9][\w'/.-]*", strip_inline(pm.group(2))))
            limit = 20 if section_title == "PROCEDURE" else 25
            if count > limit:
                add(i, "5.3", f"{count} words; limit is {limit} in {section_title}. Split into one instruction per line.", line)

    # 8 amendments
    if spec["has_log"]:
        hm = AMDT_HEADER_RE.search(lines[0])
        if not hm:
            add(1, "8.2", "header has no AMDT number")
        if log_start is None:
            add(len(lines), "8.3", "AMENDMENT LOG section is missing")
        elif hm:
            n = int(hm.group(1))
            logged = set()
            for j in range(log_start, len(lines)):
                lm = AMDT_LOG_RE.match(lines[j])
                if lm:
                    logged.add(int(lm.group(1)))
            for k in range(0, n + 1):
                if k not in logged:
                    add(log_start, "8.3", f"AMENDMENT LOG has no line for AMDT {k}")
            if logged and max(logged) > n:
                add(1, "8.2", f"header says AMDT {n} but the log reaches AMDT {max(logged)}")

    return findings


def main(argv):
    if len(argv) < 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    templates = load_templates()
    all_findings = []
    for path in argv[1:]:
        all_findings.extend(check_file(path, templates))
    for f in all_findings:
        print(f)
    print("RESULT: " + ("PASS" if not all_findings else f"FAIL ({len(all_findings)} findings)"))
    return 0 if not all_findings else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
