---
description: Start the local, read-only TEMPO dashboard and give its URL. It shows every running or recent task with its stage, agents, runs, processes and documents. Also stops it or says whether it runs.
argument-hint: [stop | status] [folder] [host]
---

TEMPO dashboard: $ARGUMENTS

1. Load the TEMPO `orchestrator` skill (listed as `tempo:orchestrator` when installed as a plugin) for its paths (section 0). `<dash>` is `python3 <orch>/scripts/tempo_dash.py` (0.15).
2. IF the words above include `stop`, THEN run `<dash> stop`, tell me in one line what it printed, and stop here.
3. IF the words above include `status`, THEN run `<dash> status`, tell me in one line what it printed, and stop here.
4. Run `<dash> start`. IF the words above name a folder, THEN pass it as an absolute path: `<dash> start --root <folder>`. The folder is a checkout, or a folder of checkouts, whose `.tempo/` tasks should be listed next to the registered ones.
5. IF it prints `DASH: <url>`, THEN tell me the URL in one line. A server that already runs prints the same line, and nothing new starts. To change its folders, run `/tempo:dash stop` first.
5a. IF the words above name a host (for example a `*.ts.net` name for `tailscale serve`), THEN add `--allow-host <name>` to the start command. A server already running without it must be stopped first (`<dash> stop`).
6. IF it exits 1, THEN show me its message. The port is taken by something else, or the server did not start. Do not pick another port or stop another process without asking.

Note: the server is read-only and local-only. It listens on `127.0.0.1`, reads each task's `state.json`, `events.jsonl` and documents, and changes nothing. It outlives this session and runs until `/tempo:dash stop`.
