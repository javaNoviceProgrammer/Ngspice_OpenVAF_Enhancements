#!/usr/bin/env python3
"""Enhancement-378: a Verilog-A `$fatal` aborts the operating point.

`CKTop` reads any non-zero return from `NIiter` as "did not converge" and walks
its whole ladder in response: gmin stepping, source stepping, pseudo-transient,
optran. A Verilog-A fatal returns `E_PANIC` through that same channel, so the
solver could not tell "this model refuses to evaluate" from "this circuit is hard
to solve" -- and answered a fatal by trying harder.

TWO CONSEQUENCES, and the second is the damaging one:

  * Every aid re-evaluates every device, so the model re-raised the same fatal on
    each pass. Measured before the fix: 373 evaluations for one device, and
    exactly 373*N for N devices -- it is one message per device evaluation.
  * The run then ended with `Error: Transient op failed, timestep too small`,
    which names CONVERGENCE. Someone whose model has a typo'd `$simparam` name is
    told their circuit will not converge.

Enhancement-55 added exactly this guard to the transient time-stepping loop in
`dctran.c`, with a comment that the error was otherwise "swallowed by the retry
logic". The operating-point path never got the same treatment, and a `.tran` hits
it too, because a transient computes its operating point first.

WHY THE TEST IS EXACT rather than a heuristic: `E_PANIC` is 1 and the
non-convergence code `E_ITERLIM` is `E_PRIVATE+3` = 103. They are distinct values,
so checking `converged == E_PANIC` cannot mistake a stalled Newton solve for a
fatal. The guard is placed after the plain solve AND after each aid, because a
model may only fatal at a bias some later aid happens to reach.

THE ACCEPT HALF MATTERS MOST. A guard that aborted too eagerly would break every
circuit that legitimately needs gmin or source stepping, so this file also checks
that a hard circuit still solves and that a plain circuit is untouched.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF as OPENVAF  # noqa: E402

checks = passed = 0

FATAL_VA = """`include "disciplines.vams"
module opfatal(a, c);
  inout a, c; electrical a, c;
  analog begin
    if (V(a,c) > 0.05) $fatal(1, "MODEL_FATAL");
    I(a,c) <+ 1e-3*V(a,c);
  end
endmodule
"""

# an unknown $simparam name is a fatal RUNTIME error rather than an explicit
# $fatal, and reaches the same channel -- see Enhancement-377
SIMPARAM_VA = """`include "disciplines.vams"
module opsimp(a, c);
  inout a, c; electrical a, c;
  (* desc="s" *) string s;
  analog begin
    s = $simparam$str("no_such_name");
    I(a,c) <+ 1e-3*V(a,c);
  end
endmodule
"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag):
    d = os.path.join(HERE, "_of_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d, exist_ok=True)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, "m.va", "-o", "m.osdi"], cwd=d, env=env,
                       capture_output=True, text=True, timeout=600, errors="replace")
    return os.path.join(d, "m.osdi") if r.returncode == 0 else None


def run(deck, tag):
    p = os.path.join(HERE, "_of_%s.cir" % tag)
    open(p, "w").write(deck)
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=900, errors="replace")
    return r.stdout, r.stderr


def deck(osdi, model, ndev, analysis):
    inst = "\n".join("N%d a 0 %s" % (i + 1, model) for i in range(ndev))
    return ("opfatal\nV1 a 0 dc 0.4\n%s\n.model %s %s()\n"
            ".control\noption noacct\npre_osdi %s\n%s\n.endc\n.end\n"
            % (inst, model, model, osdi, analysis))


def main():
    osdi = build(FATAL_VA, "f")
    if not osdi:
        check("fatal model builds", False, "compile failed")
        return finish()

    # ---- 1. the fatal aborts instead of driving the convergence ladder -------
    out, err = run(deck(osdi, "opfatal", 1, "op"), "op1")
    both = out + err
    n1 = both.count("MODEL_FATAL")
    check("$fatal in an op is raised once, not once per retry", n1 <= 2,
          "%d emissions (pre-fix: 380)" % n1)
    check("the verdict names the fatal, not a timestep failure",
          "aborting" in both and "timestep too small" not in both,
          "pre-fix said 'Transient op failed, timestep too small'")
    check("no convergence aid was started",
          "gmin stepping" not in both and "source stepping" not in both,
          "the ladder must not run at all")

    # ---- 2. it does not scale with device count any more ---------------------
    out, err = run(deck(osdi, "opfatal", 3, "op"), "op3")
    n3 = (out + err).count("MODEL_FATAL")
    check("emission count does not scale with device count", n3 <= 3 * 2,
          "1 device -> %d, 3 devices -> %d (pre-fix 380 and 1140)" % (n1, n3))

    # ---- 3. a .tran computes an op first, so it is covered too ---------------
    out, err = run(deck(osdi, "opfatal", 1, "tran 1n 10n"), "tr")
    both = out + err
    check("$fatal reached through a .tran's operating point also aborts",
          both.count("MODEL_FATAL") <= 2 and "timestep too small" not in both,
          "%d emissions" % both.count("MODEL_FATAL"))

    # ---- 4. a fatal RUNTIME error takes the same path ------------------------
    osdi2 = build(SIMPARAM_VA, "s")
    if osdi2:
        out, err = run(deck(osdi2, "opsimp", 1, "op"), "sp")
        both = out + err
        check("an unknown $simparam aborts rather than retrying",
              both.count("unknown $simparam") <= 2,
              "%d emissions (pre-fix: 373)" % both.count("unknown $simparam"))
    else:
        check("an unknown $simparam aborts rather than retrying", False, "build failed")

    # ---- 5. THE ACCEPT HALF: the ladder must still work ----------------------
    out, err = run(
        "hard dc\nV1 in 0 dc 5\nR1 in a 1k\nD1 a 0 dmod\nD2 a 0 dmod\n"
        ".model dmod d(is=1e-16 n=1)\n"
        ".control\noption noacct\nop\nprint v(a)\n.endc\n.end\n", "hard")
    m = re.search(r"^v\(a\)\s*=\s*([-+0-9.eE]+)", out, re.M)
    check("an ordinary circuit still solves its operating point",
          m is not None and 0.5 < float(m.group(1)) < 1.2,
          "v(a) = %s" % (m.group(1) if m else "not printed"))

    # a circuit that needs gmin stepping must still reach it and succeed
    out, err = run(
        "needs aid\nV1 in 0 dc 10\nR1 in a 1meg\nD1 a 0 dm\n"
        ".model dm d(is=1e-18 n=1 rs=0)\n.options noopiter\n"
        ".control\noption noacct\nop\nprint v(a)\n.endc\n.end\n", "aid")
    m = re.search(r"^v\(a\)\s*=\s*([-+0-9.eE]+)", out, re.M)
    check("a circuit forced onto the convergence aids still converges",
          m is not None, "noopiter forces gmin stepping; v(a) = %s"
          % (m.group(1) if m else "not printed"))

    return finish()


def finish():
    for j in os.listdir(HERE):
        q = os.path.join(HERE, j)
        if j.startswith("_of_"):
            shutil.rmtree(q, ignore_errors=True) if os.path.isdir(q) else os.remove(q)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
