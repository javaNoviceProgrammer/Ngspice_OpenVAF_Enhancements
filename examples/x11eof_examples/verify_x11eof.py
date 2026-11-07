#!/usr/bin/env python3
"""
verify_x11eof.py -- Enhancement-919: the prompt ends at the end of its input with
an X display open.

With a display, readline waits through an event hook. That wait asks FIONREAD and
calls the hook again; it never reaches readline's read(), the one place the end of
the input is seen. At that end the hook's select returns at once and FIONREAD says
0, so `ngspice -i` with piped input spun at the prompt for good. sourcenest [7] to
[9] hung on any machine with a live X display, and passed on CI, which has none.

Every case runs without a display. The same cases run again when an X server
answers on $DISPLAY, and only there do they reach the hook:

  [1] a pipe closed with nothing written: the prompt ends, exit 0
  [2] a pipe closed after two commands: each runs once, exit 0
  [3] a last line with no newline, from a pipe: it still runs
  [4] a file as the input, its last line with no newline: every line runs
  [5] a pipe left open and silent, then written to: not taken for its end
  [6] a signal while waiting on an open pipe: not taken for its end
  [7] a terminal: silent and signalled, then a command, then Ctrl-D ends it, exit 0

On E-918, with a display, [1] to [6] hang; [5] and [6] get through their waits and
hang at the end. [7] holds there, and is what guards the fix against going too far:
a fix that took X11_Input's return for the end of the input ends the session when a
terminal is resized. [6] did not catch that on macOS: a signal on a pipe did not
bring X11_Input back.
"""
import os
import pty
import re
import select
import shutil
import signal
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

NO_GRAPHICS = "no graphics interface"
LIMIT_S = 30    # a hang costs this, once per case; a pass takes under a second
checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def finish(p):
    """Wait for ngspice with its stdin already closed: (rc, output); rc None on a hang."""
    try:
        out, err = p.communicate(timeout=LIMIT_S)
        return p.returncode, out + err
    except subprocess.TimeoutExpired:
        p.kill()
        out, err = p.communicate()
        return None, out + err


def start(d, env, stdin=subprocess.PIPE):
    return subprocess.Popen([NGSPICE, "-i", "t.cir"], cwd=d, env=env, stdin=stdin,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, errors="replace")


def ran(out, word):
    """How many times `echo word` printed. Readline echoes a line it reads from a pipe
    (`ngspice 2 -> echo word`, then `word`), so count the printed line alone."""
    return len(re.findall(rf"(?:^|-> ){word}$", out, re.M))


def piped(d, env, text):
    p = start(d, env)
    p.stdin.write(text)
    p.stdin.close()
    return finish(p)


def send(p, text):
    p.stdin.write(text)
    p.stdin.flush()


def on_terminal(d, env):
    """A session on a pty, as a person has it: (rc, output); rc None on a hang."""
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(d)
        os.execve(NGSPICE, [NGSPICE, "-i", "t.cir"], env)
    output = b""

    def read_for(seconds):
        nonlocal output
        end = time.time() + seconds
        while time.time() < end:
            if select.select([fd], [], [], 0.05)[0]:
                try:
                    data = os.read(fd, 4096)
                except OSError:     # the far end of the pty has gone
                    return
                if not data:
                    return
                output += data

    read_for(1)
    os.kill(pid, signal.SIGWINCH)
    read_for(0.5)
    try:
        os.write(fd, b"echo TYPED\r")
        read_for(0.5)
        os.write(fd, b"\x04")
    except OSError:
        pass
    end = time.time() + LIMIT_S
    rc = None
    while time.time() < end:
        read_for(0.1)
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            rc = os.waitstatus_to_exitcode(status)
            break
    if rc is None:
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
    os.close(fd)
    return rc, output.decode(errors="replace").replace("\r", "")


def cases(tag, d, env):
    rc, out = piped(d, env, "")
    check(f"{tag} [1] a pipe closed with nothing written: exit 0", rc == 0, f"rc={rc}")

    rc, out = piped(d, env, "echo ONE\necho TWO\n")
    check(f"{tag} [2] a pipe closed after two commands: each runs once, exit 0",
          rc == 0 and ran(out, "ONE") == 1 and ran(out, "TWO") == 1, f"rc={rc}")

    rc, out = piped(d, env, "echo LAST")
    check(f"{tag} [3] a last line with no newline, from a pipe: it still runs",
          rc == 0 and ran(out, "LAST") == 1, f"rc={rc}")

    path = os.path.join(d, "input.txt")
    with open(path, "w") as f:
        f.write("echo FIRST\necho FINAL")
    with open(path) as f:
        p = start(d, env, stdin=f)
        rc, out = finish(p)
    check(f"{tag} [4] a file as the input, its last line with no newline: every line runs",
          rc == 0 and ran(out, "FIRST") == 1 and ran(out, "FINAL") == 1, f"rc={rc}")

    # Each of the next two writes a command to prove the prompt outlived the wait;
    # a prompt that took the wait for the end has exited, and the write has no reader.
    p = start(d, env)
    time.sleep(1)
    alive = p.poll() is None
    if alive:
        send(p, "echo LATER\n")
        time.sleep(0.5)
        send(p, "echo LATEST\n")
        p.stdin.close()
    rc, out = finish(p)
    check(f"{tag} [5] a pipe left open and silent, then written to: not taken for its end",
          alive and rc == 0 and ran(out, "LATER") == 1 and ran(out, "LATEST") == 1,
          f"alive={alive} rc={rc}")

    p = start(d, env)
    time.sleep(1)
    for _ in range(3):
        if p.poll() is None:
            p.send_signal(signal.SIGWINCH)
        time.sleep(0.2)
    alive = p.poll() is None
    if alive:
        send(p, "echo STILL\n")
        p.stdin.close()
    rc, out = finish(p)
    check(f"{tag} [6] a signal while waiting on an open pipe: not taken for its end",
          alive and rc == 0 and ran(out, "STILL") == 1, f"alive={alive} rc={rc}")

    rc, out = on_terminal(d, env)
    check(f"{tag} [7] a terminal: silent and signalled, then a command, then Ctrl-D ends it, exit 0",
          rc == 0 and ran(out, "TYPED") == 1, f"rc={rc}")


if os.name != "posix":
    print("  SKIP  a piped session's input and SIGWINCH: POSIX only")
    sys.exit(0)

WORK = tempfile.mkdtemp(prefix="x11eof_")
with open(os.path.join(WORK, "t.cir"), "w") as f:
    f.write("* t\nr1 1 0 1k\nv1 1 0 1\n.end\n")

no_display = {k: v for k, v in os.environ.items() if k != "DISPLAY"}
cases("no display:", WORK, no_display)

# "quit" ends the run with or without the fix, so this asks only about the display
if os.environ.get("DISPLAY"):
    rc, out = piped(WORK, os.environ, "quit\n")
    has_x = rc is not None and NO_GRAPHICS not in out
else:
    has_x = False
if has_x:
    cases("X display:", WORK, os.environ)
else:
    print("  SKIP  the same cases with the X event hook: no X server answers on $DISPLAY")

shutil.rmtree(WORK, ignore_errors=True)
print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
