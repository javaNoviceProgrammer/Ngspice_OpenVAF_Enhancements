#!/usr/bin/env python3
"""Enhancement-385: two commands left the user's circuit changed behind them.

Found by a STATE-RESTORATION AUDIT: for every (instance, parameter) pair in a
deck, the value after running a command must equal the value before. That oracle
covers a class rather than instances, and the class already had four members --
E-380 (.dc inherited integration coefficients), E-381 (stb zeroed its probes),
E-382 (loadpull left the tuner moved), E-384 (sens flipped every source to PORT).

  [A] `sens ... ac` KILLED VCCS AND CCCS SOURCES.

          @g1[gain] = 1e-3   ->  sens v(out) ac dec 3 1e3 1e6  ->  0
          a following .ac:   vm(out) = 0.0        (the answer is 1.0)

      Not a bug in sens. VCCSparam folds the multiplier into the coefficient
      when `gain` is written:

          case VCCS_TRANS:  here->VCCScoeff = value->rValue;
                            if (here->VCCSmGiven)
                                here->VCCScoeff *= here->VCCSmValue;

      and VCCSmValue was never defaulted to 1 -- `res` does exactly that in
      ressetup.c (`if(!here->RESmGiven) here->RESm = 1.0;`), VCCS and CCCS did
      not. `sens` perturbs every settable real parameter, so it wrote `m` (which
      set VCCSmGiven), read it back as 0, wrote that 0 back as the "restore", and
      the next write of `gain` multiplied by zero.

      That explains the exact scope: VCCS and CCCS have a settable `m`, VCVS and
      CCVS do not, and only the first two were affected. It also explains why one
      frequency point was harmless and three were fatal -- the perturbation loop
      runs per frequency, and `m` has to be written before `gain` is written
      again.

  [B] `sweep` NEVER PUT AN `alter`/`altermod` KNOB BACK.

          @r1[resistance] = 2000  ->  sweep @r1[resistance] 1800 2200 3  ->  2199
          a following op:  v(out) = 0.5770        (the answer is 0.6)

      [E-350](../../enhancements_doc/Enhancement-350.md) captured and restored the
      nominal of each swept `.param`; the `alter`/`altermod` path -- device and
      model parameters -- was never covered, so the knob simply stayed wherever
      the last point left it. General across parameter types: resistance,
      capacitance and a source's `dc` all stayed moved.

CHECK [13] SHIPS THE AUDIT ITSELF, so the class stays covered rather than these
two instances. Two things make it trustworthy and both were learned the hard way:

  * The BEFORE snapshot must be BOUNDED by the AFTER marker. Without that bound
    it swallowed the AFTER block and -- building a dict -- the later values
    overwrote the earlier ones, so before == after and EVERY command looked
    clean. Nothing in a green run would have shown it.
  * A parameter is a computed OUTPUT if it moves merely because the operating
    point moved, so the control is a UNION of benign analyses, subtracted per
    (instance, parameter) pair. `op` vs `op` is not enough: the same analysis
    reproduces the same operating point, so nothing appears to move.

  LIMITATION, stated rather than hidden: operating-point dependent pairs are
  subtracted, so a command that corrupts one of THOSE is masked. The inputs that
  matter -- resistance, dc, gain, capacitance -- are not among them.
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


def run(net, ctl, tag, timeout=600):
    p = os.path.join(HERE, "_st_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(net + ".control\noption noacct\nset numdgt=12\n" + ctl + "\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout, errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "__TIMEOUT__"


def val(out, name):
    m = re.search(r"^%s\s*=\s*([-+0-9.eE]+)" % re.escape(name), out, re.M)
    return float(m.group(1)) if m else None


CS = """cs
V1 in 0 dc 1 ac 1
R1 in mid 1k
G1 0 o1 mid 0 1e-3
R2 o1 0 1k
E1 o2 0 mid 0 2
R3 o2 0 1k
F1 0 o3 V1 3
R4 o3 0 1k
H1 o4 0 V1 4
R5 o4 0 1k
"""
SW = """sw
V1 in 0 dc 1
R1 in out 2k
C1 out 0 1n
R2 out 0 3k
"""


def main():
    # ---- [A] sens ac must not kill controlled sources -----------------------
    out = run(CS, "op\nsens v(o1) ac dec 3 1e3 1e6\n"
                  "print @g1[gain] @e1[gain] @f1[gain] @h1[gain]", "a1")
    for inst, want in (("g1", 1e-3), ("f1", 3.0), ("e1", 2.0), ("h1", 4.0)):
        got = val(out, "@%s[gain]" % inst)
        check("sens ac leaves @%s[gain] at %g" % (inst, want),
              got is not None and abs(got - want) <= 1e-12 * abs(want),
              "got %s" % got)

    # the consequence: a following .ac must give the real answer, not zeros
    ref = run(CS, "ac lin 1 1e4 1e4\nprint vm(o1)", "a2")
    aft = run(CS, "sens v(o1) ac dec 3 1e3 1e6\nac lin 1 1e4 1e4\nprint vm(o1)", "a3")
    a, b = val(ref, "vm(o1)"), val(aft, "vm(o1)")
    check("an .ac after sens ac matches the same .ac run alone",
          a is not None and b is not None and abs(a - b) <= 1e-9 * max(abs(a), 1e-30),
          "alone=%s after=%s" % (a, b))

    # ---- [B] sweep must put an alter/altermod knob back ---------------------
    for knob, spec, want in (("@r1[resistance]", "1800 2200 3", 2000.0),
                             ("@c1[capacitance]", "0.5n 2n 3", 1e-9),
                             ("@v1[dc]", "0.5 1.5 3", 1.0)):
        out = run(SW, "op\nsweep %s %s -analysis op\nprint %s" % (knob, spec, knob), "b" + knob[1:3])
        got = val(out, knob)
        check("sweep restores %s" % knob,
              got is not None and abs(got - want) <= 1e-9 * abs(want),
              "got %s (nominal %g)" % (got, want))

    ref = run(SW, "op\nprint v(out)", "b1")
    aft = run(SW, "sweep @r1[resistance] 1800 2200 3 -analysis op\nop\nprint v(out)", "b2")
    a, b = val(ref, "v(out)"), val(aft, "v(out)")
    check("an op after a sweep matches the same op run alone",
          a is not None and b is not None and abs(a - b) <= 1e-9 * abs(a),
          "alone=%s after=%s" % (a, b))

    # ======================= ACCEPT HALF ====================================
    # [A]'s fix touches the multiplier that scales every VCCS/CCCS, so an
    # explicit `m` is exactly what a careless fix would break.
    for dev, card, want_v, want_g in (
            ("VCCS", "G1 0 out mid 0 1e-3 m=2\nR2 out 0 1k", 2.0, 2e-3),
            ("VCCS", "G1 0 out mid 0 1e-3\nR2 out 0 1k", 1.0, 1e-3)):
        out = run("m\nV1 in 0 dc 1\nR1 in mid 1k\n" + card + "\n",
                  "op\nprint v(out) @g1[gain]", "acc" + str(want_v))
        check("%s with `%s` still gives v(out)=%g, gain=%g"
              % (dev, card.split("\n")[0].split(" ", 5)[-1], want_v, want_g),
              val(out, "v(out)") is not None
              and abs(val(out, "v(out)") - want_v) < 1e-9
              and abs(val(out, "@g1[gain]") - want_g) < 1e-15,
              "v=%s gain=%s" % (val(out, "v(out)"), val(out, "@g1[gain]")))

    out = run("f\nV1 in 0 dc 1\nR1 in 0 1k\nF1 0 out V1 3 m=2\nR2 out 0 1k\n",
              "op\nprint @f1[gain]", "accf")
    check("CCCS with m=2 still has gain 6", abs(val(out, "@f1[gain]") - 6.0) < 1e-12,
          "gain=%s" % val(out, "@f1[gain]"))

    # sens's own answer, against the analytic derivative of a divider
    out = run("s\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n",
              "sens v(out)\nprint r1 v1", "accs")
    check("sens still computes the right numbers (dv/dR1=-2.5e-4, dv/dV1=0.5)",
          val(out, "r1") is not None and abs(val(out, "r1") + 2.5e-4) < 1e-8
          and abs(val(out, "v1") - 0.5) < 1e-8,
          "r1=%s v1=%s" % (val(out, "r1"), val(out, "v1")))

    # sweep's own answer must not move, and E-350's `.param` restore must hold
    # Read the DEVICE the .param feeds, not the symbol: `print rl` does not
    # resolve a numparam after the deck is flattened, and a None there would look
    # like a restoration failure when it is only an unreadable probe.
    # NOTE the ordering: the FIRST line of a deck is the TITLE and is ignored, so
    # `.param` must come after it. Putting it first made the param vanish and the
    # probe return None, which reads exactly like a restoration failure.
    out = run("sw2 param restore\n.param rl=3k\nV1 in 0 dc 1\nR1 in out 2k\nR2 out 0 {rl}\n",
              "sweep rl lin 3 1k 5k -analysis op -output v(out)\n"
              "print @r2[resistance]", "acc350")
    got = val(out, "@r2[resistance]")
    check("E-350: a swept `.param` is still restored to its nominal",
          got is not None and abs(got - 3000.0) < 1e-6, "@r2[resistance]=%s" % got)

    # ---- [13] the audit itself, so the CLASS stays covered ------------------
    PAIRS = [("g1", "gain"), ("f1", "gain"), ("e1", "gain"), ("h1", "gain"),
             ("r1", "resistance"), ("r2", "resistance"), ("v1", "dc"),
             ("v1", "acmag"), ("v1", "function"), ("g1", "m"), ("f1", "m")]
    snap = "\n".join("print @%s[%s]" % p for p in PAIRS)

    def pairs_of(out, start, end=None):
        i = out.find(start)
        if i < 0:
            return {}
        seg = out[i:]
        if end and seg.find(end) > 0:
            seg = seg[:seg.find(end)]
        return {(m.group(1), m.group(2)): m.group(3)
                for m in re.finditer(r"^@(\w+)\[(\w+)\]\s*=\s*(\S+)", seg, re.M)}

    def audit(cmd, tag):
        o = run(CS, "op\necho @@B\n" + snap + "\n" + cmd + "\necho @@A\n" + snap, tag)
        b, a = pairs_of(o, "@@B", "@@A"), pairs_of(o, "@@A")
        moved = []
        for k in b:
            x, y = b[k], a.get(k)
            try:
                if float(x) == float(y):
                    continue
            except (TypeError, ValueError):
                pass
            if x != y:
                moved.append("@%s[%s] %s->%s" % (k[0], k[1], x, y))
        return moved

    # the harness must be able to SEE a change, or a clean report means nothing
    canary = audit("alter @r1[resistance]=9k", "canary")
    check("audit canary: a deliberate alter IS detected",
          any("r1" in m for m in canary), "; ".join(canary) or "detected nothing")

    for cmd, tag in (("sens v(o1)", "au1"), ("sens v(o1) ac dec 3 1e3 1e6", "au2"),
                     ("tran 1u 20u", "au3"), ("ac dec 3 1e3 1e6", "au4"),
                     ("sweep @r1[resistance] 900 1100 3 -analysis op", "au5")):
        moved = audit(cmd, tag)
        check("audit: `%s` restores every declared input" % cmd,
              not moved, "; ".join(moved[:4]) if moved else "11 pairs stable")

    for j in os.listdir(HERE):
        if j.startswith("_st_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
