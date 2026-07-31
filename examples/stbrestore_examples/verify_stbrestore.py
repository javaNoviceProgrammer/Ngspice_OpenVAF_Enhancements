#!/usr/bin/env python3
"""Enhancement-381: `stb` handed its probe sources back zeroed.

`stb` measures loop gain by injecting through two EXISTING sources: it drives one
with `ac = 1` while holding the other at `ac = 0`, then swaps them. When finished
it "restored the probes to quiescent" -- by setting BOTH to zero:

    /* restore the probes to quiescent */
    alter <vname> ac = 0;
    alter <iname> ac = 0;

Zero is only "quiescent" if that is where the probe started. A source carrying
`ac 1` for the user's own following `.ac` had that value destroyed, and the `.ac`
then came back with EVERY node exactly 0.00000000e+00 -- no warning, no error,
just a dead result:

    @v1[acmag]  before stb = 1.0        ac before stb:  vm(mid) = 0.3333333333
    @v1[acmag]  after  stb = 0.0        ac after  stb:  vm(mid) = 0.0000000000

The fix reads each probe's `acmag` before the first injection and writes those
exact values back afterwards. Only the magnitude is saved, because the injection
writes `ac = N`, which sets `acmag` and leaves `acphase` untouched -- verified,
and asserted below so the assumption cannot rot.

FOUND BY cross-analysis state fuzzing with a numeric oracle
(`result(B after A) == result(B alone)`), the same instrument that found
Enhancement-380. This was the one genuine survivor after E-380 landed; the other
three residual pairs were `-> hb` deviations of 1e-17..1e-23 on near-zero
harmonics, where a "30% relative" figure is the classic no-absolute-floor trap.
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE  # noqa: E402

checks = passed = 0

# A 3-pole op-amp loop -- the same shape `examples/stb_examples` uses, so `stb`
# has a genuine loop to break. The VOLTAGE PROBE deliberately carries the AC drive
# (`Vstb ... ac 1`): that is the case the defect destroys, and it is exactly what
# the fuzzer hit, where the deck's own source was named as the probe. A probe
# sitting at the more usual `ac 0` is covered by the accept half below.
NET = """stbrestore
Vin  inp 0   dc 0 ac 0
G1   0   n1  inp inn 1
R1   n1  0   1e5
C1   n1  0   1.59155e-9
E2   n2  0   n1 0 1
R2   n2  n3  1k
C2   n3  0   1.59155e-10
E3   n4  0   n3 0 1
R3   n4  n5  1k
C3   n5  0   1.59155e-11
E4   out 0   n5 0 1000
Rf   out mid 9k
Rg   mid 0   1k
Vstb mid inn dc 0 ac %s %s
Istb 0   inn dc 0 ac 0
"""


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def run(body, acmag="1", acphase="", tag="t"):
    p = os.path.join(HERE, "_sr_%s.cir" % tag)
    open(p, "w").write((NET % (acmag, acphase)) +
                       ".control\noption noacct\nset numdgt=12\n" + body +
                       "\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                       capture_output=True, text=True, timeout=900, errors="replace")
    return r.stdout + r.stderr


def scalar(out, name):
    m = re.search(r"^%s\s*=\s*([-+0-9.eE]+)" % re.escape(name), out, re.M)
    return float(m.group(1)) if m else None


def col(out):
    return [float(m.group(2)) for m in
            re.finditer(r"^\s*\d+\s+([-+0-9.eE]+)\s+([-+0-9.eE]+)\s*$", out, re.M)]


STB = "stb Vstb Istb dec 10 1 1meg"


def main():
    # ---- 1. the defect ------------------------------------------------------
    ref = col(run("ac dec 2 1e3 1e4\nprint vm(out)", tag="ref"))
    after = col(run("%s\nac dec 2 1e3 1e4\nprint vm(out)" % STB, tag="after"))
    check("an .ac after stb still produces a non-zero response",
          len(after) == len(ref) and len(after) > 0 and all(v != 0.0 for v in after),
          "%s" % (["%.6g" % v for v in after[:3]] if after else "no rows"))
    check("an .ac after stb matches the same .ac run alone",
          len(after) == len(ref) and len(ref) > 0
          and all(abs(a - b) <= 1e-9 * max(abs(a), 1.0) for a, b in zip(ref, after)),
          "ref=%s after=%s" % (["%.6g" % v for v in ref[:2]],
                               ["%.6g" % v for v in after[:2]]) if ref else "none")

    # the probe's own parameter must come back as it went in
    out = run("print @vstb[acmag]\n%s\nprint @vstb[acmag]" % STB, tag="mag")
    mags = re.findall(r"@vstb\[acmag\]\s*=\s*([-+0-9.eE]+)", out)
    check("the probe's acmag is restored, not zeroed",
          len(mags) == 2 and float(mags[0]) == float(mags[1]) and float(mags[0]) != 0,
          "before=%s after=%s" % tuple(mags) if len(mags) == 2 else "not reported")

    # the phase must survive too -- the injection only writes acmag, and this
    # asserts that assumption rather than trusting it
    out = run("print @vstb[acphase]\n%s\nprint @vstb[acphase]" % STB,
              acmag="1", acphase="45", tag="ph")
    phs = re.findall(r"@vstb\[acphase\]\s*=\s*([-+0-9.eE]+)", out)
    check("the probe's acphase survives stb",
          len(phs) == 2 and abs(float(phs[0]) - float(phs[1])) < 1e-9
          and abs(float(phs[0]) - 45.0) < 1e-9,
          "before=%s after=%s" % tuple(phs) if len(phs) == 2 else "not reported")

    # ---- 2. ACCEPT HALF -----------------------------------------------------
    # a probe that legitimately starts at zero must still come back at zero --
    # restoring "whatever it was" has to include zero
    out = run("print @istb[acmag]\n%s\nprint @istb[acmag]" % STB, tag="zero")
    z = re.findall(r"@istb\[acmag\]\s*=\s*([-+0-9.eE]+)", out)
    check("a probe that started at ac=0 still ends at ac=0",
          len(z) == 2 and float(z[0]) == 0.0 and float(z[1]) == 0.0,
          "before=%s after=%s" % tuple(z) if len(z) == 2 else "not reported")

    # stb's own answer must not move: pin the loop gain it reports
    out = run("%s\nprint mag(loopgain[0]) ph(loopgain[0])" % STB, tag="own")
    mag0, ph0 = scalar(out, "mag(loopgain[0])"), scalar(out, "ph(loopgain[0])")
    check("stb still reports a loop gain", mag0 is not None and ph0 is not None,
          "|T[0]|=%s ph=%s" % (mag0, ph0))

    # running stb twice must give the same answer both times -- before the fix the
    # second run saw probes it had itself zeroed
    out = run("%s\nprint mag(loopgain[0])\n%s\nprint mag(loopgain[0])" % (STB, STB), tag="twice")
    two = re.findall(r"mag\(loopgain\[0\]\)\s*=\s*([-+0-9.eE]+)", out)
    check("stb run twice reports the same loop gain",
          len(two) == 2 and abs(float(two[0]) - float(two[1]))
          <= 1e-9 * max(abs(float(two[0])), 1.0),
          "%s then %s" % tuple(two) if len(two) == 2 else "not reported twice")

    for j in os.listdir(HERE):
        if j.startswith("_sr_"):
            os.remove(os.path.join(HERE, j))
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
