#!/usr/bin/env python3
"""Enhancement-582: `montecarlo -track "<track arguments>"` -- track runs after
every sample's analysis and its hits are recorded per sample.

`track` (E-577) is a command, not an expression, so it could not be given to
montecarlo: `-analysis` runs exactly one command, and "-analysis track ..."
tracked the stale plot N times. The alternative was a hand-written repeat loop
around reset / tran / track with $track_plot and $track_hits (E-581).

Now `-track "<track arguments>"` (quoted, repeatable) runs `track <arguments>`
after every sample's analysis, silently, and records the result into the
montecarlo<n> plot beside the -expr vectors: `track_hits` (the hit count per
sample; 0 a miss, nan a sample that never solved) and every vector of the
track plot -- the scale, value, index, a region's x_out and width -- as
`track_<vector>`: an Lmax x N family whose row k (`track_time[k]`) is hit k of
every sample on the sample scale, nan where a sample had fewer, Lmax being the
largest count seen (a varying count is the usual case, and the one -expr
refuses); when no sample ever has more than one hit, plain N-long vectors.
Several -track flags record as track1_*, track2_*. The per-sample
track plots are destroyed as they are recorded; a real error in the track
arguments stops the run on its first sample instead of repeating per sample.

The deck is an RLC step response whose ringing depends on a random resistor.

Checks (both solvers):
  [1]  the record: track_hits per sample equals length(localmax(v(out))) recorded
       by -expr beside it; the first tracked peak is globalmax(v(out))
  [2]  the families: [Lmax,N] dims, each sample's column holds exactly its hits
       then nan, increasing in time; track_time[1] is the second hit of every
       sample, N long; value carries the voltage type
  [3]  a region spec with -which first: plain N-long vectors, x_out and width
       present, width == x_out - time on every sample
  [4]  two -track flags: track1_* and track2_* with different counts
  [5]  a miss is silent and recorded as 0 with an all-nan row; a spec that never
       hits is noted; $track_hits/$track_plot reflect the last sample; no track
       plot survives the run
  [6]  an error in the track arguments stops on sample 1 with one message,
       nothing recorded, $montecarlo_plot unset
  [7]  -track without its argument is refused; nothing to do names -track
  [8]  a limited -spec and a -track together: the yield AND the record; -lhs
  [9]  a single -track with -expr: the summary counts both as records
  [10] E-583: a dc sweep -- the scale `v-sweep` records as track_v_sweep (a
       hyphen would be subtraction in `let`); a CMOS inverter's switching point
       per sample equals (vtn + vdd + vtp)/2 for a beta ratio of 1; a region's
       x_out and width in volts; and no spurious "Phi is not positive" from the
       fast path on MOS models without an explicit phi
"""
import math
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
WORK = tempfile.mkdtemp(prefix="mctrack_")


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


DECK = """.param rr = agauss(20, 30, 3)
V1 in 0 pulse(0 1 0 1n 1n 1m 2m)
R1 in a {rr}
L1 a out 1m
C1 out 0 1u"""


def run(ctl, tag, deck=DECK):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(f"* mctrack {tag}\n{deck}\n.control\nset numdgt=10\nset noinit\n{ctl}\n.endc\n.end\n")
    r = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                       timeout=300, cwd=WORK, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout + r.stderr


def column(out, name, nth=0):
    """The values of the nth printed vector column named `name` (print's table
    form; -1 the last print of it); nan is kept as float('nan')."""
    lines = out.splitlines()
    found = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("Index") and name in ln.split():
            cols = ln.split()
            j = cols.index(name)
            vals = []
            k = i + 1
            for row in lines[k:]:
                k += 1
                t = row.split()
                if not t or not re.match(r"^\d+$", t[0]):
                    if vals:
                        break
                    continue
                vals.append(float(t[j]))
            found.append(vals)
            i = k
            continue
        i += 1
    return found[nth] if found else []


def val(out, name):
    m = re.findall(re.escape(name) + r"\s*=\s*(-?[\d.]+(?:[eE][-+]?\d+)?)", out, re.I)
    return float(m[-1]) if m else None


def rows_of(vals, n):
    """the per-sample hit lists of a printed [L, n] (hit-major) family"""
    L = len(vals) // n
    return [[vals[k * n + i] for k in range(L)] for i in range(n)]


def dims(out, name):
    m = re.search(re.escape(name) + r"\s*:.*?(\d+) long(?:, dims = \[(\d+),(\d+)\])?", out)
    if not m:
        return None
    return (int(m.group(1)), (int(m.group(2)), int(m.group(3))) if m.group(2) else None)


def vtype(out, name):
    m = re.search(re.escape(name) + r"\s*:\s*(\w+),", out)
    return m.group(1) if m else None


print("Enhancement-582: montecarlo -track\n")
N = 8

# ------------------------------------------------------- [1]-[2] the record ---
rc, out = run(f"""montecarlo {N} -seed 3 -analysis "tran 2u 1m" -track "v(out) -spec localmax -raw" -expr npk=length(localmax(v(out))) -expr tpk=globalmax(v(out)) -expr r=@r1[resistance]
echo plot=$montecarlo_plot
display
print track_hits npk tpk r
print track_time
print track_value
print track_index
print track_time[1]""", "rec")
hits = column(out, "track_hits")
npk = column(out, "npk")
tpk = column(out, "tpk")
rr = column(out, "r")
tt = column(out, "track_time")
tv = column(out, "track_value")
d_hits = dims(out, "track_hits")
d_time = dims(out, "track_time")
lmax = int(max(hits)) if hits else 0
check("[1] montecarlo1 made; track_hits is N long and equals length(localmax(v(out))) on every sample; "
      "the samples differ (r spread)",
      "plot=montecarlo1" in out and len(hits) == N and hits == npk and len(set(hits)) > 1
      and max(rr) - min(rr) > 5,
      f"hits={hits} npk={npk}")
first_pk = [rows_of(tt, N)[i][0] for i in range(N)] if tt and lmax else []
check("[1] the first tracked peak of every sample (-raw: the sample position, as the locator functions give it) "
      "is globalmax(v(out)) recorded by -expr beside it",
      len(first_pk) == N and all(abs(a - b) <= 1e-9 * max(1.0, abs(b)) for a, b in zip(first_pk, tpk)),
      f"first={first_pk[:3]}... tpk={tpk[:3]}...")
ok = d_time is not None and d_time[1] == (lmax, N) and lmax > 1 and d_hits is not None and d_hits[1] is None
check(f"[2] track_time/value/index are [{lmax},{N}] families (Lmax the largest count, hit-major), track_hits a plain vector",
      ok and dims(out, "track_value") == d_time and dims(out, "track_index") == d_time,
      f"time={d_time} hits={d_hits}")
good = bool(tt) and len(tt) == N * lmax
if good:
    for i, row in enumerate(rows_of(tt, N)):
        h = int(hits[i])
        real = [x for x in row if not math.isnan(x)]
        good &= len(real) == h and all(math.isnan(x) for x in row[h:])
        good &= all(b > a for a, b in zip(real, real[1:]))
        good &= all(0.0 < x < 1e-3 for x in real)
check("[2] each sample's column holds exactly its hits, increasing in time, then nan", good,
      f"rows={[sum(not math.isnan(x) for x in r) for r in rows_of(tt, N)] if good else tt[:6]}")
vr = rows_of(tv, N) if tv else []
second = column(out, "track_time[1]")
check("[2] track_time[1] is the second hit of every sample: N long, equal to column 1, nan where a sample had one hit",
      len(second) == N and all((math.isnan(a) and math.isnan(b)) or a == b
                                for a, b in zip(second, [rows_of(tt, N)[i][1] for i in range(N)]))
      and any(math.isnan(x) for x in second) == any(h < 2 for h in hits),
      f"second={second[:4]}...")
check("[2] the value family carries the voltage type and its first peak per sample is an overshoot (>1)",
      vtype(out, "track_value") == "voltage" and vtype(out, "track_time") == "time"
      and len(vr) == N and all(1.0 < r[0] < 2.0 for r in vr if int(hits[vr.index(r)]) > 0),
      f"types={vtype(out, 'track_value')},{vtype(out, 'track_time')}")
check("[2] the summary line names the record: hits in n of N samples, at most Lmax, [N,Lmax] families",
      re.search(rf"-track \"v\(out\) -spec localmax -raw\": hits in \d+ of {N} samples, at most {lmax} per sample "
                rf"-- track_hits and track_<vector> \(3 vectors, \[{lmax},{N}\] families: row k is hit k of every "
                rf"sample, nan where it had fewer\)", out) is not None
      and "records over 8 samples recorded into plot 'montecarlo1'" in out)

# ------------------------------------------------- [3] region, -which first ---
rc, out = run(f"""montecarlo {N} -seed 3 -analysis "tran 2u 1m" -track "v(out) -spec 'v(out) > 1.02' -which first"
display
print track_hits track_time track_x_out track_width track_value""", "region")
hits = column(out, "track_hits")
t0 = column(out, "track_time")
xo = column(out, "track_x_out")
wd = column(out, "track_width")
check("[3] a region spec with -which first: plain N-long vectors (no dims), x_out and width present, width == x_out - time",
      dims(out, "track_time") == (N, None) and dims(out, "track_x_out") == (N, None)
      and dims(out, "track_width") == (N, None) and len(wd) == N
      and all(abs(w - (x - t)) <= 1e-12 for w, x, t in zip(wd, xo, t0) if not math.isnan(w))
      and all(h in (0.0, 1.0) for h in hits) and sum(hits) >= 6,
      f"hits={hits}")
check("[3] said as such: a hit in n of N samples, never more than one, 5 vectors N long",
      re.search(rf"a hit in \d+ of {N} samples, never more than one -- track_hits and track_<vector> "
                rf"\(5 vectors, {N} long, nan where a sample had no hit\)", out) is not None)

# ------------------------------------------------------- [4] two -track ---
rc, out = run(f"""montecarlo 4 -seed 3 -analysis "tran 2u 1m" -track "v(out) -spec localmax -prominence 20m" -track "v(out) -spec localmin -prominence 20m"
display
print track1_hits track2_hits""", "two")
h1 = column(out, "track1_hits")
h2 = column(out, "track2_hits")
check("[4] two -track flags record as track1_* and track2_*, each with its own count per sample "
      "(one more maximum than minima at 20m prominence on a step)",
      len(h1) == 4 and len(h2) == 4 and h1 != h2 and all(a >= b for a, b in zip(h1, h2))
      and "track1_time" in out and "track2_time" in out and "track1_hits and track1_<vector>" in out
      and "2 records over 4 samples" in out,
      f"h1={h1} h2={h2}")

# ---------------------------------------------- [5] misses, the variables ---
rc, out = run(f"""montecarlo {N} -seed 3 -analysis "tran 2u 1m" -track "v(out) -spec localmin -prominence 20m"
echo last=$track_plot:$track_hits
print track_hits
print track_time
montecarlo 4 -seed 3 -analysis "tran 2u 1m" -track "v(out) -spec localmax -prominence 5"
print track_hits
echo plots=$plots
track v(out) -spec localmax -analysis tran4""", "miss")
hits = column(out, "track_hits")
tt = column(out, "track_time")
zero = [i for i, h in enumerate(hits) if h == 0.0]
lm = len(tt) // N if tt else 0
check("[5] a sample with no hit is 0 in track_hits with an all-nan column, and is silent (no 'no hit' / 'track failed!')",
      len(zero) >= 1 and lm > 0 and all(all(math.isnan(x) for x in rows_of(tt, N)[i]) for i in zero)
      and "no hit of" not in out and "track failed!" not in out,
      f"hits={hits}")
last_hits = hits[-1] if hits else None
m = re.search(r"last=(\S*):(\d+)", out)
check("[5] $track_plot/$track_hits hold the last sample's result afterwards",
      m is not None and int(m.group(2)) == int(last_hits)
      and ((last_hits > 0) == m.group(1).startswith("track")),
      m.group(0) if m else "")
h5 = column(out, "track_hits", -1)
check("[5] a -track that never hits is noted and records 0 for every sample; no -track plot survives the run "
      "(the per-sample track plots are destroyed as they are recorded)",
      "NOTE   : no sample had a hit for -track \"v(out) -spec localmax -prominence 5\"" in out
      and h5 == [0.0] * 4 and re.search(r"plots=[^\n]*track", out) is None
      and re.search(r"^track\d+: \d+ hits? of localmax on tran4", out, re.M) is not None,
      re.search(r"plots=.*", out).group(0)[:80] if re.search(r"plots=.*", out) else "")

# --------------------------------------------- [6]-[7] refusals ---
rc, out = run("""montecarlo 4 -seed 3 -analysis "tran 2u 1m" -track "v(nosuch) -spec localmax" -expr r=@r1[resistance]
echo plot=$montecarlo_plot
montecarlo 4 -seed 3 -analysis "tran 2u 1m" -track "v(out) -spec localmax -bogus 1"
echo plot=$montecarlo_plot""", "err")
check("[6] a track argument error stops the run on sample 1 with the message once, nothing recorded, "
      "$montecarlo_plot unset",
      out.count("cannot parse expression 'v(nosuch)'") == 1
      and "-track \"v(nosuch) -spec localmax\" failed on sample 1" in out
      and "Nothing is recorded" in out and "plot=montecarlo" not in out
      and out.count("track failed!") == 2 and "-bogus" in out and "failed on sample 1" in out)
rc, out = run("""montecarlo 4 -seed 3 -analysis "tran 2u 1m" -track
montecarlo 4 -seed 3 -analysis "tran 2u 1m"
montecarlo 4 -seed 3 -analysis "tran 2u 1m" -track "" """, "usage")
check("[7] -track without its argument is refused with the quoted form shown; nothing to do names -track; "
      "an empty -track is refused",
      "-track needs the track arguments, quoted: -track \"v(out) -spec localmax\"" in out
      and "nothing to do" in out and "-track \"<track arguments>\"" in out
      and out.count("-track needs the track arguments") == 2 and "montecarlo1" not in out)

# -------------------------------------------------- [8]-[9] with a yield ---
rc, out = run(f"""montecarlo {N} -seed 3 -lhs -analysis "tran 2u 1m" -spec "globalmax(v(out))" -max 1.6 -track "v(out) -spec localmax -prominence 20m" -expr r=@r1[resistance]
print montecarlo_yield
print track_hits r""", "yield")
hits = column(out, "track_hits")
y = val(out, "montecarlo_yield")
check("[8] a limited -spec and a -track together, with -lhs: the yield is reported AND the hits recorded",
      re.search(r"^  yield  : [\d.]+%  \(\d+ / 8 pass\)", out, re.M) is not None and y is not None
      and 0.0 <= y <= 1.0 and len(hits) == N and sum(hits) > 0 and "2 records over 8 samples" in out
      and "Latin-Hypercube" in out,
      f"yield={y} hits={hits}")
rc, out = run("""montecarlo 3 -seed 3 -analysis "tran 2u 1m" -track "v(out) -spec localmax -prominence 20m"
print track_hits""", "one")
check("[9] a lone -track is a record on its own: 'recording' said, 1 record over 3 samples, no yield",
      "1 record over 3 samples recorded into plot 'montecarlo1'" in out and "no yield (no -spec)" in out
      and len(column(out, "track_hits")) == 3)

# ------------------------------------------------- [10] a dc sweep (E-583) ---
INV = """.param vtn = agauss(0.7, 0.1, 3)
.param vtp = agauss(-0.7, 0.1, 3)
.model nm nmos level=1 vto={vtn} kp=120u lambda=0.02
.model pm pmos level=1 vto={vtp} kp=60u  lambda=0.02
Vdd vdd 0 3
Vin in  0 0
M1 out in 0   0   nm w=2u l=1u
M2 out in vdd vdd pm w=4u l=1u"""
rc, out = run("""montecarlo 6 -seed 7 -analysis "dc vin 0 3 5m" -track "v(out) -spec 'v(out) == v(in)'" -track "v(out) -spec 'abs(deriv(v(out))) > 1'" -expr vtn=@nm[vto] -expr vtp=@pm[vto]
display
print track1_v_sweep vtn vtp
print track2_v_sweep track2_x_out track2_width""", "dc", deck=INV)
vsw = column(out, "track1_v_sweep")
vtn = column(out, "vtn")
vtp = column(out, "vtp")
xin = column(out, "track2_v_sweep")
xout = column(out, "track2_x_out")
wid = column(out, "track2_width")
check("[10] a dc sweep: the scale records as track1_v_sweep (voltage type) and prints; the switching point per sample "
      "is (vtn + vdd + vtp)/2 within 20 mV (beta ratio 1) and moves with the drawn thresholds",
      len(vsw) == 6 and "track1_v_sweep      : voltage" in out and "track1_v-sweep" not in out
      and all(abs(v - (a + 3.0 + b) / 2) < 0.02 for v, a, b in zip(vsw, vtn, vtp)) and max(vsw) - min(vsw) > 0.02,
      f"vsw={[round(v, 4) for v in vsw]}")
check("[10] the gain region per sample: entry below and exit above the switching point, width == x_out - entry, in volts",
      len(wid) == 6 and all(a < v < b for a, v, b in zip(xin, vsw, xout))
      and all(abs(w - (b - a)) < 1e-9 for w, a, b in zip(wid, xin, xout)) and all(0.3 < w < 0.6 for w in wid)
      and "track2_width        : voltage" in out)
check("[10] no spurious 'Phi is not positive' from the fast path on the first sample (E-583: the temperature pass "
      "waits for the circuit to be set up); the fast path still armed",
      "Phi is not positive" not in out and "Fatal error" not in out and "fast path armed (2 random value bindings" in out)

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
