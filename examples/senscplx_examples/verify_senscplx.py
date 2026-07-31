#!/usr/bin/env python3
"""Enhancement-386: the sensitivity queries returned the PREVIOUS query's value.

    print @r1[resistance]   ->  1.00000000000000e+03
    print @r1[sens_cplx]    ->  1.00000000000000e+03      <-- echoed, not computed
    print @r1[i]            ->  5.00000000000000e-04
    print @c1[sens_cplx]    ->  4.99999616295099e-04      <-- echoed again

Every `*_QUEST_SENS_*` case in every device's ask handler had this shape:

    case RES_QUEST_SENS_CPLX:
        if (ckt->CKTsenInfo) {
            value->cValue.real = ...;
            value->cValue.imag = ...;
        }
        return(OK);

`ckt->CKTsenInfo` is only set by the SENS2 analysis, which is not compiled in, so
on any ordinary run the handler wrote NOTHING and still returned OK. The caller
then read whatever was already in its IFvalue.

In the frontend that IFvalue is a `static` reused by every query (spiceif.c,
doask), so the reading was the previous query's bytes -- which is why this first
showed up as denormal garbage (2.12736e-314) that changed between runs: a
`double` read of a stale `cValue` whose imaginary half had never been written.
Interleaving queries makes it much plainer: the answer is simply the last thing
you asked for.

TWO OTHER CALLERS pass an uninitialised STACK IFvalue -- `dctrcurv.c`, which then
saves the result as a parameter's nominal to RESTORE later, and `cktsens.c`'s
sens_getp, which feeds sgen the value it will write back. Both are latent today
because they only ask for parameters whose handlers do write, but they are why
this had to be fixed in the handlers rather than in any single caller. `doask`
was hardened as well, so the channel itself is deterministic for any handler that
ever fails to write.

Zero is the answer the surrounding code already chose: the MAG and PH cases
explicitly `value->rValue = 0` when the response magnitude is zero.

SCOPE: 60 cases across 10 device types (res, cap, ind, mutual, dio, bjt, vccs,
vcvs, cccs, ccvs) x the six queries sens_dc / sens_real / sens_imag / sens_mag /
sens_ph / sens_cplx. A sweep over every parameter of seven device types found 44
stale readings before the fix and none after -- the two that still match the
probe value are `@r1[r]` and `@r1[ac]`, genuine aliases of `resistance` that
really are 1000.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0

NET = """senscplx
V1 in 0 dc 1 ac 1
R1 in mid 1k
C1 mid 0 1n
L1 mid n2 1m
D1 n2 out dm
R2 out 0 1k
Q1 out mid 0 qm
G1 0 nc mid 0 1e-3
E1 ne 0 mid 0 2
R3 nc 0 1k
R4 ne 0 1k
.model dm d(is=1e-14)
.model qm npn(bf=100)
"""
SENSQ = ["sens_dc", "sens_real", "sens_imag", "sens_mag", "sens_ph", "sens_cplx"]
DEVS = ["r1", "c1", "l1", "d1", "q1", "g1", "e1"]


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(ctl, tag, timeout=300):
    p = os.path.join(HERE, "_sc_%s.cir" % tag)
    with open(p, "w") as f:
        f.write(NET + ".control\noption noacct\nset numdgt=14\n" + ctl + "\n.endc\n.end\n")
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout, errors="replace")
        return r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        return "__TIMEOUT__"


def readings(out):
    return re.findall(r"^@(\w+)\[(\w+)\]\s*=\s*(\S+)", out, re.M)


def main():
    # ---- [1] the echo: a sens query right after a known value ---------------
    # 1000 is R1's resistance; if a sens query returns it, the handler wrote
    # nothing and the caller read the previous answer.
    body = []
    for d in DEVS:
        for q in SENSQ:
            body.append("print @r1[resistance]")
            body.append("print @%s[%s]" % (d, q))
    out = run("op\n" + "\n".join(body), "echo")
    vals = readings(out)
    echoed = []
    for i in range(0, len(vals) - 1, 2):
        probe, target = vals[i], vals[i + 1]
        if probe[2] == target[2] and (target[0], target[1]) != ("r1", "resistance"):
            echoed.append("@%s[%s]" % (target[0], target[1]))
    check("no sensitivity query echoes the preceding query's value",
          not echoed, "%d echoed: %s" % (len(echoed), " ".join(echoed[:6])) if echoed else
          "%d queries checked" % (len(vals) // 2))

    # ---- [2] every sens query answers 0 when there is no sensitivity data ---
    bad = []
    for d in DEVS:
        out = run("op\n" + "\n".join("print @%s[%s]" % (d, q) for q in SENSQ), "z" + d)
        for inst, kw, v in readings(out):
            try:
                if float(v) != 0.0:
                    bad.append("@%s[%s]=%s" % (inst, kw, v))
            except ValueError:
                bad.append("@%s[%s]=%s" % (inst, kw, v))
    check("every sensitivity query answers 0 without a sensitivity run",
          not bad, " ".join(bad[:6]) if bad else "%d queries" % (len(DEVS) * len(SENSQ)))

    # ---- [3] and it is DETERMINISTIC -- the original symptom was a value
    #          that changed between runs and between calls in one session
    out = run("op\nprint @r1[sens_cplx]\nprint @r1[i]\nprint @r1[sens_cplx]\n"
              "print @r1[p]\nprint @r1[sens_cplx]", "det")
    seen = [v for inst, kw, v in readings(out) if kw == "sens_cplx"]
    check("repeated sens_cplx reads agree within one session",
          len(seen) == 3 and len(set(seen)) == 1, " ".join(seen))

    a = run("op\nprint @d1[sens_mag]", "r1a")
    b = run("op\nprint @d1[sens_mag]", "r1b")
    va, vb = readings(a), readings(b)
    check("sens_mag agrees across two separate runs",
          va and vb and va[0][2] == vb[0][2],
          "%s vs %s" % (va[0][2] if va else "?", vb[0][2] if vb else "?"))

    # ======================= ACCEPT HALF ====================================
    # Real parameters must still report their real values -- the fix pre-zeroes
    # the output, so a handler that forgot to write afterwards would read 0 here.
    # Key by (instance, parameter): `gain` exists on BOTH g1 and e1 with
    # different values, and a name-keyed dict silently kept only the last one.
    out = run("op\nprint @r1[resistance] @c1[capacitance] @l1[inductance] "
              "@g1[gain] @e1[gain]", "acc1")
    got = {(i, kw): float(v) for i, kw, v in readings(out)}
    want = {("r1", "resistance"): 1000.0, ("c1", "capacitance"): 1e-9,
            ("l1", "inductance"): 1e-3, ("g1", "gain"): 1e-3, ("e1", "gain"): 2.0}
    check("ordinary parameters still report their real values",
          all(k in got and abs(got[k] - v) <= 1e-12 * abs(v) for k, v in want.items()),
          " ".join("@%s[%s]=%s" % (k[0], k[1], got.get(k)) for k in sorted(want)))

    # Operating-point readbacks must still work. The values are asserted to be
    # SELF-CONSISTENT rather than hard-coded: p = i^2 * R for a resistor holds
    # whatever the rest of the deck does, whereas a literal copied from a simpler
    # circuit just bakes in the wrong number.
    out = run("op\nprint @r1[i] @r1[p] @r1[resistance]", "acc2")
    got = {kw: float(v) for _, kw, v in readings(out)}
    i, pw, rr = got.get("i"), got.get("p"), got.get("resistance")
    check("operating-point readbacks still work and are self-consistent (p = i^2 R)",
          None not in (i, pw, rr) and i != 0
          and abs(pw - i * i * rr) <= 1e-9 * abs(pw),
          "i=%s p=%s i^2R=%s" % (i, pw, None if None in (i, rr) else i * i * rr))

    # `sens` itself must still compute the right numbers -- this touches the
    # ask path the sensitivity analysis reads through
    p = os.path.join(HERE, "_sc_sens.cir")
    open(p, "w").write("sens\nV1 in 0 dc 1\nR1 in out 1k\nR2 out 0 1k\n"
                       ".control\noption noacct\nset numdgt=12\n"
                       "sens v(out)\nprint r1 v1\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=300, errors="replace")
    o = r.stdout + r.stderr
    r1 = re.search(r"^r1\s*=\s*(\S+)", o, re.M)
    v1 = re.search(r"^v1\s*=\s*(\S+)", o, re.M)
    check("sens still computes the right numbers (dv/dR1=-2.5e-4, dv/dV1=0.5)",
          r1 and v1 and abs(float(r1.group(1)) + 2.5e-4) < 1e-8
          and abs(float(v1.group(1)) - 0.5) < 1e-8,
          "r1=%s v1=%s" % (r1.group(1) if r1 else "?", v1.group(1) if v1 else "?"))

    # `show` walks every parameter of every device through the same path
    out = run("op\nshow all : all", "acc3")
    check("`show all : all` still lists devices",
          "Resistor" in out and "Capacitor" in out and "Diode" in out,
          "%d lines" % len(out.splitlines()))

    for j in os.listdir(HERE):
        if j.startswith("_sc_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
