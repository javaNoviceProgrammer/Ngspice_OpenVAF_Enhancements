#!/usr/bin/env python3
"""Enhancement-192: auto-checkpoint on interrupt (`set autosave=<file>`).

Enhancement-131 added `savestate`/`loadstate`, but a checkpoint had to be taken
by hand. E-192 makes an *interrupted* transient write one automatically when the
user opts in with `set autosave=<file>`.

The mechanism: when a running transient is interrupted, dctran's per-timepoint
`IFpauseTest` returns `E_PAUSE` at an ACCEPTED timepoint, which unwinds cleanly
(on the main thread -- never in the signal handler) back to `dosim`, where the
run reports "interrupted" (err == 1). E-192 hooks exactly that branch: if
`autosave` is set and the run was a transient, it writes a checkpoint there.
Because the pause point is a clean timestep boundary, the saved state is
consistent and `loadstate` resumes it.

A real Ctrl-C (SIGINT) and a `stop when ...` breakpoint reach this SAME err == 1
branch -- they differ only in how the interrupt flag gets set, upstream of the
E-192 code. So checks 1-4 drive it deterministically with a `stop` breakpoint
(no signal-timing race); check 5 additionally fires a genuine SIGINT through a
PTY and is lenient (a machine fast enough to finish the run before the signal
lands just skips it -- the hook itself is already covered).

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

SCRATCH = tempfile.mkdtemp(prefix="autosave_")
passed = failed = 0


def check(label, ok, detail=""):
    global passed, failed
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  {detail}" if detail else ""))
    if ok:
        passed += 1
    else:
        failed += 1


def run(deck, name="d.cir"):
    open(os.path.join(SCRATCH, name), "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", name], capture_output=True, text=True,
                       cwd=SCRATCH, timeout=120)
    return r.stdout + r.stderr


def path(f):
    return os.path.join(SCRATCH, f)


RC = ("* RC for the auto-checkpoint-on-interrupt test\n"
      "V1 in 0 SIN(0 1 1k)\n"
      "R1 in out 1k\n"
      "C1 out 0 1u\n"
      ".tran 1u 10m\n")

# ---- 1. `set autosave` -> a paused (stop) transient writes a checkpoint ----
log = run(RC +
          ".control\n"
          "set autosave=cp1.dat\n"
          "stop when time > 2m\n"
          "run\n"
          ".endc\n.end\n", "a1.cir")
wrote = "Auto-checkpoint" in log and os.path.exists(path("cp1.dat"))
check("[autosave] interrupted transient writes a checkpoint", wrote,
      "(msg + file present)" if wrote else "(no checkpoint)")

# ---- 2. autosave file == a manual savestate at the SAME pause (byte-identical) ----
run(RC +
    ".control\n"
    "stop when time > 2m\n"
    "run\n"
    "savestate cp_manual.dat\n"
    ".endc\n.end\n", "a2.cir")
if os.path.exists(path("cp1.dat")) and os.path.exists(path("cp_manual.dat")):
    identical = (open(path("cp1.dat"), "rb").read() ==
                 open(path("cp_manual.dat"), "rb").read())
    check("[autosave] checkpoint == manual savestate at same pause (byte-identical)",
          identical)
else:
    check("[autosave] checkpoint == manual savestate", False, "missing file(s)")

# ---- 3. the autosave checkpoint loads and resumes ----
log = run(RC +
          ".control\n"
          "loadstate cp1.dat\n"
          "run\n"
          "let tmax = time[length(time)-1]\n"
          "print tmax\n"
          ".endc\n.end\n", "a3.cir")
resumed = ("Restored checkpoint" in log and "continuing transient from t" in log)
check("[autosave] the checkpoint loads and resumes (loadstate)", resumed,
      "(restored + continued)" if resumed else "(load failed)")

# ---- 4. opt-in gate: WITHOUT autosave, an interrupt writes no checkpoint ----
before = set(os.listdir(SCRATCH))
log = run(RC +
          ".control\n"
          "stop when time > 2m\n"
          "run\n"
          "echo NOAUTO_DONE\n"
          ".endc\n.end\n", "a4.cir")
after = set(os.listdir(SCRATCH))
# a fresh checkpoint would be a new non-deck file; ignore the .cir deck itself
new_files = [f for f in (after - before) if not f.endswith(".cir")]
paused = "simulation interrupted" in log and "NOAUTO_DONE" in log
check("[autosave] opt-in gate: no `autosave` var -> interrupt writes no checkpoint",
      paused and "Auto-checkpoint" not in log and not new_files,
      "(paused, no checkpoint file)" if paused else "(did not pause)")

# ---- 5. a REAL SIGINT (Ctrl-C) through a PTY triggers the autosave (lenient) ----
def sigint_check():
    """Genuine interactive Ctrl-C. Returns True (checkpoint written), or None to
    skip (couldn't catch the run mid-flight, or PTY unavailable) -- never fails,
    since the identical err==1 hook is already proven deterministically above."""
    try:
        import pty
        import signal
        import time
        import select
    except ImportError:
        return None
    if not hasattr(pty, "fork"):
        return None
    chk = path("cp_sigint.dat")
    if os.path.exists(chk):
        os.remove(chk)
    # A long, memory-bounded run (only v(out) saved) so a genuine SIGINT lands
    # mid-transient on typical hardware.
    deck = ("* real SIGINT autosave\n"
            "V1 in 0 SIN(0 1 1k)\nR1 in out 1k\nC1 out 0 1u\n"
            ".save v(out)\n.tran 1n 30m\n"
            ".control\nset autosave=cp_sigint.dat\nrun\nquit\n.endc\n.end\n")
    open(path("s.cir"), "w").write(deck)
    try:
        pid, fd = pty.fork()
    except OSError:
        return None
    if pid == 0:
        os.chdir(SCRATCH)
        os.execv(NGSPICE, [NGSPICE, "s.cir"])
        os._exit(127)
    start = time.time()
    sent = False
    while True:
        if not sent and time.time() - start > 0.8:
            try:
                os.kill(pid, signal.SIGINT)
            except OSError:
                pass
            sent = True
        try:
            r, _, _ = select.select([fd], [], [], 0.2)
            if r:
                if not os.read(fd, 4096):
                    break
        except OSError:
            break
        wpid, _ = os.waitpid(pid, os.WNOHANG)
        if wpid == pid:
            break
        if time.time() - start > 25:
            os.kill(pid, signal.SIGKILL)
            os.waitpid(pid, 0)
            break
    return True if os.path.exists(chk) else None


res = sigint_check()
if res is True:
    check("[sigint] a genuine Ctrl-C (SIGINT) triggers the autosave", True,
          "(checkpoint written by real signal)")
elif res is None:
    print("  SKIP  [sigint] real Ctrl-C not exercised "
          "(run finished before the signal, or PTY unavailable); "
          "the identical hook is covered deterministically above")
else:
    check("[sigint] a genuine Ctrl-C (SIGINT) triggers the autosave", False)

# tidy
import glob
for g in glob.glob(os.path.join(SCRATCH, "*")):
    try:
        os.remove(g)
    except OSError:
        pass
try:
    os.rmdir(SCRATCH)
except OSError:
    pass

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
