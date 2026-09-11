#!/usr/bin/env python3
"""Enhancement-609: montecarlo's flags compose -- an -expr may feed a -track
or a -spec, and a -spec or -expr may read the sample's -track result: the
yield of a tracked quantity in one command.

`montecarlo N -analysis <cmd> -track "<track arguments>" -spec <metric>
-min/-max ...` accepted all four flags together, but a -spec was evaluated on
the analysis plot before the tracks ran, so nothing in it could reach a
track's result: `-spec value` or `-spec track1.value` "did not resolve".
The locators as functions (`-spec "globalmax(v(out))"`) covered the plain
cases only -- not a track's -prominence, -edge, -which, or a region's
x_out/width -- and a yield of a tracked quantity needed a hand-written
repeat loop.

Now the tracks run first and each sample's track plot is kept until the
specs and exprs have read it: `track<k>.<vector>` in a metric names the k-th
-track of the command, for the sample being judged (`track1.value`,
`track2.x_out`, `track1.value[0]` for the first of several hits, and
`track1.hits`, the hit count as a number -- 0 on a miss). A spec on a track
that had no hit for the sample is a violation, counted apart in the report;
an -expr on one leaves nan for that sample. A track<k> beyond the -track
flags given is refused at parse time. And an -expr that does not read a
track is evaluated before the tracks and defined as a vector of the sample's
plot, so `-expr q=... -track "q -spec globalmax -output pk" -spec track1.pk`
chains; an -expr that does read a track is evaluated after them.

Checks (a parabola whose peak position and height vary per sample):
  [1] the four flags together: -spec track1.value -min 2 yields 30/40, the
      same as -spec maximum(v(out)) -min 2; the -expr and the record both there
  [2] a metric mixing the track and the analysis plot: track1.v_sweep /
      maximum(v(out)) -max 0.7, the pass count matching a recount from the
      records
  [3] a region track with misses: -spec track1.hits -max 0 is the yield of
      "no region" (23 of 40); -spec track1.width -min 0.5 counts the misses
      as violations and says so
  [4] -expr w=track1.width: nan on the misses (with a NOTE), the values
      equal to the record's where hit
  [5] a multi-hit track: -spec track1.value[0] judges the first hit; the
      yield matches a recount from the record
  [6] two -track flags: track2. reads the second
  [7] refusals: track2. with one -track, track1. with none, in a -spec and
      in an -expr
  [8] stays: -spec maximum(v(out)) -min 2 without a -track, and -expr beside
      -spec, unchanged
  [9] the chain -expr -> -track -output -> -spec: -expr q=v(out)*2, -track
      "q -spec globalmax -output pk", -spec track1.pk -min 4 yields 30/40,
      the record plot holds pk
  [10] a -spec straight on an -expr's name (-expr qmax=... -spec qmax)
  [11] an -expr reading the track that read an -expr equals the record
  [12] an -expr named like a vector of the analysis plot: the note, once
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
WORK = tempfile.mkdtemp(prefix="mcyield_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


DECK = (".param vmax = agauss(3, 0.3, 1)\n.param g = agauss(1, 0.1, 1)\n"
        "v1 in 0 dc 0\nb1 out 0 v = {g} * v(in) * ({vmax} - v(in))\n")
MC = 'montecarlo 40 -seed 7 -analysis "dc v1 0 5 0.01" '


def run(ctl, tag, deck=DECK):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* mcyield {tag}\n{deck}.control\nset noinit\nset numdgt=8\n{ctl}\n.endc\n.end\n")
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300,
                       cwd=WORK, stdin=subprocess.DEVNULL)
    return p.stdout + p.stderr


def yields(out):
    return [(int(a), int(b)) for a, b in re.findall(r"yield\s*:\s*[\d.]+%\s+\((\d+) / (\d+) pass\)", out)]


def val(out, name):
    m = re.findall(rf"^{re.escape(name)} = ([-+.\deE]+|nan)", out, re.M)
    return [float(x) for x in m]


print("Enhancement-609: the yield of a tracked quantity\n")

# ------------------------------------------------------------- [1] ---
out = run(MC + '-track "v(out) -spec globalmax" -expr pk=maximum(v(out)) -spec "track1.value" -min 2\n'
          'let n = mean(track1.value >= 2) * length(track1.value)\nprint n\nprint mean(montecarlo1.pk)\n'
          + MC + '-spec "maximum(v(out))" -min 2', "t1")
y = yields(out)
check("[1] -analysis, -track, -expr and -spec track1.value together: a yield (30/40), the same as -spec maximum(v(out))",
      len(y) == 2 and y[0] == (30, 40) and y[1] == (30, 40) and "did not resolve" not in out, f"{y} {out[-300:]}")
check("[1] ...the pass count is the record's own count; the -expr is recorded beside it",
      val(out, "n") == [30.0] and val(out, "mean(montecarlo1.pk)") and 2 < val(out, "mean(montecarlo1.pk)")[0] < 3
      and "spec 1 (track1.value): 10 violations" in out, out[-400:])

# ------------------------------------------------------------- [2] ---
out = run(MC + '-track "v(out) -spec globalmax" -expr pk=maximum(v(out)) -spec "track1.v_sweep / maximum(v(out))" -max 0.7\n'
          'let r = track1.v_sweep / montecarlo1.pk\nlet n = mean(r <= 0.7) * length(r)\nprint n', "t2")
y = yields(out)
check("[2] a metric mixing the track and the analysis plot: the pass count matches a recount from the records",
      len(y) == 1 and y[0][1] == 40 and val(out, "n") == [float(y[0][0])] and "did not resolve" not in out,
      f"{y} {val(out, 'n')} {out[-300:]}")

# ------------------------------------------------------------- [3] ---
out = run(MC + '-track "v(out) -spec v(out)>2.3 -at mid" -spec "track1.hits" -max 0\n'
          + MC + '-track "v(out) -spec v(out)>2.3 -at mid" -spec "track1.width" -min 0.5\n'
          'let n = mean(track2.width >= 0.5) * length(track2.width)\nprint n\nprint track2.hits[0]', "t3")
y = yields(out)
hits = int(re.search(r"a hit in (\d+) of 40 samples", out).group(1)) if re.search(r"a hit in (\d+) of 40 samples", out) else -1
check("[3] -spec track1.hits -max 0 on a region track with misses: the yield of 'no region' (40 - hits)",
      len(y) == 2 and hits > 0 and y[0] == (40 - hits, 40) and f"spec 1 (track1.hits): {hits} violations" in out,
      f"{y} hits={hits} {out[-300:]}")
n_w = val(out, "n")
check("[3] ...-spec track1.width -min 0.5: the misses are violations, counted apart; the passes recounted",
      len(y) == 2 and n_w and y[1][0] == int(n_w[0])
      and re.search(rf"spec 1 \(track1\.width\): \d+ violations \({40 - hits} of them samples whose track had no hit to judge\)", out),
      f"{y} {n_w} {out[-300:]}")

# ------------------------------------------------------------- [4] ---
out = run(MC + '-track "v(out) -spec v(out)>2.3 -at mid" -expr w=track1.width\n'
          'let same = montecarlo1.w eq track1.width\nprint mean(same) * length(same)\n'
          'print length(montecarlo1.w)', "t4")
hits = int(re.search(r"a hit in (\d+) of 40 samples", out).group(1)) if re.search(r"a hit in (\d+) of 40 samples", out) else -1
check("[4] -expr w=track1.width: nan on the misses with a NOTE, the record's width where hit",
      re.search(rf"NOTE\s*: -expr w is nan on {40 - hits} samples whose track had no hit", out)
      and val(out, "mean(same) * length(same)") == [float(hits)] and val(out, "length(montecarlo1.w)") == [40.0],
      f"hits={hits} {out[-300:]}")

# ------------------------------------------------------------- [5] ---
SINE = (".param f = agauss(1, 0.1, 1)\n.param a = agauss(1, 0.1, 1)\nv1 in 0 dc 0\n"
        "b1 out 0 v = {a} * sin(2*3.14159*{f}*v(in)) * (3 - v(in))\n")
out = run('montecarlo 30 -seed 3 -analysis "dc v1 0 3 0.005" -track "v(out) -spec localmax -prominence 0.1" '
          '-spec "track1.value[0]" -min 2.2\nlet n = mean(track1.value[0] >= 2.2) * length(track1.value[0])\nprint n\n'
          'print track1.hits[0] track1.hits[1]', "t5", deck=SINE)
y = yields(out)
check("[5] a multi-hit track: -spec track1.value[0] judges the first hit; the yield matches the record's recount",
      len(y) == 1 and y[0][1] == 30 and val(out, "n") == [float(y[0][0])] and "at most" in out
      and val(out, "track1.hits[0]") and val(out, "track1.hits[0]")[0] >= 2, f"{y} {val(out, 'n')} {out[-300:]}")

# ------------------------------------------------------------- [6] ---
out = run('montecarlo 30 -seed 3 -analysis "dc v1 0 3 0.005" -track "v(out) -spec localmax -prominence 0.1" '
          '-track "v(out) -spec localmin -prominence 0.1 -which first" -spec "track2.value" -max -1.5 -expr dip=track2.value\n'
          'let n = mean(track2.value <= -1.5) * length(track2.value)\nprint n\nlet d = montecarlo1.dip - track2.value\nprint maximum(abs(d))',
          "t6", deck=SINE)
y = yields(out)
check("[6] two -track flags: track2. reads the second, in the -spec and in an -expr",
      len(y) == 1 and val(out, "n") == [float(y[0][0])] and val(out, "maximum(abs(d))") == [0.0]
      and "spec 1 (track2.value)" in out, f"{y} {out[-300:]}")

# ------------------------------------------------------------- [7] ---
out = run(MC + '-track "v(out) -spec globalmax" -spec "track2.value" -min 2\n'
          + MC + '-spec "track1.value" -min 2\n'
          + MC + '-track "v(out) -spec globalmax" -expr q=track3.value', "t7")
check("[7] refusals: track2. with one -track, track1. with none, an -expr's track3.",
      "-spec 'track2.value' reads track2, but only one -track was given" in out
      and "-spec 'track1.value' reads track1, but no -track was given" in out
      and "-expr 'track3.value' reads track3, but only one -track was given" in out
      and "pass)" not in out, out[-500:])

# ------------------------------------------------------------- [8] ---
out = run(MC + '-spec "maximum(v(out))" -min 2\n' + MC + '-expr pk=maximum(v(out)) -spec "maximum(v(out))" -min 2', "t8")
y = yields(out)
check("[8] stays: a -spec on the analysis plot, with and without an -expr beside it",
      y == [(30, 40), (30, 40)] and "montecarlo1" in out, f"{y}")

# ------------------------------------------------------------- [9] ---
out = run(MC + '-expr q=v(out)*2 -track "q -spec globalmax -output pk" -spec "track1.pk" -min 4\n'
          'setplot $track_plot\nlet n = mean(pk >= 4) * length(pk)\nprint n', "t9")
y = yields(out)
check("[9] the chain -expr q -> -track \"q ... -output pk\" -> -spec track1.pk: 30/40, the record holds pk",
      y == [(30, 40)] and val(out, "n") == [30.0] and "plot track1: sample, hits, v_sweep, pk, index" in out
      and "did not resolve" not in out, f"{y} {out[-300:]}")

# ------------------------------------------------------------ [10] ---
out = run(MC + '-expr qmax=maximum(v(out)*2) -spec qmax -min 4', "t10")
y = yields(out)
check("[10] a -spec straight on an -expr's name: 30/40",
      y == [(30, 40)] and "spec 1 (qmax): 10 violations" in out, f"{y} {out[-300:]}")

# ------------------------------------------------------------ [11] ---
out = run(MC + '-expr q=v(out)*2 -track "q -spec globalmax -output pk" -expr pkv=track1.pk -spec "track1.pk" -min 4\n'
          'set tp = $track_plot\nlet same = montecarlo1.pkv eq {$tp}.pk\nprint mean(same) * length(same)', "t11")
y = yields(out)
check("[11] an -expr reading the track that read an -expr: equal to the record on every sample",
      y == [(30, 40)] and val(out, "mean(same) * length(same)") == [40.0], f"{y} {out[-300:]}")

# ------------------------------------------------------------ [12] ---
out = run('montecarlo 10 -seed 7 -analysis "dc v1 0 5 0.01" -expr out=v(out)*2 -spec "maximum(out)" -min 2', "t12")
check("[12] an -expr named like a vector of the analysis plot: the note, once; the spec reads the plot's",
      out.count("the analysis plot already has a vector of that name") == 1 and yields(out) == [(8, 10)],
      out[-400:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
