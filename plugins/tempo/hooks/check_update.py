#!/usr/bin/env python3
"""TEMPO SessionStart hook: says when a newer TEMPO is published than the one installed.

Reads the installed version from this plugin's plugin.json and the published one from
the same file on GitHub main. When the published one is newer it prints a systemMessage
with the update commands. Offline, slow or any error: prints nothing, the session starts.
"""
import json
import os
import re
import sys
import urllib.request

URL = "https://raw.githubusercontent.com/jorgelrj/claude-skills/main/plugins/tempo/.claude-plugin/plugin.json"
MANIFEST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".claude-plugin", "plugin.json")


def parse(v):
    return tuple(int(n) for n in re.findall(r"\d+", v)[:3])


def main():
    with open(MANIFEST, encoding="utf-8") as f:
        installed = json.load(f)["version"]
    # shortcut: one fetch per session start, 2 s cap; add a daily cache if it ever slows startup
    with urllib.request.urlopen(URL, timeout=2) as r:
        latest = json.loads(r.read().decode("utf-8"))["version"]
    if parse(latest) > parse(installed):
        print(json.dumps({"systemMessage": (
            f"TEMPO {latest} is out (installed: {installed}). Update with: "
            "claude plugin marketplace update jorgelrj-skills && claude plugin update tempo@jorgelrj-skills, "
            "then restart Claude Code.")}))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
