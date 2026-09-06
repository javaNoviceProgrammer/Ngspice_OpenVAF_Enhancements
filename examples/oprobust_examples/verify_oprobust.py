#!/usr/bin/env python3
"""
verify_oprobust.py -- Enhancement-568: operating-point robustness, pinned on BOTH
solvers (KLU and Sparse 1.3 answer identically on every deck below).

  R1  the false-convergence guard (E-256) measured a row's KCL residual against
      |(G*x)_k|, which cancels on a high-gain branch row: a VCVS of gain 1e6 in
      unity feedback converged in 4 Newton iterations and was then declined --
      127 gmin iterations under KLU, Sparse tripping from gain 1e8. The residual
      is now scaled by the MAGNITUDE of the row's terms.
  R2  the XSPICE `pwl` code model behind `E/G ... TABLE` limits its input to a
      fraction of a segment per iteration; in a positive-feedback loop that walk
      never ends (a two-resistor Schmitt trigger: 38000 iterations across gmin,
      source stepping and optran, then failure). Two rules end it: no limiting on
      one linear piece, and Newton's value accepted once the limiter has reversed
      twice at a corner.
  R3  a `.nodeset` is held by REPLACING the node's KCL row; a device between the
      held node and a stiff one may have no equilibrium (a diode clamp asked to
      sit 97 V forward), so the hold ate the whole Newton budget and the junction
      ran to exp() overflow -- 2160 / 1400 iterations, KLU announcing a singular
      matrix at the clamp source, Sparse silent on the same NaN. The hold now
      gets a tenth of the budget (never less than ten passes); the diode's
      exponentials are clamped at MAX_EXP_ARG.
  R4  a loop of ideal voltage-defined branches (two behavioural voltage sources
      feeding each other) has nothing gmin, source stepping, pseudo-transient or
      optran can soften: 37673 iterations, then failure, for a deck whose unique
      solution a damped Newton finds in 53. The ladder now ends with one
      line-search Newton solve -- last, so no converging deck changes.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import math
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = 0
passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def ngspice(deck, name="_o.cir"):
    path = os.path.join(HERE, name)
    with open(path, "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True, text=True, timeout=600)
    return r.stdout + r.stderr


def scalars(out):
    vals = {}
    for line in out.splitlines():
        m = re.match(r"\s*([\w\(\)\[\]#@.,-]+)\s*=\s*([-+0-9.eE]+)", line)
        if m:
            try:
                vals[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                pass
    return vals


def iters(out):
    m = re.search(r"Total iterations\s*=\s*(\d+)", out)
    return int(m.group(1)) if m else None


def aids(out):
    return re.findall(r"Starting ([a-z -]+?)(?: stepping| continuation| \(line search\))?\n", out)


def near(a, b, tol):
    return a is not None and abs(a - b) <= tol


def op_deck(title, body, prints, options=""):
    return (f"* {title}\n{options}{body}\n.control\nop\nprint {prints}\nrusage totiter\n.endc\n.end\n")


SCHMITT = """vin in 0 {vin}
rin in inn 10k
rf out inp 100k
rg inp 0 10k
eamp o1 0 table {{v(inp)-v(inn)}} = (-1m,-5) (1m,5)
ro o1 out 100
rl out 0 10k"""

NPN = ".model qn npn(is=1e-15 bf=100)\n"
FLIPFLOP = """vcc vcc 0 5
rc1 vcc c1 1k
rc2 vcc c2 1k
q1 c1 b1 0 qn
q2 c2 b2 0 qn
rb1 c2 b1 10k
rb2 c1 b2 10k
""" + NPN + ".nodeset v(c1)=5 v(c2)=0.2"

OPAMP_CLAMP = """vin in 0 1
eamp o1 0 in out 1e6
ro o1 out 100
rl out 0 1k
d1 out clamp dd
vclamp clamp 0 3
.model dd d(is=1e-14)"""

RING = """b1 q 0 v=2.5*(1+tanh(6*(v(qb)-2.5)))
r1 q 0 1k
b2 qb 0 v=2.5*(1-tanh(6*(v(q)-2.5)))
r2 qb 0 1k"""

LATCH = """b1 q 0 v=2.5*(1+tanh(6*(v(qb)-2.5)))
r1 q 0 1k
b2 qb 0 v=2.5*(1+tanh(6*(v(q)-2.5)))
r2 qb 0 1k"""


def main():
    print("Enhancement-568: operating-point robustness (R1 guard scale, R2 pwl limiter, "
          "R3 nodeset hold, R4 last-resort damped Newton)")

    # ---- R2: E TABLE Schmitt trigger, DC operating point -------------------------
    print("\n[R2] `E ... TABLE` Schmitt trigger (positive feedback through the pwl code model)")
    for opt in ("", ".option linesearch\n", ".option trustregion\n", ".option noopiter\n"):
        out = ngspice(op_deck("schmitt", SCHMITT.format(vin=1.0), "v(out)", opt))
        v = scalars(out).get("v(out)")
        n = iters(out)
        tag = opt.strip() or "default ladder"
        check(f"schmitt [{tag}]: converges to the -5 V state", near(v, -4.94604, 1e-3), f"v(out)={v}")
        if opt == ".option noopiter\n":
            check(f"schmitt [{tag}]: within 60 iterations", n is not None and n <= 60, f"iterations={n}")
        else:
            check(f"schmitt [{tag}]: plain Newton, no aid, within 30 iterations",
                  n is not None and n <= 30 and not aids(out), f"iterations={n} aids={aids(out)}")

    # the same source written out by hand with a narrower and a wider smoothing domain
    for dom in ("0.01", "0.5"):
        body = SCHMITT.format(vin=1.0).replace(
            "eamp o1 0 table {v(inp)-v(inn)} = (-1m,-5) (1m,5)",
            "eamp o1 0 eamp_int1 0 1\nbeamp eamp_int2 0 v=v(inp)-v(inn)\n"
            "aeamp %v(eamp_int2) %v(eamp_int1) xf\n"
            f".model xf pwl(x_array=[-1m 1m] y_array=[-5 5] input_domain={dom} fraction=true limit=true)")
        out = ngspice(op_deck("schmitt_dom", body, "v(out)"))
        v, n = scalars(out).get("v(out)"), iters(out)
        check(f"schmitt, pwl input_domain={dom}: -5 V state, direct, <= 40 iterations",
              near(v, -4.94604, 1e-3) and n is not None and n <= 40 and not aids(out), f"v(out)={v} iterations={n}")

    # the nodeset picks the state when both exist (vin inside the hysteresis window)
    for ns, want in (("4.9", 4.946043), ("-4.9", -4.94604)):
        out = ngspice(op_deck("schmitt_ns", SCHMITT.format(vin=0.3) + f"\n.nodeset v(out)={ns}", "v(out)"))
        v, n = scalars(out).get("v(out)"), iters(out)
        check(f"schmitt vin=0.3, .nodeset v(out)={ns}: lands on {want:+.3f}, direct, <= 20 iterations",
              near(v, want, 1e-3) and n is not None and n <= 20 and not aids(out), f"v(out)={v} iterations={n}")

    # decks the limiter must NOT disturb: negative feedback, a many-segment table
    out = ngspice(op_deck("nf_table", "vin in 0 0.7\neamp out 0 table {v(in)-v(out)} = (-1m,-5) (1m,5)\nrl out 0 1k", "v(out)"))
    v, n = scalars(out).get("v(out)"), iters(out)
    check("TABLE op-amp in unity negative feedback: 0.69986 V in <= 5 iterations",
          near(v, 0.69986, 1e-4) and n is not None and n <= 5, f"v(out)={v} iterations={n}")
    out = ngspice(op_deck("multiseg", "vin in 0 2\nr1 in x 1k\nr2 x 0 1k\n"
                          "eamp o 0 table {v(x)} = (-3,-1) (-1,-0.9) (-0.5,-0.2) (0,0) (0.5,0.2) (1,0.9) (3,1)\nr3 o x 500",
                          "v(x) v(o)"))
    s, n = scalars(out), iters(out)
    check("seven-point TABLE inside a loop: v(x)=0.83333, v(o)=0.66667, <= 15 iterations",
          near(s.get("v(x)"), 0.833333, 1e-4) and near(s.get("v(o)"), 0.666667, 1e-4) and n is not None and n <= 15,
          f"v(x)={s.get('v(x)')} v(o)={s.get('v(o)')} iterations={n}")

    # transient: the hysteresis thresholds are the circuit's, not the limiter's
    deck = ("* schmitt tran\n.option cshunt=1p\n" + SCHMITT.format(vin="pwl(0 0 1m 2 3m -2 5m 2)") +
            "\n.control\ntran 1u 5m\nmeas tran vin_up find v(in) when v(out)=0 rise=1\n"
            "meas tran vin_dn find v(in) when v(out)=0 fall=1\n.endc\n.end\n")
    out = ngspice(deck)
    s = scalars(out)
    check("schmitt transient (cshunt=1p): switches at vin = -0.4485 / +0.4484",
          near(s.get("vin_up"), -0.44847, 2e-3) and near(s.get("vin_dn"), 0.44844, 2e-3) and "too small" not in out,
          f"vin_up={s.get('vin_up')} vin_dn={s.get('vin_dn')}")

    # ---- R1: high-gain VCVS in unity feedback ------------------------------------
    print("\n[R1] false-convergence guard on a high-gain branch row")
    for gain in ("1e6", "1e8", "1e9"):
        out = ngspice(op_deck("unity", f"vin in 0 1\neamp o1 0 in out {gain}\nro o1 out 100\nrl out 0 1k", "v(out)"))
        v, n = scalars(out).get("v(out)"), iters(out)
        check(f"VCVS gain {gain}, unity feedback: v(out)=1, plain Newton, <= 6 iterations",
              near(v, 1.0, 1e-5) and n is not None and n <= 6 and not aids(out), f"v(out)={v} iterations={n} aids={aids(out)}")
    out = ngspice(op_deck("gspread", "v1 in 0 1\nr1 in a 1e15\nr2 a b 1e-6\nr3 b c 1e12\nd1 c 0 dd\nr4 c 0 1e6\n.model dd d(is=1e-14)", "v(c)"))
    v, n = scalars(out).get("v(c)"), iters(out)
    check("21 decades of conductance spread into a diode: v(c)=-1 mV, plain Newton, <= 6 iterations (was 132 gmin iterations)",
          near(v, -0.001, 1e-6) and n is not None and n <= 6 and not aids(out), f"v(c)={v} iterations={n} aids={aids(out)}")

    # ---- R3: a nodeset the circuit cannot satisfy ---------------------------------
    print("\n[R3] `.nodeset` hold: released after a tenth of the Newton budget")
    for ns, limit, direct in (("100", 400, False), ("10", 100, True), ("5", 60, True)):
        out = ngspice(op_deck("ns_far", OPAMP_CLAMP + f"\n.nodeset v(out)={ns}", "v(out)"))
        v, n = scalars(out).get("v(out)"), iters(out)
        check(f".nodeset v(out)={ns} on a 3 V diode clamp: v(out)=1, <= {limit} iterations",
              near(v, 0.9999989, 1e-5) and n is not None and n <= limit, f"v(out)={v} iterations={n} aids={aids(out)}")
        check(f".nodeset v(out)={ns}: no singular-matrix report, no NaN",
              "singular" not in out and "nan" not in out.lower().replace("nanosecond", ""), "")
        if direct:
            check(f".nodeset v(out)={ns}: plain Newton, no aid", not aids(out), f"aids={aids(out)}")
    out = ngspice(op_deck("ns_ff", FLIPFLOP, "v(c1) v(c2)"))
    s, n = scalars(out), iters(out)
    check("BJT flip-flop, .nodeset selects the c1-high state: v(c1)=4.6148, <= 15 iterations, no aid",
          near(s.get("v(c1)"), 4.614844, 1e-3) and n is not None and n <= 15 and not aids(out),
          f"v(c1)={s.get('v(c1)')} v(c2)={s.get('v(c2)')} iterations={n}")

    # ---- R4: a loop of ideal voltage-defined branches -----------------------------
    print("\n[R4] last-resort damped Newton")
    out = ngspice(op_deck("ring", RING, "v(q) v(qb)"))
    s = scalars(out)
    check("tanh buffer+inverter ring: the point is found", near(s.get("v(q)"), 2.5, 0.01) and near(s.get("v(qb)"), 2.5, 0.01),
          f"v(q)={s.get('v(q)')} v(qb)={s.get('v(qb)')}")
    check("tanh ring: reached through the damped Newton rung, announced",
          "Starting damped Newton (line search)" in out and "could not be simulated" not in out,
          f"aids={aids(out)}")
    out = ngspice(op_deck("ring_ls", RING, "v(q) v(qb)", ".option linesearch\n"))
    s = scalars(out)
    check("tanh ring with .option linesearch: same point, rung not repeated",
          near(s.get("v(q)"), 2.5, 0.01) and "Starting damped Newton" not in out and not aids(out),
          f"v(q)={s.get('v(q)')} aids={aids(out)}")
    out = ngspice(op_deck("latch", LATCH, "v(q) v(qb)"))
    s, n = scalars(out), iters(out)
    check("tanh bistable pair, no nodeset: still the plain 3-iteration (0, 0) point",
          near(s.get("v(q)"), 0.0, 1e-9) and near(s.get("v(qb)"), 0.0, 1e-9) and n is not None and n <= 4 and not aids(out),
          f"v(q)={s.get('v(q)')} iterations={n}")

    for f in ("_o.cir",):
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
