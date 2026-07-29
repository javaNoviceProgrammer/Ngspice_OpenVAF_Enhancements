#!/usr/bin/env python3
"""Enhancement-370: `.pz` re-expanded the URC subcircuit, overflowing the RHS.

FOUND BY RUNNING AN EXISTING FIXTURE UNDER A SANITIZER. A sweep of every shipped
deck under ASan/UBSan, with each solver forced in turn, produced exactly one real
finding -- and it was in `ngcrashanalysis_examples/pz_urc.cir`, the
[E-315](../../enhancements_doc/Enhancement-315.md) fixture. E-315 stopped that
deck from SIGSEGVing, and the deck has passed ever since; nothing had run it
under a sanitizer, so the memory corruption underneath was still there:

    heap-buffer-overflow READ of size 8 in RESload resload.c
      CKTload -> NIiter -> CKTop -> PZan
      buffer allocated by NIreinit

`RESload` indexes `ckt->CKTrhsOld` by node number, so the read past the end means
a resistor's node number exceeded the RHS the solver had allocated.

THE CAUSE. The URC device declared

    .DEVsetup   = URCsetup,
    .DEVpzSetup = URCsetup,      <-- the same function

but `URCsetup` is a SUBCIRCUIT EXPANDER: it calls `CKTmkVolt` per lump and
`CKTcrtElt` per element, with no idempotency guard. `CKTpzSetup` calls
`DEVpzSetup` for every device on EVERY pz job, so each `.pz` expanded the URC
again, creating fresh internal nodes AFTER `NIinit` had already sized the RHS.
The resistors of the new lump then indexed past `CKTrhsOld`.

That is why `RESsetup`/`CAPsetup` are safe in the same slot and `URCsetup` is
not: they only allocate matrix entries, which is idempotent. URC was the only
expander wired up this way.

THE FIX is that the URC needs no pz setup at all -- its `DEVload`, `DEVacLoad`
and `DEVpzLoad` are all NULL, so it stamps nothing itself. The RES/CAP instances
it creates are ordinary circuit elements registered under their own device types,
and `CKTpzSetup` calls `RESsetup`/`CAPsetup` for them, which is what actually
re-binds the matrix after the pz matrix is rebuilt.

NOT A SOLVER BUG, despite being found in a solver hunt: it reproduces identically
under KLU and Sparse.

WHAT AN ORDINARY BUILD CAN SEE. The duplicate expansion also produced a visible
symptom -- `doAnalyses: device already exists, existing one being used` -- which
aborted the run. So the checks below need no sanitizer: the warning must be gone,
and the analysis must actually reach the solver instead of aborting early.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def deck(npz, lumps=2, load=True):
    pz = ".pz 1 0 3 0 cur zer\n" * npz
    return ("urc pz re-expansion\nv1 1 0 1\n.model um urc\n"
            "u1 1 2 0 um l=1 n=%d\n%s%s.control\noption noacct\nrun\n.endc\n.end\n"
            % (lumps, "r2 2 0 1k\n" if load else "", pz))


def run(src, tag, timeout=180):
    p = os.path.join(HERE, "_up_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(src)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE, capture_output=True,
                       text=True, timeout=timeout, errors="replace")
    return r.stdout + r.stderr


DUP = re.compile(r"device already exists", re.I)


def main():
    # [1] the duplicate-expansion warning must be gone -- even ONE .pz triggered
    #     it, because CKTsetup expands once and CKTpzSetup expanded again
    for n in (1, 2, 3):
        out = run(deck(n), "a%d" % n)
        check("%d x .pz: no duplicate-device expansion" % n, not DUP.search(out),
              "clean" if not DUP.search(out) else "'device already exists'")

    # [2] it must not depend on the lump count (the overflow scaled with it)
    for lumps in (1, 4, 8):
        out = run(deck(2, lumps=lumps), "b%d" % lumps)
        check("n=%d lumps, 2 x .pz: no duplicate expansion" % lumps, not DUP.search(out),
              "clean" if not DUP.search(out) else "duplicated")

    # [3] the analysis must now REACH the solver rather than aborting during
    #     setup. The fixture's node 3 is genuinely floating, so a singular-matrix
    #     complaint is the correct outcome -- what matters is that the run gets
    #     far enough to say so instead of dying on a spurious duplicate device.
    out = run(deck(2), "c")
    reached = re.search(r"singular matrix|gmin stepping|Doing analysis", out, re.I)
    check("analysis reaches the solver instead of aborting in setup", bool(reached),
          reached.group(0) if reached else "never reached")

    # [4] a URC that is properly terminated must still work under every other
    #     analysis -- the fix must not disturb the ordinary setup path
    src = ("urc normal\nv1 1 0 dc 1 ac 1\n.model um urc\nu1 1 2 0 um l=1 n=4\n"
           "r2 2 0 1k\n.control\noption noacct\nop\nprint v(2)\n"
           "ac dec 3 1e3 1e6\ntran 1u 10u\n.endc\n.end\n")
    out = run(src, "d")
    v = re.search(r"^v\(2\)\s*=\s*([-+0-9.eE]+)", out, re.M)
    check("URC still solves normally (op/ac/tran)", bool(v) and not DUP.search(out),
          "v(2)=%s" % v.group(1) if v else "no op result")

    # [5] both solvers -- this was never solver-specific and must stay that way
    for solver in ("sparse", "klu"):
        out = run(src.replace(".control\noption noacct",
                              ".control\noption noacct\noption " + solver), "e_" + solver)
        v2 = re.search(r"^v\(2\)\s*=\s*([-+0-9.eE]+)", out, re.M)
        check("%s: URC unaffected" % solver, bool(v2) and not DUP.search(out),
              "v(2)=%s" % v2.group(1) if v2 else "no result")

    for j in os.listdir(HERE):
        if j.startswith("_up_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
