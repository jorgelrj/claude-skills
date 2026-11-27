"""Tests for check_doc.py's QA Report rules: METHOD (result and Method on each criterion line),
EVIDENCE (a PASS cites its own qa/ file that exists next to the report), MISSING and RESULT.

Run: python3 -m unittest discover -s <plugin>/tests -v
"""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills" / "document-standard" / "scripts"))
import check_doc  # noqa: E402

QA = """\
# QA Report: T-1 / R1
Inputs: spec.md, integration.md · Issued by: qa

## 1 Scope
- Branch: tempo/T-1 at abc123
- Criteria source: spec.md §3

## 2 Environment
- Stack started: api `npm run dev` ready "listening"
- Devices and browsers: NIL
- Data: seed `npm run seed`
- Design reference: NIL

## 3 Criteria results
{line}

## 4 Regression check
- Integrate at abc123, bars FULL: PASS. NIL

## 5 Failures returned to build
- NIL

## 6 Result
{result}
"""


class QaRules(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        (self.dir / "qa").mkdir()
        self.templates = check_doc.load_templates()

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, line, result="PASS"):
        p = self.dir / "qa-r1.md"
        p.write_text(QA.format(line=line, result=result), encoding="utf-8")
        findings, _ = check_doc.check_file(str(p), self.templates)
        return findings

    def test_old_method_fails(self):
        f = self.check("- AC-1: PASS. Method: COMMAND. Evidence: npm test exit 0. Supporting: NIL")
        self.assertTrue(any("METHOD" in x for x in f), f)

    def test_ci_result_fails(self):
        f = self.check("- AC-1: CI. Method: TEST. Evidence: widget_test. Supporting: NIL")
        self.assertTrue(any("METHOD" in x for x in f), f)

    def test_missing_evidence_fails(self):
        f = self.check("- AC-1: PASS. Method: LIVE-API. Steps: curl. Observed: 200. "
                       "Evidence: qa/AC-1.http.txt. Supporting: NIL")
        self.assertTrue(any("EVIDENCE" in x for x in f), f)

    def test_test_criterion_may_cite_a_clean_run(self):
        f = self.check("- AC-1: PASS. Method: TEST (additive). Steps: NIL. Observed: field asserted. "
                       "Evidence: run tempo-run-ab12 TREE e44ad6b5 clean. Supporting: NIL")
        self.assertEqual([x for x in f if "EVIDENCE" in x], [], f)

    def test_live_criterion_cannot_cite_a_run(self):
        f = self.check("- AC-1: PASS. Method: LIVE-API. Steps: curl. Observed: 200. "
                       "Evidence: run tempo-run-ab12 TREE e44ad6b5 clean. Supporting: NIL")
        self.assertTrue(any("EVIDENCE" in x for x in f), f)

    def test_test_needs_its_class(self):
        f = self.check("- AC-1: PASS. Method: TEST. Steps: NIL. Observed: asserted. "
                       "Evidence: run tempo-run-ab12 TREE e44ad6b5 clean. Supporting: NIL")
        self.assertTrue(any("METHOD" in x for x in f), f)

    def test_live_api_with_file_passes(self):
        (self.dir / "qa" / "AC-1.http.txt").write_text("HTTP/1.1 200 OK\n")
        f = self.check("- AC-1: PASS. Method: LIVE-API. Steps: `curl -sS -i localhost:3000/x`. Observed: 200. "
                       "Evidence: qa/AC-1.http.txt. Supporting: api.test.ts")
        self.assertEqual(f, [])

    def test_design_line_passes(self):
        (self.dir / "qa" / "design").mkdir()
        for n in ("design", "app", "side"):
            (self.dir / "qa" / "design" / f"AC-2-F-1-{n}.png").write_bytes(b"png")
        f = self.check("- AC-2: PASS. Method: LIVE-WEB + DESIGN. Steps: open /home. Observed: list shown. "
                       "Evidence: qa/design/AC-2-F-1-design.png, qa/design/AC-2-F-1-app.png, "
                       "qa/design/AC-2-F-1-side.png. Supporting: NIL")
        self.assertEqual(f, [])

    def test_blocked_needs_no_file(self):
        f = self.check("- AC-3: BLOCKED. Method: LIVE-MOBILE. Steps: NIL. Observed: no simulator. "
                       "Evidence: MISSING-SOURCE F-2 | prototype at another commit. Supporting: NIL", result="FAIL")
        self.assertEqual(f, [])

    def test_blocked_under_pass_result_fails(self):
        f = self.check("- AC-3: BLOCKED. Method: LIVE-MOBILE. Steps: NIL. Observed: no simulator. "
                       "Evidence: NIL. Supporting: NIL")
        self.assertTrue(any("RESULT" in x for x in f), f)

    def test_star_bullet_is_checked(self):
        (self.dir / "qa" / "x.txt").write_text("x")
        f = self.check("* AC-1: PASS. Method: LIVE-API. Evidence: qa/x.txt")
        self.assertTrue(any("METHOD" in x for x in f), f)

    def test_other_files_are_not_evidence(self):
        for n in ("build-AC-1.http.txt", "progress.md", "AC-2.png"):
            (self.dir / "qa" / n).write_text("x")
        f = self.check("- AC-1: PASS. Method: LIVE-API. Steps: curl. Observed: 200. "
                       "Evidence: qa/build-AC-1.http.txt, qa/progress.md, qa/AC-2.png. Supporting: NIL")
        self.assertTrue(any("EVIDENCE" in x for x in f), f)

    def test_older_round_is_not_evidence(self):
        (self.dir / "qa" / "r1").mkdir()
        (self.dir / "qa" / "r1" / "AC-1.png").write_bytes(b"png")
        f = self.check("- AC-1: PASS. Method: LIVE-WEB. Steps: open /. Observed: ok. "
                       "Evidence: qa/r1/AC-1.png. Supporting: NIL")
        self.assertTrue(any("EVIDENCE" in x for x in f), f)

    def test_design_needs_design_file(self):
        (self.dir / "qa" / "AC-2.png").write_bytes(b"png")
        f = self.check("- AC-2: PASS. Method: LIVE-WEB + DESIGN. Steps: open /home. Observed: list shown. "
                       "Evidence: qa/AC-2.png. Supporting: NIL")
        self.assertTrue(any("DESIGN" in x and "EVIDENCE" in x for x in f), f)

    def test_no_criterion_line_fails(self):
        f = self.check("NIL")
        self.assertTrue(any("MISSING" in x for x in f), f)



FINDINGS = """\
# Findings: T-1 / R1
Inputs: review/raw-correctness-r1.md · Issued by: verifier
Severity: as in the Raw Findings template.

## 1 Scope
- Round: 1 of 3. Kind: FULL
- Lenses: CORRECTNESS
- Diff: abc123..def456
- Fix diff: NIL

## 2 Confirmed findings
### F-1: {severity} · `tests/cli.test.ts:9` · Lens: SPEC · Owner: WO-01
- Problem: the CLI tests read .wclite.json from the real working directory. NIL
- Area: tests/cli.test.ts
- Fix kind: LOCAL
{extra}
- Evidence: `readFileSync('.wclite.json')` at tests/cli.test.ts:9
- Fix direction: run each test in a temp directory

## 3 Dropped findings
- NIL

## 4 Sibling sweep
- NIL

## 5 Left open
- NIL

## 6 Result
- FAIL. PASS means no confirmed HIGH or MEDIUM finding remains.
- Introduced findings: 0. Areas: NIL
"""

SCENARIO = "- Failure scenario: a developer with a .wclite.json in the repo root runs the tests; they read and overwrite it."
YES = "- Blocking: yes. Breaks: AC-3 (no test touches the real working directory). Can't wait: the PR ships the exact gap AC-3 forbids."
NO = "- Blocking: no. Breaks: NIL. Can't wait: NIL"


class FindingsRules(unittest.TestCase):
    """Rule BLOCKING: a confirmed MEDIUM says whether it blocks the board's default bar, and how it fails."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.templates = check_doc.load_templates()

    def tearDown(self):
        self.tmp.cleanup()

    def check(self, extra, severity="MEDIUM"):
        p = Path(self.tmp.name) / "findings-r1.md"
        p.write_text(FINDINGS.format(severity=severity, extra=extra), encoding="utf-8")
        findings, _ = check_doc.check_file(str(p), self.templates)
        return findings

    def test_blocking_medium_that_breaks_a_criterion_passes(self):
        self.assertEqual(self.check(f"{SCENARIO}\n{YES}"), [])

    def test_non_blocking_medium_passes(self):
        self.assertEqual(self.check(f"{SCENARIO}\n{NO}"), [])

    def test_medium_without_either_field_fails(self):
        f = self.check("- Note: NIL")
        self.assertEqual(sum("BLOCKING" in x for x in f), 2, f)

    def test_medium_without_blocking_fails(self):
        f = self.check(SCENARIO)
        self.assertTrue(any("Blocking: yes|no" in x for x in f), f)

    def test_medium_with_nil_scenario_fails(self):
        f = self.check(f"- Failure scenario: NIL\n{NO}")
        self.assertTrue(any("Failure scenario" in x for x in f), f)

    def test_blocking_yes_needs_a_criterion_and_a_reason(self):
        f = self.check(f"{SCENARIO}\n- Blocking: yes. Breaks: NIL. Can't wait: NIL")
        self.assertTrue(any("'Breaks:'" in x for x in f), f)
        self.assertTrue(any("'Can't wait:'" in x for x in f), f)

    def test_code_defect_may_block(self):
        self.assertEqual(self.check(f"{SCENARIO}\n- Blocking: yes. Breaks: CODE. Can't wait: it loses the user's config."), [])

    def test_high_and_low_need_no_blocking_line(self):
        self.assertEqual(self.check("- Note: NIL", severity="HIGH"), [])
        self.assertEqual(self.check("- Note: NIL", severity="LOW"), [])


if __name__ == "__main__":
    unittest.main()
