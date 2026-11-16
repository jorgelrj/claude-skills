"""The few calls that differ between POSIX (macOS, Linux) and native Windows. Standard library only.

POSIX keeps the calls the scripts always used. Windows has no fcntl, killpg, process groups, /proc or ps,
and os.kill(pid, 0) there terminates the process instead of probing it, so nothing outside this module
calls os.kill, os.killpg or fcntl.
"""
import os
import shutil
import signal
import subprocess
import sys
import time

WINDOWS = os.name == "nt"

if WINDOWS:
    import ctypes
    import msvcrt
    for _s in (sys.stdin, sys.stdout, sys.stderr):  # the console code page cannot carry every character a task holds
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
else:
    import fcntl

# Windows locks are mandatory byte ranges: lock one byte far past the text a slot file holds, so other
# processes can still read who holds it.
_LOCK_AT = 1 << 30


def lock(f, block=True):
    """Exclusive lock on open file `f`, released when it closes. Raises OSError when `block` is False and it is held."""
    if not WINDOWS:
        fcntl.flock(f, fcntl.LOCK_EX | (0 if block else fcntl.LOCK_NB))
        return
    f.flush()
    while True:
        os.lseek(f.fileno(), _LOCK_AT, os.SEEK_SET)
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            if not block:
                raise
            time.sleep(0.05)  # LK_LOCK gives up after 10 s; the state lock must wait as long as it takes


def alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if not WINDOWS:
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.OpenProcess.restype = ctypes.c_void_p
    h = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ctypes.get_last_error() == 5  # access denied: it exists, it is another user's
    code = ctypes.c_ulong()
    ok = k32.GetExitCodeProcess(ctypes.c_void_p(h), ctypes.byref(code))
    k32.CloseHandle(ctypes.c_void_p(h))
    return bool(ok) and code.value == 259  # STILL_ACTIVE


def kill(pid, force=False, group=False):
    """SIGTERM (or SIGKILL with `force`) to `pid`, or to its process group with `group`. Never raises.
    Windows: taskkill /T /F, always the whole tree. It has no process groups, and a console program ignores
    the polite taskkill, so the grace period would only be lost time. A process `spawn` started also has its job
    killed: Git Bash's fork and exec leave children whose parent PID is gone, which taskkill /T misses."""
    try:
        if WINDOWS:
            # Open the job first: its name dies with the process that holds it. Kill the tree before the job, while
            # its parent links hold: an app-execution-alias program (a Store or install-manager python.exe) starts
            # outside the job.
            job = _job(int(pid))
            subprocess.run(["taskkill", "/PID", str(int(pid)), "/T", "/F"], capture_output=True, timeout=30)
            if job:
                _k32().TerminateJobObject(job, 1)
                _k32().CloseHandle(job)
        else:
            (os.killpg if group else os.kill)(int(pid), signal.SIGKILL if force else signal.SIGTERM)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass


def spawn(args, **kw):
    """Popen in its own session (POSIX) or process group, without a console (Windows), so it outlives the caller."""
    if not WINDOWS:
        return subprocess.Popen(args, start_new_session=True, **kw)
    flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW | 0x4  # CREATE_SUSPENDED
    try:  # out of the caller's job object, which may kill everything in it when the Bash tool call ends
        proc = subprocess.Popen(args, creationflags=flags | 0x01000000, **kw)  # CREATE_BREAKAWAY_FROM_JOB
    except OSError:  # the job forbids breakaway
        proc = subprocess.Popen(args, creationflags=flags, **kw)
    # Its own named job, joined before it runs: every descendant inherits it, so kill() finds them all.
    # A job's name lives only while a handle to it is open, so the process holds a copy of the handle.
    k32, child = _k32(), ctypes.c_void_p(int(proc._handle))
    job = ctypes.c_void_p(k32.CreateJobObjectW(None, _job_name(proc.pid)))
    if job.value:
        k32.AssignProcessToJobObject(job, child)
        k32.DuplicateHandle(ctypes.c_void_p(k32.GetCurrentProcess()), job, child,
                            ctypes.byref(ctypes.c_void_p()), 0, False, 0x2)  # DUPLICATE_SAME_ACCESS
        k32.CloseHandle(job)
    ctypes.WinDLL("ntdll").NtResumeProcess(child)
    return proc


def _k32():
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = k32.OpenJobObjectW.restype = k32.GetCurrentProcess.restype = ctypes.c_void_p
    return k32


def _job_name(pid):
    # shortcut: named by PID, so a reused PID reaches leftovers of the old job; key by start time if that bites
    return f"Local\\tempo-{pid}"


def _job(pid):
    h = _k32().OpenJobObjectW(0x0008, False, _job_name(pid))  # JOB_OBJECT_TERMINATE
    return ctypes.c_void_p(h) if h else None


def shell(cmd):
    """argv that runs a command line through bash. On Windows that is Git Bash: a bare `bash` there can be the
    WSL launcher in System32, which runs the command in Linux, not in this checkout."""
    return [git_bash() or "bash", "-c", cmd]


def git_bash():
    """Git Bash's bash.exe on Windows, else None. git.exe sits in Git\\cmd, Git\\bin or Git\\mingw64\\bin."""
    if not WINDOWS:
        return None
    env = os.environ.get("CLAUDE_CODE_GIT_BASH_PATH")
    if env and os.path.isfile(env):
        return env
    git = shutil.which("git")
    d = os.path.dirname(git) if git else None
    for _ in range(3):
        if not d:
            break
        for rel in (("bin", "bash.exe"), ("usr", "bin", "bash.exe")):
            if os.path.isfile(os.path.join(d, *rel)):
                return os.path.join(d, *rel)
        d = os.path.dirname(d)
    bash = shutil.which("bash")  # skip System32\bash.exe, the WSL launcher
    return bash if bash and "system32" not in bash.lower() else None


def replace(src, dst):
    """os.replace. Windows refuses it while another process (the dashboard) has `dst` open: retry briefly."""
    for i in range(40):
        try:
            return os.replace(src, dst)
        except PermissionError:
            if not WINDOWS or i == 39:
                raise
            time.sleep(0.05)


def uid():
    return os.getuid() if hasattr(os, "getuid") else -1
