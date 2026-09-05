#!/usr/bin/env python3
"""Enhancement-552: `montecarlo` records without judging -- `-expr`, and a
yield only where a spec has a limit.

The packaged Monte Carlo command answered one question: the yield. A spec was
mandatory, a limit on it was mandatory, and nothing per sample survived the run
-- the analyses ran under the loop commands' plot recycling, so "run the sweep
N times and keep a value from each" had to be hand-written around `reset`.

Now `-expr [name=]<expression>` records the expression after every sample into a
plot of its own, `montecarlo1`, `montecarlo2`, ... (one per invocation, named
in $montecarlo_plot), with `sample` (1..N) as its scale: a scalar per sample
becomes an N-long vector, a waveform per sample (a dc/ac sweep's output, L
points) an N x L two-dimensional vector with the analysis scale copied beside
it, which `plot` draws as a family of N curves. No -spec, no yield; a -spec
without -max/-min is refused with a pointer to -expr; -spec and -expr combine.

Checks (both solvers):
  [1]  a record-only run: no yield, three scalars recorded, $montecarlo_plot
  [2]  the values are the samples' own (r drawn from the deck's .param)
  [3]  a dc sweep's output is an N x L family with the v-sweep scale beside it
  [4]  an ac output is recorded as its magnitude, on the frequency scale
  [5]  two invocations are two plots; the first is still readable
  [6]  `plot`-ready: the family renders through pyplot
  [7]  a -spec without a limit is refused, naming -expr
  [8]  nothing to judge and nothing to record is refused
  [9]  an -expr that resolves to nothing is refused, nothing recorded
  [10] -spec with a limit and -expr together: the yield AND the record
  [11] an expression that never varies is noted
  [12] a waveform whose point count differs between samples is refused, the
       scalar beside it still recorded
  [14] E-557: an -expr named like the plot's own vector (sample, montecarlo_n) is refused
  [13] the old form is unchanged: a limited -spec alone reports the yield and
       creates no plot
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

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="mcrecord_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


def run(deck, ctl, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* mcrecord {tag}\n{deck}\n.control\nset numdgt=10\n{ctl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=300, cwd=WORK, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout + r.stderr


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


def column(out, name):
    """The values of a printed vector column named `name` (print's table form)."""
    lines = out.splitlines()
    for i, ln in enumerate(lines):
        if ln.startswith("Index") and name in ln:
            cols = ln.split()
            j = cols.index(name)
            vals = []
            for row in lines[i + 1:]:
                t = row.split()
                if not t or not re.match(r"^\d+$", t[0]):
                    if vals:
                        break
                    continue
                vals.append(float(t[j]))
            return vals
    return []


DECK = """.param rr = agauss(1000, 100, 3)
V1 in 0 dc 1 ac 1
R1 in out {rr}
R2 out 0 1k"""

print("Enhancement-552: montecarlo records without judging\n")

# ---------------------------------------------------------- [1]-[2] scalars ---
rc, out = run(DECK, """montecarlo 6 -seed 3 -analysis op -expr v(out) -expr vo=v(out) -expr r=@r1[resistance]
echo plot=$montecarlo_plot n=$montecarlo_n
setplot montecarlo1
print expr1 vo r sample""", "scalar")
e1 = column(out, "expr1"); r = column(out, "r"); smp = column(out, "sample")
check("[1] a record-only run: no yield line, 'no yield (no -spec)' said, plot montecarlo1, $montecarlo_plot set",
      rc == 0 and "yield  :" not in out and "no yield (no -spec)" in out
      and "recorded into plot 'montecarlo1'" in out and "plot=montecarlo1 n=6" in out, out.strip()[-300:])
check("[2] three scalars over 6 samples: expr1 == vo, r is the drawn resistance (spread ~100), sample = 1..6",
      len(e1) == 6 and e1 == column(out, "vo") and len(r) == 6
      and 800 < min(r) < 1000 < max(r) < 1200 and smp == [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
      f"expr1={e1[:3]} r={r[:3]} sample={smp}")

# ------------------------------------------------- [3]-[6] waveforms, plots ---
rc, out = run(DECK, """montecarlo 4 -seed 3 -analysis "dc v1 0 1 0.25" -expr vo=v(out)
setplot montecarlo1
display
print length(vo)
montecarlo 3 -seed 3 -analysis "ac dec 2 1 100" -expr vo=v(out) -expr vmax=vecmax(mag(v(out)))
setplot montecarlo2
display
setplot montecarlo1
print vo[0]
set pyplot_terminal=png
set pyplot_backend=Agg
setplot montecarlo1
pyplot fam vo""", "wave")
check("[3] a dc sweep's v(out) is a 4 x 5 family on a copied v-sweep scale",
      "vo                  : voltage, real, 20 long, scale = v-sweep, dims = [4,5]" in out
      and "v-sweep             : voltage, real, 5 long" in out and val(out, "length(vo)") == 20,
      out.strip()[-300:])
check("[4] an ac v(out) is recorded as its magnitude, a 3 x 5 family on the frequency scale, beside a scalar",
      "vo                  : voltage, real, 15 long, scale = frequency, dims = [3,5]" in out
      and "vmax                : voltage, real, 3 long" in out)
check("[5] two invocations are montecarlo1 and montecarlo2, and the first is still readable",
      "recorded into plot 'montecarlo1'" in out and "recorded into plot 'montecarlo2'" in out
      and len(column(out, "vo[0]")) == 5)
check("[6] the family renders through pyplot", "pyplot: wrote" in out and "fam.png" in out
      and os.path.isfile(os.path.join(WORK, "fam.png")) and os.path.getsize(os.path.join(WORK, "fam.png")) > 1000,
      out.strip()[-160:])

# ------------------------------------------------------- [7]-[9] refusals ---
rc, out = run(DECK, "montecarlo 4 -seed 3 -analysis op -spec v(out)\necho after1", "nolimit")
check("[7] a -spec without a limit is refused, naming -expr",
      "has no -max/-min limit" in out and "use '-expr v(out)'" in out and "after1" in out
      and "yield  :" not in out, out.strip()[-200:])
rc, out = run(DECK, "montecarlo 4 -seed 3 -analysis op\necho after2", "nothing")
check("[8] nothing to judge and nothing to record is refused with both options named",
      "nothing to do" in out and "-spec <metric> -max" in out and "-expr [name=]" in out and "after2" in out,
      out.strip()[-200:])
rc, out = run(DECK, "montecarlo 4 -seed 3 -analysis op -expr v(nosuch)\necho plot=$montecarlo_plot", "unresolved")
check("[9] an -expr that resolves to nothing is refused on sample 1, nothing recorded, $montecarlo_plot unset",
      "-expr expr1 (v(nosuch)) did not resolve" in out and "Nothing is recorded" in out
      and "plot=montecarlo" not in out, out.strip()[-200:])

# ------------------------------------------- [10]-[11] combined, constant ---
rc, out = run(DECK, """montecarlo 8 -seed 3 -analysis op -spec v(out) -max 0.6 -min 0.4 -expr vo=v(out) -expr vin=v(in)
echo yield=$montecarlo_yield plot=$montecarlo_plot
print montecarlo1.vo""", "both")
check("[10] a limited -spec and an -expr together: the yield AND the record",
      "yield  : 100.000%" in out and "yield=1 plot=montecarlo1" in out and len(column(out, "montecarlo1.vo")) == 8,
      out.strip()[-300:])
check("[11] an expression that never varies is noted",
      "-expr vin gave the SAME value in every sample" in out)

# --------------------------------------------------------- [12] ragged ---
rc, out = run(""".param per = aunif(2u, 1u)
V1 in 0 dc 0 pulse(0 1 0 1n 1n 0.5u {per})
R1 in out 1k
C1 out 0 1n""", """montecarlo 4 -seed 3 -analysis "tran 0.5u 8u" -expr vo=v(out) -expr vmax=vecmax(v(out))
setplot $montecarlo_plot
display""", "ragged")
check("[12] a waveform whose point count differs between samples is refused with the reason; the scalar beside it is recorded",
      "-expr vo (v(out)) is not recorded" in out and "same points in every sample" in out
      and "vmax                : voltage, real, 4 long" in out and "dims = [4," not in out,
      out.strip()[-300:])

# ---------------------------------------------------------- [13] old form ---
rc, out = run(DECK, """montecarlo 6 -seed 3 -analysis op -spec v(out) -max 0.6 -min 0.4
echo yield=$montecarlo_yield plot=$montecarlo_plot""", "old")
check("[13] the old form is unchanged: a limited -spec alone reports the yield and creates no plot",
      "yield  : 100.000%" in out and "yield=1" in out and "plot=montecarlo" not in out
      and "recorded into plot" not in out,
      out.strip()[-200:])

# Enhancement-557 (hunt F7): a name the record plot already owns
rc, out = run(DECK, "montecarlo 4 -seed 3 -analysis op -expr sample=@r1[resistance]\necho after3", "resname")
rc2, out2 = run(DECK, "montecarlo 4 -seed 3 -analysis op -expr montecarlo_n=v(out)\necho after4", "resname2")
check("[14] E-557: an -expr named like the plot's own vector (sample, montecarlo_n) is refused, nothing recorded",
      "-expr name 'sample' is the record plot's own vector" in out and "recorded into plot" not in out
      and "after3" in out and "-expr name 'montecarlo_n' is the record plot's own vector" in out2
      and "recorded into plot" not in out2 and "after4" in out2, (out + out2).strip()[-200:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
