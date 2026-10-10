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

Enhancement-841 (F4): each sens perturbation re-runs a model's DEVsetup into its
own matrix, binding those devices' pointers there, and sens freed that matrix
without binding them back -- a second `.sens` in one deck (or anything after a
sens that runs without a new setup) loaded through dangling pointers: "singular
matrix" on a resistor divider, a fault in RESload under Guard Malloc.
  [6] two dc `.sens`, a dc and an ac one, two over an OSDI resistor, and a
      `.sens` then an `.sp`: every one runs, with the closed-form sensitivity

Enhancement-842 (F5): `envelope` checked only that a matrix existed after its
settling transient; a device refused at setup (a lossless line with z0 = 0)
leaves one and no solution vector, and EFanalysis copied from NULL.
  [7] envelope after a setup refusal is refused with a message; the deck runs on.
      Control: envelope over a divider with no charges, which has no state vector
      (the first cut of the check asked for one and refused it).
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


def run_deck(text, tag, extra=None):
    """Run a whole deck; return (rc, output)."""
    for name, body in (extra or {}).items():
        with open(os.path.join(WORK, name), "w") as f:
            f.write(body)
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(text)
    env = dict(os.environ)
    if GUARD:
        env["DYLD_INSERT_LIBRARIES"] = GMALLOC
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300,
                       cwd=WORK, env=env, errors="replace")
    return p.returncode, p.stdout + p.stderr


def sens_vals(out, name):
    return [float(m) for m in re.findall(rf"^{re.escape(name)} = (\S+)", out, re.M)]


# [6] Enhancement-841: d v(mid)/d r1 = -r2/(r1+r2)^2 = -1.875e-4 with r1 = 1k, r2 = 3k
DIV = "* sens twice\nv1 in 0 dc 1 ac 1\nr1 in mid 1k\nr2 mid 0 3k\n"
rc, out = run_deck(DIV + ".sens v(mid)\n.sens v(mid)\n.control\nrun\nsetplot\nsetplot sens1\nprint r1\n"
                   "setplot sens2\nprint r1\necho SURVIVED\n.endc\n.end\n", "6a")
v = sens_vals(out, "r1")
check("[6] two dc .sens in one deck: both run, d v(mid)/d r1 = -1.875e-4 twice, no singular matrix",
      survived(rc, out) and len(v) == 2 and all(abs(x + 1.875e-4) < 1e-9 for x in v) and "singular" not in out,
      f"rc={rc} r1={v}")
rc, out = run_deck(DIV + ".sens v(mid)\n.sens v(mid) ac dec 1 1 1k\n.control\nrun\nsetplot sens1\n"
                   "let m = mag(r1[0])\nprint m\nsetplot sens2\nlet m = mag(r1[0])\nprint m\necho SURVIVED\n.endc\n.end\n", "6b")
v = sens_vals(out, "m")
check("[6] a dc and an ac .sens in one deck: both run, |d v(mid)/d r1| = 1.875e-4 in each (at 1 Hz in the ac one)",
      survived(rc, out) and "singular" not in out and len(v) == 2 and all(abs(x - 1.875e-4) < 1e-9 for x in v),
      f"rc={rc} m={v}")
VA = '''`include "disciplines.vams"
module vr(a, b); inout a, b; electrical a, b; parameter real r = 1k from (0:inf);
analog I(a, b) <+ V(a, b)/r;
endmodule
'''
VADIR = os.path.join(WORK, "va")
os.makedirs(VADIR, exist_ok=True)
with open(os.path.join(VADIR, "vr.va"), "w") as f:
    f.write(VA)
from _setup import VAF as OPENVAF  # noqa: E402
cr = subprocess.run([OPENVAF, "vr.va", "-o", "vr.osdi"], cwd=VADIR, capture_output=True, text=True)
rc, out = run_deck("* sens osdi twice\n.control\npre_osdi " + os.path.join(VADIR, "vr.osdi") + "\n.endc\n"
                   "v1 in 0 dc 1\nn1 in mid mr\n.model mr vr r=1k\nr2 mid 0 3k\n.sens v(mid)\n.sens v(mid)\n"
                   ".control\nrun\nsetplot sens1\nprint r2\nsetplot sens2\nprint r2\necho SURVIVED\n.endc\n.end\n", "6c")
v = sens_vals(out, "r2")
check("[6] two .sens over an OSDI resistor: both run, d v(mid)/d r2 = r1/(r1+r2)^2 = 6.25e-5 twice",
      cr.returncode == 0 and survived(rc, out) and len(v) == 2 and all(abs(x - 6.25e-5) < 1e-9 for x in v),
      f"rc={rc} r2={v}")
rc, out = run_deck("* sens then sp\nv1 in 0 dc 1 ac 1 portnum 1 z0 50\nr1 in mid 1k\nr2 mid 0 3k\nr3 mid out 50\n"
                   "v2 out 0 dc 0 ac 0 portnum 2 z0 50\n.sens v(mid)\n.sp lin 1 1k 1k\n.control\nrun\nsetplot\n"
                   "echo SURVIVED\n.endc\n.end\n", "6e")
check("[6] a .sens then an .sp, which runs after it without a new setup: both run, no singular matrix",
      survived(rc, out) and "singular" not in out and "sens1" in out and "sp1" in out, f"rc={rc}")
rc, out = run_deck(DIV + ".sens v(mid)\n.control\nrun\nprint r1\necho SURVIVED\n.endc\n.end\n", "6d")
v = sens_vals(out, "r1")
check("[6] (control) one .sens: d v(mid)/d r1 = -1.875e-4",
      survived(rc, out) and len(v) == 1 and abs(v[0] + 1.875e-4) < 1e-9, f"rc={rc} r1={v}")

# [7] Enhancement-842: envelope after a device refused at setup
rc, out = run_deck("* envelope refused\nv1 1 0 dc 1 sin(0 1 1meg)\nr1 1 2 1k\nc1 2 0 1n\n"
                   "t1 2 0 3 0 z0=0 td=1n\nr2 3 0 50\n.control\nenvelope 2 1meg 10u\necho SURVIVED\n.endc\n.end\n", "7a")
check("[7] envelope after a lossless line refused at setup (z0 = 0): refused with a message, the deck runs on",
      survived(rc, out) and "envelope: the settling transient did not run" in out, f"rc={rc}")
rc, out = run_deck("* envelope without charges\nv1 in 0 dc 0 sin(0 1 1meg)\nr1 in out 1k\nr2 out 0 1k\n"
                   ".control\nenvelope out 1meg 20u\nprint out_amp[1]\necho SURVIVED\n.endc\n.end\n", "7b")
check("[7] (control) envelope over a divider with no charges, so no state vector: it runs, out_amp = 0.5",
      survived(rc, out) and re.search(r"^out_amp\[1\] = 5\.0*e-01", out, re.M) is not None, f"rc={rc}")

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
