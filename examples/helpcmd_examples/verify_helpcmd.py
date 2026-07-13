#!/usr/bin/env python3
"""Regression guard: the interactive `help` command must not crash.

ngspice prints each command's one-line help by passing the help string itself
as the *format* argument to out_printf/tvprintf:

    out_printf(ccc[i]->co_help, cp_program);   /* com_help.c */

so the help string is a printf format with exactly one available argument
(cp_program, meant for a single %s). A help string that contains any other '%'
(e.g. a literal "95% CI") is an invalid conversion specifier: tvprintf fails and
ngspice calls a fatal exit(-1). `help all` walks every command, so one bad
string takes down the whole command -- and `help <thatcommand>` too.

This actually shipped: the `montecarlo` command's help (Enhancement-151) read
"... a Wilson 95% CI ...", so `help all` and `help montecarlo` crashed with
"Error: tvprintf failed / fatal error in ngspice, exit(-1)". Fixed by escaping
the percent as %%.

Two checks:
  [1..3] RUNTIME -- drive an interactive ngspice on a pty and confirm `help`,
         `help all`, and `help montecarlo` each run to completion (no crash, no
         "tvprintf failed"), and that the montecarlo line renders the literal
         "95% CI".
  [4] STATIC class-guard -- scan commands.c and assert NO command help string
         carries a format hazard (a '%' that is not '%s' or '%%', or more than
         one '%s'), so a future unescaped '%' is caught even if that specific
         command is never exercised at runtime.

Not a circuit simulation, so the dual-solver harness does not apply.
"""
import os
import pty
import re
import select
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE

REPO = os.path.dirname(os.path.dirname(HERE))
COMMANDS_C = os.path.join(REPO, "ngspice-46", "src", "frontend", "commands.c")

passed = failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name} {detail}")
    else:
        failed += 1
        print(f"  FAIL  {name} {detail}")


def run_help(arg):
    """Type `help <arg>` into an interactive ngspice on a pty. Return
    (status, text) where status is 'ok' / 'crash' / 'exit<N>'."""
    pid, fd = pty.fork()
    if pid == 0:
        os.execv(NGSPICE, [NGSPICE])
        os._exit(1)
    time.sleep(0.8)
    os.write(fd, (f"help {arg}\r" if arg else "help\r").encode())
    time.sleep(1.6)
    buf = b""
    try:
        while select.select([fd], [], [], 0.4)[0]:
            d = os.read(fd, 4096)
            if not d:
                break
            buf += d
    except OSError:
        pass
    status = "ok"
    try:
        wpid, st = os.waitpid(pid, os.WNOHANG)
        if wpid and os.WIFSIGNALED(st):
            status = f"crash(sig{os.WTERMSIG(st)})"
        elif wpid:
            status = f"exit{os.WEXITSTATUS(st)}"
    except ChildProcessError:
        status = "gone"
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass
    txt = re.sub(r"\x1b\[[0-9;?]*[a-zA-Z]", "", buf.decode(errors="replace"))
    return status, txt


def alive_and_clean(status, txt):
    return status == "ok" and "tvprintf failed" not in txt and "fatal error" not in txt


# [1] plain `help` (the short blurb)
st, txt = run_help("")
check("[1] `help` runs without crash", alive_and_clean(st, txt), f"({st})")

# [2] `help all` -- walks every command's help string through the printf path
st, txt = run_help("all")
check("[2] `help all` runs without crash (was: tvprintf fatal at montecarlo)",
      alive_and_clean(st, txt), f"({st})")

# [3] `help montecarlo` -- the specific regressor; the % must render literally
st, txt = run_help("montecarlo")
line = next((l for l in txt.splitlines() if "Wilson" in l), "")
check("[3] `help montecarlo` runs and renders a literal '95% CI'",
      alive_and_clean(st, txt) and "95% CI" in line,
      f"({st}; line={line.strip()[:60]!r})")

# [4] STATIC class-guard over commands.c help strings
hazards = []
if os.path.isfile(COMMANDS_C):
    src = open(COMMANDS_C, encoding="utf-8", errors="replace").read()
    for m in re.finditer(r'"((?:[^"\\]|\\.)*)"', src):
        s = m.group(1)
        if "%" not in s:
            continue
        toks = re.findall(r"%.", s)
        bad = [t for t in toks if t not in ("%s", "%%")]
        # a trailing bare '%' at end-of-literal also can't be caught by %. above
        trailing = s.endswith("%") and not s.endswith("%%")
        if bad or trailing or s.count("%s") > 1:
            ln = src[:m.start()].count("\n") + 1
            hazards.append((ln, toks, s[:70]))
    check("[4] no command help string has a printf-format hazard "
          "(bare % / multiple %s)",
          not hazards,
          "" if not hazards else f"({len(hazards)} found: {hazards[:2]})")
else:
    # source not present (running against a packaged binary only) -- skip, don't fail
    check("[4] static help-string scan (source not present -- skipped)", True,
          "(commands.c not found)")

print(f"\n{passed} passed, {failed} failed")
raise SystemExit(1 if failed else 0)
