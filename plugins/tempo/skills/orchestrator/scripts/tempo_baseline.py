#!/usr/bin/env python3
"""TEMPO baseline: which platform-target tests already fail on the base commit.

A target that is red on the base branch (config `advisory: true`) only blocks on
failures the base does not have. The integrator runs the target's scoped tests on
the base commit once, records the failures here, and every later task on the same
base commit reuses them. Comparison is by name, done by this script, not by hand.

Cache: <repo>/.tempo/baselines/<base commit, 12 chars>/<target>.tsv
  ran<TAB><test file>                 a test file run on the base
  fail<TAB><test file><TAB><test name>  a failure on the base ("*" as the name: the file failed to load)

Failure lists (--failures, --head) are text files with one failure per line:
  <test file><TAB><test name>       (or just <test file> when the whole file failed or did not load)

Usage: tempo_baseline.py <command> [args]
  path     --repo R --base SHA --target NAME        print the cache path (creates its folder)
  missing  CACHE --tests T [T ...]                  print the test files not yet run on the base
  record   CACHE --tests T [T ...] --failures FILE  add a base run of those files and its failures
  compare  CACHE --head FILE [--tests T ...]        NEW / FIXED / STILL against the base; exit 1 if NEW
Exit 0 ok, 1 new failures (compare) or error.
"""
import argparse
import sys
from pathlib import Path

if sys.platform == "win32":  # the console code page cannot carry every character a task or a hook holds
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")


def read_cache(path):
    ran, fails = set(), set()
    p = Path(path)
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            parts = line.split("\t")
            if parts[0] == "ran" and len(parts) >= 2:
                ran.add(parts[1].strip())
            elif parts[0] == "fail" and len(parts) >= 3:
                fails.add((parts[1].strip(), parts[2].strip()))
    return ran, fails


def read_failures(path):
    out = set()
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        f, _, name = line.partition("\t")
        out.add((f.strip(), name.strip() or "*"))
    return out


def main(argv=None):
    p = argparse.ArgumentParser(prog="tempo_baseline.py", description="TEMPO platform-target baselines")
    sp = p.add_subparsers(dest="cmd", required=True)
    pa = sp.add_parser("path"); pa.add_argument("--repo", default="."); pa.add_argument("--base", required=True); pa.add_argument("--target", required=True)
    mi = sp.add_parser("missing"); mi.add_argument("cache"); mi.add_argument("--tests", nargs="+", required=True)
    rc = sp.add_parser("record"); rc.add_argument("cache"); rc.add_argument("--tests", nargs="+", required=True); rc.add_argument("--failures", required=True)
    co = sp.add_parser("compare"); co.add_argument("cache"); co.add_argument("--head", required=True); co.add_argument("--tests", nargs="*")
    a = p.parse_args(argv)

    if a.cmd == "path":
        d = Path(a.repo).resolve() / ".tempo" / "baselines" / a.base[:12]
        d.mkdir(parents=True, exist_ok=True)
        print(d / f"{a.target}.tsv"); return 0

    ran, fails = read_cache(a.cache)
    if a.cmd == "missing":
        for t in a.tests:
            if t not in ran:
                print(t)
        return 0

    if a.cmd == "record":
        new = read_failures(a.failures)
        lines = [f"ran\t{t}" for t in a.tests if t not in ran]
        lines += [f"fail\t{f}\t{n}" for f, n in sorted(new) if (f, n) not in fails]
        if lines:
            with open(a.cache, "a", encoding="utf-8") as fh:
                fh.write("\n".join(lines) + "\n")
        print(f"BASELINE: {a.cache}  RAN: +{len([x for x in a.tests if x not in ran])}  FAILURES: +{len(lines) - len([x for x in a.tests if x not in ran])}")
        return 0

    if a.cmd == "compare":
        head = read_failures(a.head)
        scope = set(a.tests) if a.tests else None
        unrun = sorted({f for f, _ in head if f not in ran} | ({t for t in scope if t not in ran} if scope else set()))
        if unrun:
            print("NOT IN BASELINE: " + " ".join(unrun) + "  (run them on the base and `record` first)")
            return 1
        base = {x for x in fails if scope is None or x[0] in scope}
        broken = {f for f, n in base if n == "*"}  # a file that did not load on the base hides its tests' names
        new = sorted(x for x in head if x not in base and x[0] not in broken)
        fixed = sorted(x for x in base if x not in head and x[1] != "*")
        still = sorted(x for x in head if x in base or x[0] in broken)
        print(f"NEW: {len(new)}  FIXED: {len(fixed)}  STILL: {len(still)}")
        for tag, items in (("NEW", new), ("FIXED", fixed)):
            for f, n in items:
                print(f"{tag}\t{f}\t{n}")
        return 1 if new else 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
