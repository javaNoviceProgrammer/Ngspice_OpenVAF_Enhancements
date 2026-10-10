#!/usr/bin/env python3
"""Enhancement-840 (F3 of the 2026-10-10 robustness and correctness campaign): a
refused analysis command no longer leaves the circuit pointing at a freed job.

The circuit keeps CKTcurJob on the last job it ran. An interactive analysis
command deletes the previous command's task -- and its jobs -- before it parses
its own card, and a card refused there (`sens v(nosuch)`, `ac dec 0 1 1`,
`tran 1u`, `tf v(nosuch) v1`, `noise v(nosuch) ...`) never reaches CKTdoJob, so
CKTcurJob was left on freed memory. The next `reset` read its JOBtype in
DCtran_step_quit: a use-after-free, SIGSEGV under macOS Guard Malloc and silent
without it. The deck fuzz of the campaign met it as `op`, `sens v(1)`, `reset`.
CKTdelTask now clears the pointer when it frees the job it names (closing a
stepped transient's open plot first, as `reset` would), and `remcirc` deletes
the tasks before it frees the circuit they belong to.

The decks run under Guard Malloc where it exists (macOS), which faults at the
freed access, so a regression fails every time; elsewhere they run plainly and
only what the deck prints is checked.

  [1] after an `op`, each refused command, then `reset`: the deck runs on, and
      the `op` after it reads v(a) = 1
  [2] the same after a `tran`
  [3] a paused, stepped transient, a refused `sens`, `reset`: the transient's
      plot is kept
  [4] `remcirc` after a refused command, and with a second circuit loaded
  [5] (control) `op`, `op`, `reset`
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

GMALLOC = "/usr/lib/libgmalloc.dylib"
GUARD = sys.platform == "darwin" and os.path.exists(GMALLOC)
WORK = tempfile.mkdtemp(prefix="jobreset_")
checks = passed = 0

REFUSED = ["sens v(nosuch)", "ac dec 0 1 1", "tran 1u", "tf v(nosuch) v1", "noise v(nosuch) v1 dec 1 1 1k"]


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(body, tag, extra=None):
    """Run a deck whose control block is `body`; return (rc, output)."""
    for name, text in (extra or {}).items():
        with open(os.path.join(WORK, name), "w") as f:
            f.write(text)
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* jobreset {tag}\nv1 a 0 sin(0 1 1meg) dc 1\nr1 a b 1k\nc1 b 0 1n\n"
                f".control\n{body}\n.endc\n.end\n")
    env = dict(os.environ)
    if GUARD:
        env["DYLD_INSERT_LIBRARIES"] = GMALLOC
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300,
                       cwd=WORK, env=env, errors="replace")
    return p.returncode, p.stdout + p.stderr


def survived(rc, out):
    return rc is not None and rc >= 0 and "SURVIVED" in out


print(f"(Guard Malloc {'on' if GUARD else 'not available: values only'})")
for pre, sec in (("op", "[1]"), ("tran 10n 1u", "[2]")):
    for k, cmd in enumerate(REFUSED):
        rc, out = run(f"{pre}\n{cmd}\nreset\nop\nprint v(a)\necho SURVIVED", f"{sec[1]}_{k}")
        check(f"{sec} after `{pre}`, a refused `{cmd}`, then reset: the deck runs on, v(a) = 1",
              survived(rc, out) and re.search(r"v\(a\) = 1\.0*e\+00", out) is not None,
              f"rc={rc}" + ("" if "SURVIVED" in out else " " + out[-200:].replace("\n", " | ")))

rc, out = run("stop after 20\ntran 10n 5u\nstep 3\nsens v(nosuch)\nreset\nop\nsetplot\necho SURVIVED", "3")
check("[3] a stepped transient, a refused sens, reset: the deck runs on and tran1 is kept",
      survived(rc, out) and "tran1" in out, f"rc={rc}")

rc, out = run("op\nsens v(nosuch)\nremcirc\necho SURVIVED", "4a")
check("[4] remcirc after a refused command: the tasks go before the circuit", survived(rc, out), f"rc={rc}")
rc, out = run("op\nsource c2.cir\nop\nprint v(x)\nsetcirc 1\nac dec 0 1 1\nremcirc\nsetcirc\necho SURVIVED", "4b",
              {"c2.cir": "* second\nv2 x 0 2\nr2 x 0 1k\n.end\n"})
check("[4] two circuits: a refused command on the first, remcirc, the second still listed",
      survived(rc, out) and re.search(r"v\(x\) = 2\.0*e\+00", out) is not None and "second" in out, f"rc={rc}")

rc, out = run("op\nop\nreset\nop\nprint v(a)\necho SURVIVED", "5")
check("[5] (control) op, op, reset: v(a) = 1", survived(rc, out) and "v(a) = 1" in out, f"rc={rc}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
