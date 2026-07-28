#!/usr/bin/env python3
"""Enhancement-351: `sens` on an OSDI model that allocates an internal node.

Running `sens` on a circuit containing one used to kill the process outright:

    Internal Error: node allocation in DEVsetup() during sensitivity analysis,
    this will cause serious troubles !, please report this issue !
    ERROR: fatal error in ngspice, exit(1)

`sens` re-invokes every model's DEVsetup() to stamp the perturbation matrix and
requires that doing so allocate no nodes -- it snapshots CKTlastNode around the
call and calls controlled_exit() if it moved. Built-in devices satisfy that by
guarding their allocation on "not already allocated" (the inductor's
`if (here->INDbrEq == 0)`); OSDI's setup had no such guard and allocated a fresh
internal node every time it was called.

That made `.sens` unusable with essentially every production compact model --
BSIM, HICUM, PSP and EKV all carry internal nodes for their terminal
resistances -- and it failed by taking the session down rather than refusing.

  [1] the analysis that used to be fatal now completes, on both solvers
  [2] a model with NO internal node still works (it always did -- guards it)
  [3] the sensitivities are CORRECT, not merely non-fatal: an internal-node
      model and an electrically identical one without must agree
  [4] and they match closed form for the shared built-in resistor
  [5] repeated `sens` in one session stays stable (setup runs again each time)
  [6] a real re-setup after `reset` still allocates -- the node record must not
      outlive the nodes
  [7] every other analysis is unaffected
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

MODELS = ["os_rs", "os_plain"]
R1 = 1000.0
RL = 3010.0                       # os_rs: r=3000 + rs=10; os_plain: r=3010

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build():
    for m in MODELS:
        out = os.path.join(HERE, "_%s.osdi" % m)
        r = subprocess.run([OPENVAF, os.path.join(HERE, "va", "%s.va" % m), "-o", out],
                           capture_output=True, text=True, timeout=900)
        if r.returncode != 0 or not os.path.exists(out):
            print("FATAL: %s failed to compile\n%s" % (m, r.stdout + r.stderr))
            sys.exit(2)


DEV = {
    "os_rs":    "N1 out 0 m1\n.model m1 os_rs(r=3000 rs=10)\n",
    "os_plain": "N1 out 0 m1\n.model m1 os_plain(r=3010)\n",
}


def run(model, ctl, solver="sparse", timeout=300):
    opt = ".option klu\n" if solver == "klu" else ""
    p = os.path.join(HERE, "_os.cir")
    with open(p, "w") as f:
        f.write("osdisens\n%sV1 in 0 dc 1 ac 1\nR1 in out 1k\n%sC1 out 0 1n\n"
                ".control\npre_osdi _%s.osdi\noption noacct\nset numdgt=14\n%s\n"
                ".endc\n.end\n" % (opt, DEV[model], model, ctl))
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
    except subprocess.TimeoutExpired:
        return -99, "HANG"
    return r.returncode, r.stdout + r.stderr


def sens_of(out, name):
    m = re.search(r"^%s\s*=\s*([-\d.e+]+)\s*$" % re.escape(name), out, re.M)
    return float(m.group(1)) if m else None


def main():
    build()

    # ---- [1] the vector that used to be fatal -------------------------------
    bad = []
    for solver in ("sparse", "klu"):
        rc, out = run("os_rs", "sens v(out)\nprint all\necho SENS_DONE", solver)
        if rc != 0 or "SENS_DONE" not in out or "node allocation in DEVsetup" in out:
            bad.append("%s: rc=%d%s" % (solver, rc,
                       " (node-allocation abort)" if "node allocation" in out else ""))
    check("sens on an internal-node OSDI model completes, both solvers",
          not bad, "; ".join(bad) if bad else "sparse+klu")

    # ---- [2] the no-internal-node model still works -------------------------
    rc, out = run("os_plain", "sens v(out)\nprint all\necho SENS_DONE")
    check("sens on an OSDI model without an internal node still works",
          rc == 0 and "SENS_DONE" in out, "rc=%d" % rc)

    # ---- [3] correct, not merely non-fatal ----------------------------------
    _, a = run("os_rs", "sens v(out)\nprint all")
    _, b = run("os_plain", "sens v(out)\nprint all")
    ra, rb = sens_of(a, "r1"), sens_of(b, "r1")
    va = sens_of(a, "n1_r")
    ok3 = (ra is not None and rb is not None
           and abs(ra - rb) <= 1e-12 * max(abs(ra), abs(rb)))
    check("internal-node and equivalent no-internal-node decks agree",
          ok3, "r1: %s vs %s" % (ra, rb))

    # ---- [4] and both match closed form -------------------------------------
    want_r1 = -RL / (R1 + RL) ** 2
    want_r = R1 / (R1 + RL) ** 2
    ok4 = (ra is not None and abs(ra - want_r1) <= 1e-4 * abs(want_r1)
           and va is not None and abs(va - want_r) <= 1e-4 * abs(want_r))
    check("both match closed form d v(out)/dR", ok4,
          "r1 %.6e vs %.6e ; n1_r %.6e vs %.6e"
          % (ra or 0, want_r1, va or 0, want_r))

    # ---- [5] repeated sens in one session -----------------------------------
    rc, out = run("os_rs", "echo ---S1---\nsens v(out)\nprint all\n"
                           "echo ---S2---\nsens v(out)\nprint all\necho ---END---")
    seg = re.split(r"---S\d---|---END---", out)
    ok5 = False
    if rc == 0 and len(seg) >= 3:
        n1 = re.findall(r"[-+]?\d+\.\d+e[-+]\d+", seg[1])
        n2 = re.findall(r"[-+]?\d+\.\d+e[-+]\d+", seg[2])
        ok5 = bool(n1) and n1 == n2
    check("sens twice in one session gives the same answer", ok5,
          "rc=%d" % rc if not ok5 else "%d values identical" % len(n1))

    # ---- [6] the record must not outlive the nodes --------------------------
    # reset deletes the internal nodes; the next setup has to allocate again.
    rc, out = run("os_rs", "op\nreset\nop\nprint v(out)\nsens v(out)\n"
                           "reset\nop\nprint v(out)\necho CYCLED")
    vals = re.findall(r"v\(out\)\s*=\s*([-\d.e+]+)", out)
    ok6 = (rc == 0 and "CYCLED" in out and len(vals) >= 2
           and abs(float(vals[0]) - float(vals[-1])) <= 1e-12)
    check("reset/re-setup cycles still work after sens", ok6,
          "rc=%d values=%s" % (rc, vals[:3]))

    # ---- [7] no other analysis disturbed ------------------------------------
    broke = []
    for a_name, ctl in (("op", "op\nprint v(out)"),
                        ("dc", "dc v1 0 1 0.25\nprint v(out)"),
                        ("ac", "ac dec 5 1e2 1e6\nprint mag(v(out))[3]"),
                        ("tran", "tran 20n 1u\nmeas tran x FIND v(out) AT=500n"),
                        ("tf", "tf v(out) v1\nprint transfer_function"),
                        ("pz", "pz in 0 out 0 vol pol\nprint all"),
                        ("noise", "noise v(out) v1 dec 3 1e2 1e5\nsetplot noise1\n"
                                  "print onoise_spectrum[0]")):
        rc, out = run("os_rs", ctl + "\necho OK_" + a_name)
        if rc != 0 or ("OK_" + a_name) not in out:
            broke.append("%s(rc=%d)" % (a_name, rc))
    check("every other analysis still runs on the same model",
          not broke, "; ".join(broke) if broke else "7/7")

    for junk in os.listdir(HERE):
        if junk.startswith("_"):
            os.remove(os.path.join(HERE, junk))

    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
