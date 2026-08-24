#!/usr/bin/env python3
"""Enhancement-478: the value a guard checks is the value that gets used.

Five defects from bug-hunt round 46. In each one a check was performed and then
something *else* was used -- a different parser, a different end of the range, a
different lookup, or a different loop's state.

  1  A COUNT was validated with a float parser and consumed with `atoi()`, which
     stops at the first non-digit. `sweep lin 2e2` ran 2 points, `montecarlo 2e2`
     drew 2 samples and printed a yield from them, and `sweep lin 1e6` ran ONE
     point while the same number written `1000000` was correctly refused as too
     many. The float the validator computed was discarded.
  2  `spec` checked its step against the span but never against zero, so a
     negative step produced a negative point count, a negative allocation and a
     NULL dereference: `spec 100 10k -1e9 v(b)` SEGFAULTED.
  3  Indexing a `@dev[param]` waveform returned the device's LIVE value instead
     of the element. The literal-index probe built the name `@c1[i][50]` and
     asked vec_get() for it -- and vec_get answers an '@' name from the DEVICE,
     not the plot, so every index gave the same number.
  4  `fourier` refused a fundamental whose wavelength was longer than the data
     but had no test at the other end, so one far above the sample rate printed
     a full report of `nan` with no diagnostic.
  5  A loop command run as another's `-analysis` overwrote the single set of
     progress-bar statics, and the inner `end()` tore the bar down for both.

THE UNIT UNDER TEST IS THE AGREEMENT, not the symptom: [1]-[6] check that two
spellings of the SAME number are treated the same, [12] that both ends of the
same range are, and [16] that the indexed vector is the one that was named.

WHAT IS DELIBERATELY NOT CHANGED, and pinned here so a later round does not
"fix" it:
  * `.four 1e30` still RUNS. Enhancement-445 fixed the overflow hole here and
    its suite pins that a large but FINITE fundamental is accepted; this adds a
    warning so the nan is explained, and does not refuse. [13]/[14].
  * `psd 0` still clamps to 1 -- but it ANNOUNCES it ("Number of averaged data
    points: 1"), which is the whole difference. Round 46 first reported it as a
    silent clamp; the report was wrong because the check filtered for
    error/warning keywords and this is a plain informational line. [15] pins it.
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


def run(body, ctl, tag, timeout=300):
    if not body.endswith("\n"):
        body += "\n"
    deck = f"guardmatch\n{body}.control\noption noacct\n{ctl}\n.endc\n.end\n"
    p = os.path.join(HERE, f"_gm_{tag}.cir")
    with open(p, "w") as f:
        f.write(deck)
    try:
        r = subprocess.run([NGSPICE, "-b", os.path.basename(p)], cwd=HERE,
                           capture_output=True, text=True, timeout=timeout,
                           errors="replace")
        rc, out = r.returncode, r.stdout + r.stderr
    except subprocess.TimeoutExpired:
        rc, out = "TIMEOUT", ""
    finally:
        try:
            os.remove(p)
        except OSError:
            pass
    return rc, out


DIV = "V1 a 0 dc 1\nR1 a b 1k\nR2 b 0 1k\n"
MC = ".param rv=agauss(1k,100,1)\nV1 a 0 dc 1\nR1 a b {rv}\nR2 b 0 1k\n"
OSC = "V1 a 0 sin(0 1 1k)\nR1 a b 1k\nRX b 0 1k\n"


def npoints(out):
    m = re.search(r"over (\d+) point", out)
    return int(m.group(1)) if m else None


print("=== Enhancement-478: the value a guard checks is the value that gets used ===")

# ---------------------------------------------------------------------------
print("\n[1-8] a count is read with ONE parser, not validated with one and used with another")
# ---------------------------------------------------------------------------
_, a = run(DIV, "sweep @r1[resistance] lin 200 1k 2k -output v(b)", "c200")
_, b = run(DIV, "sweep @r1[resistance] lin 2e2 1k 2k -output v(b)", "c2e2")
check("[1] `lin 2e2` means 200 points, exactly like `lin 200`",
      npoints(a) == 200 and npoints(b) == 200, f"200->{npoints(a)}  2e2->{npoints(b)}")

_, a = run(DIV, "sweep @r1[resistance] lin 1000000 1k 2k -output v(b)", "cbig")
_, b = run(DIV, "sweep @r1[resistance] lin 1e6 1k 2k -output v(b)", "c1e6")
check("[2] `lin 1e6` trips the SAME cap as `lin 1000000` (it used to run 1 point)",
      "too many points" in a and "too many points" in b,
      f"1000000={'refused' if 'too many' in a else npoints(a)}  "
      f"1e6={'refused' if 'too many' in b else npoints(b)}")

for n, tag in (("0", "z"), ("-5", "neg")):
    _, o = run(DIV, f"sweep @r1[resistance] lin {n} 1k 2k -output v(b)", "cl" + tag)
    check(f"[3{tag}] `lin {n}` is refused, not silently rewritten to 1 point",
          "at least 1 point" in o and npoints(o) is None, o.strip().splitlines()[-1][:48])

_, o = run(DIV, "sweep @r1[resistance] lin 2.5 1k 2k -output v(b)", "cfrac")
check("[4] a fractional count is named", "whole number of points" in o)

_, o = run(DIV, "sweep @r1[resistance] dec 0 1k 100k -output v(b)", "cdec")
check("[5] `dec 0` is refused too (it used to change the SPACING silently)",
      "at least 1 point" in o)

_, o = run(DIV, "sweep @r1[resistance] lin 3 1k 3k "
                "-vs @r2[resistance] lin 0 1k 2k -output v(b)", "cvs")
check("[6] a `-vs` knob is held to the same rule (it silently collapsed a dimension)",
      "at least 1 point" in o)

_, o = run(MC, "montecarlo 2e2 -analysis op -spec v(b) -min 0 -max 1", "cmc")
m = re.search(r"(\d+) random samples", o)
check("[7] `montecarlo 2e2` draws 200 samples, not 2",
      m and m.group(1) == "200", f"drew {m.group(1) if m else '-'}")

_, o = run(MC, "highsigma 2e2 -analysis op -metric v(b) -max 1", "chs")
m = re.search(r"(\d+) samples", o)
check("[8] `highsigma 2e2` draws 200 samples, not 2",
      m and m.group(1) == "200", f"drew {m.group(1) if m else '-'}")

# ---------------------------------------------------------------------------
print("\n[9-12] `spec`: the step is checked at BOTH ends (a negative one segfaulted)")
# ---------------------------------------------------------------------------
for step, tag in (("-1e9", "a"), ("-1e4", "b"), ("-100", "c")):
    rc, o = run(OSC, f"tran 1u 10m\nspec 100 10k {step} v(b)\necho ==OK==", "sp" + tag)
    crashed = rc == "TIMEOUT" or (isinstance(rc, int) and (rc < 0 or rc >= 128))
    check(f"[9{tag}] `spec` step {step} is refused, and does not crash",
          not crashed and "bad step freq" in o and "==OK==" in o,
          f"rc={rc}")

rc, o = run(OSC, "tran 1u 10m\nspec 100 10k 100 v(b)\necho ==OK==", "spok")
check("[12] a POSITIVE step still works -- only the missing end was added",
      "==OK==" in o and "bad step freq" not in o)

# ---------------------------------------------------------------------------
print("\n[13-15] pinned decisions")
# ---------------------------------------------------------------------------
_, o = run(OSC, "tran 1u 10m\nfourier 1e30 v(b)", "f30")
check("[13] DECISION: a large FINITE fundamental still RUNS (Enhancement-445)",
      "Fourier analysis for" in o)
check("[14] ...but the meaningless result is now explained",
      "not measurable" in o, [l.strip()[:60] for l in o.splitlines()
                              if "not measurable" in l][:1])

_, o = run(OSC, "tran 1u 10m\nlinearize v(b)\npsd 0 v(b)", "psd0")
check("[15] DECISION: `psd 0` still clamps to 1 -- because it SAYS so",
      "averaged data points:  1" in o,
      "round 46 called this silent; the check was filtering for error keywords")

# ---------------------------------------------------------------------------
print("\n[16-18] the indexed vector is the one that was named")
# ---------------------------------------------------------------------------
PULSE = "V1 a 0 pulse(0 1 0 1u 1u 10u 20u)\nR1 a b 1k\nC1 b 0 1n\n"
_, o = run(PULSE, "save v(b) @c1[i]\ntran 100n 20u\n"
                  "print @c1[i][50] @c1[i][218]\nlet z=@c1[i]\nprint z[50] z[218]", "idx")


def val(out, name):
    m = re.search(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out)
    return float(m.group(1)) if m else None


d50, d218 = val(o, "@c1[i][50]"), val(o, "@c1[i][218]")
z50, z218 = val(o, "z[50]"), val(o, "z[218]")
check("[16] two different indices give two different samples (they were equal)",
      d50 is not None and d218 is not None and d50 != d218,
      f"[50]={d50} [218]={d218}")
check("[17] ...and they match the same vector reached through a plain name",
      d50 == z50 and d218 == z218, f"z[50]={z50} z[218]={z218}")

_, o = run(PULSE, "save v(b) @c1[i]\ntran 100n 20u\n"
                  "print length(@c1[i])\nlet m=maximum(@c1[i])\nprint m", "whole")
check("[18] taking the vector WHOLE was always right and still is",
      val(o, "length(@c1[i])") == 219.0 and val(o, "m") is not None,
      f"length={val(o, 'length(@c1[i])')}")

# ---------------------------------------------------------------------------
print("\n[19-20] a nested loop command does not steal the outer's progress line")
# ---------------------------------------------------------------------------
AN = "montecarlo 6 -analysis op -spec v(b) -min 0 -max 1"
_, o = run(MC + "R3 b 0 1meg\n",
           f'set loopbar\nsweep @r3[resistance] lin 3 1meg 3meg -analysis "{AN}" '
           f'-output v(b)\nprint all', "nest")
frames = [l.strip() for l in re.split(r"[\r\n]", o)
          if re.match(r"\s*\w+: (point|sample|iteration)", l)]
labels = sorted({f.split(":")[0] for f in frames})
check("[19] only the OUTER loop draws (the inner used to take the line over)",
      labels == ["sweep"], f"labels={labels}")
check("[20] ...and the last frame is the OUTER loop's real completion",
      frames and re.search(r"point\s+3/3\b.*100%", frames[-1]) is not None,
      frames[-1][:46] if frames else "-")

print(f"\n=== {passed}/{checks} checks passed ===")
sys.exit(0 if passed == checks else 1)
