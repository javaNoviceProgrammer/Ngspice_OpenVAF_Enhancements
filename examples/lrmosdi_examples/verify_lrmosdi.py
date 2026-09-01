#!/usr/bin/env python3
"""Enhancement-529: the ngspice OSDI layer, audited and fixed.

What this suite pins:

  * ORIGINAL-OPENVAF v0.3 OBJECTS ARE REJECTED, with a recompile message.
    The old acceptance path read a spec-conformant 0.3 object through the
    extended in-repo layout -- the OsdiNode stride grew 48 -> 56 bytes
    (E-45's nodeset field), so node records were misread (devhelp showed a
    terminal named "V", the units field); the AC-stim/transient-noise code
    read past the 0.3 descriptor's end; and 0.3's five-argument load_noise
    was called with four -- wrong metadata in DC and a transient SIGSEGV
    with zero diagnostics. `fake03.c` is a minimal but functional 0.3
    object written strictly against the published osdi_v0p3.pdf; the suite
    compiles it with the host cc and asserts the clean rejection.
  * A NEGATIVE MULTIPLICITY IS WARNED AND IGNORED on every route --
    `alter @n1[m]=-2` included, which used to APPLY it: the device
    sign-inverted (a resistor sourcing current) and the compiled sqrt(m)
    noise factor made .noise print 'onoise_spectrum = nan' silently.
    m=0 stays the SILENT disable-this-instance idiom (E-426), and
    positive m keeps scaling exactly.
  * devhelp lists no phantom "(null)" parameter row (the synthesized `m`
    alias slot is counted only when the descriptor carries $mfactor).
  * An unknown $limit name still falls back to no limiting and LOADS
    (E-520, re-pinned here from the layer side).

The OpenMP eval branch's @(initial_step) parity fix (task-local
OsdiSimInfo) is compile-checked only -- the committed binaries are built
without OpenMP.
"""

import atexit
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402
from _setup import VAF as OPENVAF  # noqa: E402
from _setup import check_both_solvers  # noqa: E402

check_both_solvers(__file__)


def _cleanup():
    for junk in os.listdir(HERE):
        if junk.startswith("_lo_"):
            try:
                os.remove(os.path.join(HERE, junk))
            except OSError:
                pass


atexit.register(_cleanup)

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run_deck(deck, tag, timeout=120):
    p = os.path.join(HERE, f"_lo_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "[TIMEOUT]"


def num(out, name):
    m = re.search(rf"^{re.escape(name)}\s*=\s*(\S+)", out, re.M)
    try:
        return float(m.group(1)) if m else None
    except ValueError:
        return None


def close(a, b, tol=1e-9):
    return a is not None and abs(a - b) <= tol


# ---- [1] v0.3 objects are rejected -----------------------------------------
print("original-OpenVAF v0.3 objects (broken layout) are rejected:")
fake = os.path.join(HERE, "_lo_fake03.osdi")
cc = subprocess.run(["cc", "-shared", "-fPIC", "-o", fake,
                     os.path.join(HERE, "fake03.c")],
                    capture_output=True, text=True)
check("the published-spec 0.3 object compiles with the host cc",
      cc.returncode == 0, (cc.stderr or "").strip()[:60])
if cc.returncode == 0:
    out = run_deck("lrmosdi 0.3 rejection\nV1 a 0 dc 1\nN1 a b m3\n.model m3 res03\n"
                   ".op\n.control\npre_osdi _lo_fake03.osdi\nrun\nquit\n.endc\n.end\n",
                   "f03")
    check("pre_osdi rejects it with the recompile message",
          "original-OpenVAF" in out and "recompile" in out,
          next((l.strip()[:64] for l in out.splitlines()
                if "OSDI" in l and "0.3" in l), ""))
    check("...and the library is NOT loaded (no silent misread)",
          "couldn't be loaded" in out, "")

# ---- [2] the multiplicity guard --------------------------------------------
print("\nthe multiplicity m on OSDI devices:")
rc = subprocess.run([OPENVAF, os.path.join(HERE, "res.va"), "-o",
                     os.path.join(HERE, "_lo_res.osdi")], cwd=HERE,
                    capture_output=True, text=True).returncode
check("res.va compiles", rc == 0)
BASE = ("lrmosdi m guard\nV1 in 0 2.0\nNR1 in 0 mr\n.model mr myres(r=1k)\n"
        ".control\npre_osdi _lo_res.osdi\n{alter}op\nprint i(V1)\nquit\n.endc\n.end\n")
out = run_deck(BASE.format(alter="alter @NR1[m]=-2\n"), "mneg")
check("alter m=-2 is warned and IGNORED (i stays -2 mA; it used to "
      "SOURCE +4 mA)", "is negative" in out and close(num(out, "i(v1)"), -2e-3),
      f"i={num(out, 'i(v1)')}")
NOISE = ("lrmosdi m noise\nV1 in 0 DC 0 AC 1\nR0 in 0 1k\nNR1 a 0 mr\nR1 a 0 1k\n"
         ".model mr myres(r=1k)\n.control\npre_osdi _lo_res.osdi\n"
         "alter @NR1[m]=-2\nnoise v(a) V1 lin 1 1k 1k\nsetplot noise1\n"
         "print onoise_spectrum\nquit\n.endc\n.end\n")
out = run_deck(NOISE, "mnn")
on = num(out, "onoise_spectrum")
check("...and .noise stays FINITE (it printed nan)",
      on is not None and on == on and on > 0, f"onoise={on}")
out = run_deck(BASE.format(alter="alter @NR1[m]=0\n"), "mz")
check("m=0 stays the SILENT disable idiom (i = 0, no warning)",
      "negative" not in out and close(num(out, "i(v1)"), 0.0, 1e-15),
      f"i={num(out, 'i(v1)')}")
out = run_deck(BASE.format(alter="alter @NR1[m]=4\n"), "m4")
check("m=4 scales exactly (i = -8 mA)", close(num(out, "i(v1)"), -8e-3),
      f"i={num(out, 'i(v1)')}")

# ---- [3] devhelp has no phantom row ----------------------------------------
print("\ninstance-parameter table integrity:")
out = run_deck("lrmosdi devhelp\nV1 in 0 1\nNR1 in 0 mr\n.model mr myres(r=1k)\n"
               ".op\n.control\npre_osdi _lo_res.osdi\ndevhelp myres\nquit\n"
               ".endc\n.end\n", "dh")
check("devhelp lists the _mfactor/m alias rows and no '(null)' phantom",
      "_mfactor" in out and "(null)" not in out, "")

# ---- [4] the $limit fallback still loads and runs (E-520) ------------------
print("\n$limit unknown-name fallback (LRM 9.17.3, E-520):")
va = os.path.join(HERE, "_lo_blim.va")
with open(va, "w") as f:
    f.write('`include "disciplines.vams"\n'
            "module blim(a, c);\n  inout a, c; electrical a, c;\n"
            "  analog I(a,c) <+ 1e-3*$limit(V(a,c), \"foolim\", 1.0);\n"
            "endmodule\n")
subprocess.run([OPENVAF, va, "-o", os.path.join(HERE, "_lo_blim.osdi")],
               cwd=HERE, capture_output=True, text=True)
out = run_deck("lrmosdi limit fallback\nV1 a 0 dc 1\nN1 a 0 mb\n.model mb blim\n"
               ".op\n.control\npre_osdi _lo_blim.osdi\nrun\nprint i(v1)\nquit\n"
               ".endc\n.end\n", "bl")
check("the model LOADS with the 9.17.3 no-limiting warning and runs",
      "no limiting" in out and close(num(out, "i(v1)"), -1e-3),
      f"i={num(out, 'i(v1)')}")

print(f"\n{'ALL PASS' if checks == passed else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if checks == passed else 1)
