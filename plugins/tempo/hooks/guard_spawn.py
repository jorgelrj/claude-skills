#!/usr/bin/env python3
"""TEMPO guard: in a session running a TEMPO task, long-lived processes go through tempo_procs.py.

PreToolUse hook for Bash. On 2026-10-30 a QA agent's `nohup emulator ...` (8.3 GB),
helper-launched Java services and `nest --watch` watchers outlived their sessions by
up to 42 hours and pushed the Mac into 11 GB of swap. A process started with nohup,
setsid, disown, a trailing `&`, or the Bash tool's run_in_background escapes every
teardown. In a TEMPO session (the session's Claude Code process has registered a task
that is still open, see tempo_procs.py) this hook denies such a command with a reason
that gives the exact `tempo_procs.py start` line instead. Commands through
tempo_procs.py or tempo_run.py pass, and so does a command with TEMPO_ALLOW_DETACH=1
in it (something Jorge asked for outside the task).

It also denies pkill, killall and a kill fed by pgrep. They stop processes by name anywhere on the machine,
and several TEMPO tasks share it: on 2026-11-11 a builder ran `pkill -f flutter_tester`
to cancel its own test run, and two seconds later the commands of three other tasks'
agents died. A run is cancelled with `tempo_run.py stop <ID>`, a service with
`tempo_procs.py stop`. TEMPO_ALLOW_KILL=1 in the command lets one through.

Outside TEMPO sessions it does nothing. Any error in the hook lets the command through.
"""
import json
import os
import re
import sys

if sys.platform == "win32":  # the console code page cannot carry every character a task or a hook holds
    for _s in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(HERE), "skills", "orchestrator", "scripts").replace(os.sep, "/")  # pasted into bash
WORDS = re.compile(r"(^|[;&|(\s])(nohup|setsid|disown)(\s|;|$)")
QUOTED = re.compile(r"'[^']*'|\"(?:\\.|[^\"\\])*\"")
AMP = re.compile(r"(?<![&>|<])&(?![&>])")
WATCH = re.compile(r"""[^;&|`$()<>\n]*tempo_state\.py["']?\s+watch\s[^;&|`$()<>\n]*""")
# pkill, killall, and the same thing spelled with pgrep: kill $(pgrep ...), kill `pgrep ...`, pgrep ... | xargs kill
# Only where a command starts (line start, after ; & | ( $( or a backtick, also behind sudo or xargs): a grep for
# the word, a file name or a message that mentions it is not a kill.
KILLS = re.compile(r"(^|[;&|(\n`])\s*(sudo\s+|xargs\s+(-\S+\s+)*)?(pkill|killall)(\s|$)|\bkill\b[^;&|]*(\$\(|`)\s*pgrep\b|\bpgrep\b[^;&]*\|\s*xargs\b[^;&|]*\bkill\b")


def detaches(command):
    if WORDS.search(command):
        return True
    bare = QUOTED.sub("''", command)
    return bool(AMP.search(bare))


def main():
    try:
        data = json.load(sys.stdin)
        ti = data.get("tool_input") or {}
        command = ti.get("command") or ""
        bg = bool(ti.get("run_in_background"))
        kills = bool(KILLS.search(QUOTED.sub("''", command))) and "TEMPO_ALLOW_KILL=1" not in command
        if not kills:
            if not (bg or detaches(command)):
                return 0
            if re.search(r"tempo_procs\.py|tempo_run\.py|TEMPO_ALLOW_DETACH=1", command):
                return 0
            # The stall watcher (orchestrator 2.7.0) runs as a background Bash command; only when it is the whole command.
            if bg and not detaches(command) and WATCH.fullmatch(command.strip()):
                return 0
        sys.path.insert(0, SCRIPTS)
        import tempo_procs
        owner = tempo_procs.find_owner()
        f = tempo_procs.SESSIONS / f"{owner}.json"
        if not owner or not f.exists():
            return 0
        open_tasks = [d for d in json.loads(f.read_text(encoding="utf-8"))
                      if tempo_procs.task_status(d)[0] not in tempo_procs.ENDED | {"GONE", "UNKNOWN"}]
        if not open_tasks:
            return 0
    except Exception:
        return 0
    procs = f"{SCRIPTS}/tempo_procs.py"
    task = open_tasks[-1] if len(open_tasks) == 1 else "<task folder: " + " | ".join(open_tasks) + ">"
    if kills:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                "TEMPO guard: pkill and killall stop processes by name anywhere on this machine, and other TEMPO "
                "tasks share it (a pkill of flutter_tester in one task was followed by three other tasks' commands dying). "
                f"To cancel a test or build run you started: python3 {SCRIPTS}/tempo_run.py stop <ID> "
                "(the ID its RUNNING line printed). To stop a service you started: "
                f"python3 {procs} stop --task {task} --label <short name>. To stop one process you started yourself, "
                "kill its PID. Only if Jorge asked for this kill by name, put TEMPO_ALLOW_KILL=1 in the command. "
                "Do not ask the user."
            ),
        }}))
        return 0
    how = "run_in_background" if bg else "nohup, setsid, disown or a trailing &"
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": (
            f"TEMPO guard: this session runs a TEMPO task, and a process started with {how} outlives "
            "the agent and the session (leftover emulators and servers filled the Mac's memory). "
            "For a server, emulator, simulator, watcher or container that must keep running, start it with: "
            f"python3 {procs} start --task {task} --label <short name> [--ready '<log line regex>'] "
            "[--stop '<command that stops it, e.g. docker compose down>'] -- '<command>'  "
            f"and stop it when done with: python3 {procs} stop --task {task} --label <short name>. "
            "For a test, build or other command that ends, use the run script <run> instead. "
            "Only if Jorge asked for this process outside the task, put TEMPO_ALLOW_DETACH=1 in the command. "
            "Do not ask the user."
        ),
    }}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
