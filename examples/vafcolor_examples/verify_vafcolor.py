#!/usr/bin/env python3
"""
verify_vafcolor.py -- openvaf-r colours a diagnostic only when the stream it writes
is a terminal (Enhancement-574).

The compiler chose its colours with termcolor's `ColorChoice::Auto`, which consults
TERM and NO_COLOR and never the stream. From any colour terminal, every diagnostic
written into a pipe -- a build log, a test harness, ngspice's own `pre_osdi -va`
capture -- carried ANSI escape codes: the line that reads "error: ..." on the
screen began with `\x1b[0m\x1b[1m\x1b[38;5;9m` in the file. Five suites that parse
diagnostics (lrmdisc, lrmfuncs, natureref, vafdeterminism, vafice) failed in a
regression sweep run from an ordinary terminal and passed from a harness with TERM
unset, which is how this was found.

  1. into a pipe, with TERM naming a colour terminal: no escape code in a
     diagnostic, in the "Finished building" line, in --lints, in --supported-targets
  2. on a pseudo-terminal the colours are still there, and NO_COLOR / TERM=dumb
     still turn them off -- the terminal case keeps termcolor's own policy
"""
import os
import pty
import select
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import VAF as OPENVAF

HDR = '`include "disciplines.vams"\n'
GOOD = HDR + "module g(p, n);\n  inout p, n; electrical p, n;\n  analog I(p,n) <+ V(p,n) / 1000.0;\nendmodule\n"
BAD = HDR + "module b(p, n);\n  inout p, n; electrical p, n;\n  analog I(p,n) <+ V(p,n) / nosuch;\nendmodule\n"
ESC = "\x1b["


def write(name, text):
    p = os.path.join(HERE, name)
    with open(p, "w") as fh:
        fh.write(text)
    return p


def piped(args, **env):
    e = dict(os.environ, RAYON_NUM_THREADS="1")
    e.pop("NO_COLOR", None)
    e.update(env)
    r = subprocess.run([OPENVAF] + args, cwd=HERE, capture_output=True, text=True,
                       timeout=300, env=e)
    return r.returncode, r.stdout + r.stderr


def on_pty(args, **env):
    """Run the compiler with stdout AND stderr on a pseudo-terminal; return its output."""
    e = dict(os.environ, RAYON_NUM_THREADS="1")
    e.pop("NO_COLOR", None)
    e.update(env)
    master, slave = pty.openpty()
    proc = subprocess.Popen([OPENVAF] + args, cwd=HERE, stdin=slave, stdout=slave,
                            stderr=slave, env=e, close_fds=True)
    os.close(slave)
    out = b""
    while True:
        r, _, _ = select.select([master], [], [], 60)
        if not r:
            break
        try:
            chunk = os.read(master, 65536)
        except OSError:
            break
        if not chunk:
            break
        out += chunk
    proc.wait(timeout=60)
    os.close(master)
    return proc.returncode, out.decode("utf-8", "replace")


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    good = write("_good.va", GOOD)
    bad = write("_bad.va", BAD)
    term = {"TERM": "xterm-256color"}

    print("[1] into a pipe, TERM=xterm-256color: no escape code anywhere")
    rc, out = piped([bad, "-o", "_bad.osdi"], **term)
    check("a diagnostic is plain text", rc != 0 and ESC not in out and "error" in out,
          repr(out.strip().splitlines()[0][:60]) if out.strip() else "no output")
    check("...and its first line begins with `error:` at column 0",
          any(l.startswith("error:") for l in out.splitlines()), "")
    rc, out = piped([good, "-o", "_good.osdi"], **term)
    check("the `Finished building` line is plain text", rc == 0 and ESC not in out and "Finished" in out,
          repr(out.strip()[:60]))
    rc, out = piped(["--lints"], **term)
    check("--lints (stdout) is plain text", rc == 0 and ESC not in out and "ERRORS" in out, "")
    rc, out = piped(["--supported-targets"], **term)
    check("--supported-targets (stdout) is plain text", rc == 0 and ESC not in out and "TARGETS" in out, "")
    rc, out = piped([bad, "-o", "_bad.osdi"], TERM="dumb")
    check("TERM=dumb into a pipe: plain text as before", rc != 0 and ESC not in out, "")

    print("[2] on a pseudo-terminal the colours are kept, and the usual switches still work")
    rc, out = on_pty([bad, "-o", "_bad.osdi"], **term)
    check("TERM=xterm-256color on a pty: the diagnostic IS coloured", rc != 0 and ESC in out,
          "" if ESC in out else "no escape code")
    rc, out = on_pty([good, "-o", "_good.osdi"], **term)
    check("...and so is `Finished`", rc == 0 and ESC in out, "")
    rc, out = on_pty([bad, "-o", "_bad.osdi"], TERM="xterm-256color", NO_COLOR="1")
    check("NO_COLOR=1 on a pty: plain", rc != 0 and ESC not in out, "")
    rc, out = on_pty([bad, "-o", "_bad.osdi"], TERM="dumb")
    check("TERM=dumb on a pty: plain", rc != 0 and ESC not in out, "")

    for f in ("_good.va", "_bad.va", "_good.osdi", "_bad.osdi"):
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass
    print("\nALL PASS: {}/10 passed".format(10) if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
