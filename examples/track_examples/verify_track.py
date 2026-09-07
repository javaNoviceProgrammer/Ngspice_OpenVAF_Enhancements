#!/usr/bin/env python3
"""
verify_track.py -- the `track` command and the locator functions (Enhancement-577),
end-to-end through the committed ngspice on both solvers.

`track <expr> [<expr> ...] [-range x0 x1] [-spec <spec>] [-analysis <plot|type>]
 [-which ...] [-edge ...] [-at ...] [-prominence p] [-raw] [-output name ...]`
turns a spec into the set of x positions where it holds, reads every expression there,
and packages both into a plot trackN of its own. localmin/localmax/globalmin/globalmax
are also `let` functions returning the x positions.

  1. a transient sine: localmax at (k+1/4)T, the count from -range, -which -1 the last,
     -raw the sample and the refined value nearer the amplitude; `let localmax(v(a))`
     the same positions
  2. an RC step crossing at tau*ln2; a square wave's rise, fall and both edges
  3. regions: v(b)<=-1 on an amplitude-2 sine, width exactly T/3 with interpolated
     boundaries, -at mid reading -2; a boolean spec with sample-midpoint boundaries
  4. several expressions at once under one spec: value1..N, or -output names
  5. prominence on a rippled sine, and one maximum per plateau on a clipped one
  6. ac: db(v(out))==-3 on an RC at the corner through log-x interpolation; a
     complex-valued spec refused with the mag() hint
  7. -analysis by name and by type while another plot is current; a wrong name lists
     the plots; plot_cur unchanged; a descending dc sweep with -range either way
  8. refusals: zero hits (no plot made, `track failed!`), -which out of range, an
     unknown option, a locator on two samples, -edge/-at/-prominence on the wrong
     spec kind, a nested dc sweep; `define` composes; an unquoted <= spec parses

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


def ngspice(deck):
    with open(os.path.join(HERE, "_o.cir"), "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", "_o.cir"], cwd=HERE, capture_output=True,
                       text=True, timeout=120)
    return r.stdout + r.stderr


def deck(body, ctl):
    return f"* track\n{body}\n.control\nset numdgt=10\n{ctl}\n.endc\n.end\n"


def rows(out, tag):
    """the batch rows of the track whose summary carries `tag`: list of dicts"""
    got = []
    on = False
    for line in out.splitlines():
        m = re.match(r"^(track\d+): (\d+) hits? of (.*)$", line)
        if m:
            on = tag in m.group(3) or tag == m.group(1)
            continue
        if on and line.startswith("  ") and "=" in line:
            d = {}
            for kv in line.split():
                k, _, v = kv.partition("=")
                try:
                    d[k] = float(v)
                except ValueError:
                    pass
            if d:                                    # the mapping line under a summary carries no numbers
                got.append(d)
        elif on and not line.startswith(" "):
            on = False
    return got


def summary(out, tag):
    for line in out.splitlines():
        m = re.match(r"^(track\d+): (\d+) hits? of (.*)$", line)
        if m and (tag in m.group(3) or tag == m.group(1)):
            return int(m.group(2)), m.group(1), line
    return None, None, None


def values(out):
    vals = {}
    for line in out.splitlines():
        m = re.match(r"\s*([\w.()#\-\[\]]+)\s*=\s*(-?[\d.]+e[-+]\d+|-?[\d.]+)\s*$", line)
        if m:
            try:
                vals[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                pass
    return vals


def near(a, b, tol):
    return a is not None and b is not None and abs(a - b) <= tol


SINE = "va a 0 sin(0 1 1k)\nvb b 0 sin(0 2 1k)\nvs s 0 pulse(0 1 0 1n 1n 0.5m 1m)\nvr r 0 pwl(0 0 1u 1)\nrr r o 1k\nc1 o 0 1u\n"


def main():
    ok = True

    def check(label, cond, detail=""):
        nonlocal ok
        ok = ok and cond
        print(f"  {'PASS' if cond else 'FAIL'}  {label}   {detail}")

    print("[1] a transient sine: localmax")
    out = ngspice(deck(SINE, "tran 1u 5m\ntrack v(a) -spec localmax\ntrack v(a) -spec localmax -range 1.1m 3.9m\n"
                             "track v(a) -spec localmax -which -1\ntrack v(a) -spec localmax -which 1 -raw\n"
                             "let lm = localmax(v(a))\nprint lm[0] lm[4] length(lm)\nprint track1.time[2] track1.value[2]"))
    r = rows(out, "track1")
    check("five maxima at (k+1/4)T within 1e-7 s, the refined value 1 within 1e-5",
          len(r) == 5 and all(near(h["time"], (k + 0.25) * 1e-3, 1e-7) and near(h["value"], 1.0, 1e-5) for k, h in enumerate(r)),
          f"{[h.get('time') for h in r]}")
    n2, _, _ = summary(out, "track2")
    check("-range 1.1m 3.9m keeps the three inside", n2 == 3, f"{n2}")
    r3 = rows(out, "track3")
    check("-which -1 is the last, at 4.25 ms", len(r3) == 1 and near(r3[0]["time"], 4.25e-3, 1e-7), f"{r3}")
    r4 = rows(out, "track4")
    check("-raw reports the sample: value below 1 and the refined value closer to the amplitude",
          len(r4) == 1 and r4[0]["value"] < 1.0 and (1.0 - r4[0]["value"]) > 1e-6 and near(r[0]["value"], 1.0, 1e-6), f"{r4}")
    v = values(out)
    check("`let lm = localmax(v(a))` gives the same positions (length 5, first and last)",
          near(v.get("length(lm)"), 5, 0) and near(v.get("lm[0]"), r4[0]["time"], 1e-9) and near(v.get("lm[4]"), 4.25e-3, 2e-6), f"{v}")
    check("`print track1.time[2]` reads the plot from another plot: 2.25 ms, value 1",
          near(v.get("track1.time[2]"), 2.25e-3, 1e-7) and near(v.get("track1.value[2]"), 1.0, 1e-5), "")

    print("[2] crossings")
    out = ngspice(deck(SINE, "tran 1u 5m\ntrack v(o) -spec v(o)==0.5\ntrack v(s) -spec v(s)==0.5 -edge rise\n"
                             "track v(s) -spec v(s)==0.5 -edge fall\ntrack v(s) -spec v(s)==0.5 -edge both -range 0 1.2m\nprint track4.edge"))
    r = rows(out, "track1")
    check("an RC step crossing 0.5 at tau*ln2 (1 us ramp): 0.6936 ms within 2 us",
          len(r) == 1 and near(r[0]["time"], 1e-3 * math.log(2) + 0.5e-6, 2e-6) and near(r[0]["value"], 0.5, 1e-9), f"{r}")
    n_rise, _, _ = summary(out, "track2"); n_fall, _, _ = summary(out, "track3")
    check("a square wave: 5 rising, 5 falling edges in 5 ms", n_rise == 5 and n_fall == 5, f"{n_rise} {n_fall}")
    r = rows(out, "track4")
    check("-edge both in 0..1.2 ms writes edge = +1, -1, +1", [h.get("edge") for h in r] == [1.0, -1.0, 1.0], f"{[(h.get('time'), h.get('edge')) for h in r]}")

    print("[3] regions and a boolean spec")
    out = ngspice(deck(SINE, "tran 1u 5m\ntrack v(b) -spec v(b)<=-1.0 -at mid\ntrack v(a) -spec v(a)>0 & v(b)>0 -range 0 2.5m"))
    r = rows(out, "track1")
    check("v(b)<=-1 on an amplitude-2 sine: five regions of width T/3 = 333.33 us within 0.2 us, boundaries interpolated",
          len(r) == 5 and all(near(h["width"], 1e-3 / 3, 2e-7) and near(h["time"], (k + 7.0 / 12) * 1e-3, 2e-7) for k, h in enumerate(r)), f"{r[:2]}")
    check("-at mid reads the trough, -2 within 1e-4", all(near(h["value"], -2.0, 1e-4) for h in r), "")
    n, _, line = summary(out, "track2")
    check("a boolean spec: three regions and the summary says the boundaries are sample midpoints",
          n == 3 and line is not None and "boundaries at sample midpoints" in line, f"{line}")

    print("[4] several expressions under one spec, and the expression forms")
    out = ngspice(deck(SINE, "tran 1u 5m\ntrack v(a) v(b) v(s) -spec localmax(v(a)) -range 0 2.5m\n"
                             "track v(a) v(b) -spec localmax -output pk vb -range 0 1.5m\nprint track2.pk track2.vb\n"
                             "let p = v(a)*v(b)\ntrack p -spec localmax -range 0 1.1m\ntrack v(a)*v(b) -spec localmax -range 0 1.1m\n"
                             "track \"v(a) * v(b)\" -spec localmax -range 0 1.1m\ntrack v(a) 3*v(a)^2 -spec deriv(v(a))==0 -range 0 1.1m"))
    r3, r4, r5 = rows(out, "track3"), rows(out, "track4"), rows(out, "track5")
    check("a `let` vector, an inline expression and a quoted expression with spaces track alike (two maxima of v(a)*v(b))",
          len(r3) == 2 and r3 == r4 == r5 and near(r3[0]["time"], 0.25e-3, 2e-6), f"{[h.get('time') for h in r3]} {len(r4)} {len(r5)}")
    r6 = rows(out, "track6")
    check("functions in the spec and the expressions: deriv(v(a))==0 read on v(a) and on 3*v(a)^2 -> +-1 and 3",
          len(r6) == 2 and near(abs(r6[0]["value1"]), 1.0, 1e-4) and near(r6[0]["value2"], 3.0, 1e-3), f"{r6}")
    r = rows(out, "track1")
    check("value1..value3 at the three maxima of v(a): 1, 2, 1",
          len(r) == 3 and all(near(h["value1"], 1, 1e-5) and near(h["value2"], 2, 1e-4) and near(h["value3"], 1, 1e-9) for h in r), f"{r[:1]}")
    check("the summary names the mapping", "value1=v(a) value2=v(b) value3=v(s)" in out, "")
    r2 = rows(out, "track2")
    check("-output pk vb names the vectors: pk = 1, vb = 2 at both maxima, and `print track2.pk` finds them",
          len(r2) == 2 and all(near(h["pk"], 1.0, 1e-5) and near(h["vb"], 2.0, 1e-4) for h in r2)
          and "track2.pk" in out and "not available" not in out, f"{r2}")

    print("[5] prominence and plateaus")
    body = "va a 0 sin(0 1 1k)\nbn n 0 v = v(a) + 0.01*sin(2*pi*50k*time)\nbc c 0 v = v(a) > 0.5 ? 0.5 : v(a)\n"
    out = ngspice(deck(body, "tran 0.5u 3m\ntrack v(n) -spec localmax\ntrack v(n) -spec localmax -prominence 0.1\n"
                             "track v(n) -spec localmin -prominence 0.1\ntrack v(c) -spec localmax"))
    n_raw, _, _ = summary(out, "track1")
    r2 = rows(out, "track2"); r3 = rows(out, "track3"); r4 = rows(out, "track4")
    check("raw localmax on the rippled sine: far more than the three periods", n_raw is not None and n_raw > 30, f"{n_raw}")
    check("-prominence 0.1: exactly one maximum per period, at the crest within a ripple period",
          len(r2) == 3 and all(near(h["time"], (k + 0.25) * 1e-3, 25e-6) for k, h in enumerate(r2)), f"{[h['time'] for h in r2]}")
    check("...and one minimum per period", len(r3) == 3 and all(near(h["time"], (k + 0.75) * 1e-3, 25e-6) for k, h in enumerate(r3)), "")
    check("a clipped sine: one maximum per plateau at its midpoint, value 0.5",
          len(r4) == 3 and all(near(h["time"], (k + 0.25) * 1e-3, 2e-6) and near(h["value"], 0.5, 1e-9) for k, h in enumerate(r4)), f"{r4}")

    print("[6] ac")
    rc = "v1 in 0 dc 0 ac 1\nr1 in out 1k\nc1 out 0 159.155nF\n"
    out = ngspice(deck(rc, "ac dec 20 10 100k\ntrack db(v(out)) -spec db(v(out))==-3.0103\ntrack v(out) -spec v(out)>0.5"))
    r = rows(out, "track1")
    check("db(v(out))==-3.01 on an RC: the corner at 1 kHz within 0.1 % through log-x interpolation",
          len(r) == 1 and near(r[0]["frequency"], 1000.0, 1.0), f"{r}")
    check("a complex-valued spec is refused with the mag() hint",
          "is complex-valued; wrap it in mag(), db(), ph() or real()" in out and out.count("track failed!") == 1, "")

    print("[7] -analysis, plot_cur, a descending sweep")
    body = "vd d 0 dc 1 sin(0 1 1k)\nrd d 0 1k\n"
    out = ngspice(deck(body, "tran 1u 3m\nac dec 5 1 100\ntrack v(d) -spec globalmax -analysis tran1\n"
                             "track v(d) -spec globalmax -analysis tran\ntrack v(d) -spec globalmax -analysis nosuch\nsetplot\n"
                             "dc vd 3 -3 -0.5\ntrack v(d) -spec v(d)==1 -range 2 0\ntrack v(d) -spec v(d)==1 -range 0 2"))
    r1 = rows(out, "track1"); r2 = rows(out, "track2")
    check("-analysis tran1 while ac1 is current: the sine's global maximum at 2.25 ms",
          len(r1) == 1 and near(r1[0]["time"], 2.25e-3, 5e-6), f"{r1}")
    check("-analysis tran (a type) picks the same plot", r2 == r1, "")
    check("a wrong name is refused and the plots are listed",
          "-analysis nosuch matches no plot; there are:" in out and "tran1" in out.split("there are:")[1].splitlines()[0], "")
    check("plot_cur is unchanged: the current plot is still ac1", re.search(r"^Current ac1", out, re.M) is not None, "")
    r3 = rows(out, "track3"); r4 = rows(out, "track4")          # the failed -analysis made no plot
    check("a descending dc sweep, -range 2 0 and 0 2 alike: one hit at v_sweep = 1 (E-584: the track "
          "plot spells the dc scale v_sweep, a name print can reach)",
          len(r3) == 1 and len(r4) == 1 and near(r3[0]["v_sweep"], 1.0, 1e-9) and r3 == r4
          and "v-sweep=" not in out, f"{r3} {r4}")

    print("[8] refusals and parsing")
    out = ngspice(deck(SINE, "tran 1u 5m\ntrack v(a) -spec v(a)==5\nsetplot\ntrack v(a) -spec localmax -which 9\n"
                             "track v(a) -spec localmax -bogus 1\ntrack v(a) -spec localmax -edge rise\n"
                             "track v(a) -spec v(a)==0.5 -at mid\ntrack v(a) -spec v(a)==0.5 -prominence 0.1\n"
                             "define hp(x) x - 0.5\ntrack v(a) -spec localmax(hp(v(a))) -range 0 1.5m\n"
                             "dc va 0 1 1\ntrack v(a) -spec localmax\ndc va 0 1 0.5 vb 0 1 0.5\ntrack v(a) -spec globalmax"))
    check("zero hits: `track failed!`, no track plot made", "no hit of v(a)==5" in out
          and "track1" not in out.split("List of plots")[1].split("\n\n")[0] if "List of plots" in out else False, "")
    check("-which 9 of 5 hits is refused", "-which 9 selects nothing: 5 hits" in out, "")
    check("an unknown option is refused", "unknown option '-bogus'" in out, "")
    check("-edge on a locator, -at on a crossing, -prominence on a crossing: three refusals",
          "-edge applies to a crossing spec" in out and "-at applies to a region spec" in out
          and "-prominence applies to a local extremum spec" in out, "")
    r = rows(out, "localmax(hp(v(a)))")
    check("`define hp(x) x - 0.5` composes inside the spec: the two maxima in 0..1.5 ms",
          len(r) == 2 and near(r[0]["time"], 0.25e-3, 1e-5) and near(r[1]["time"], 1.25e-3, 1e-5), f"{r}")
    check("a locator on a two-sample sweep is refused", "needs at least three samples" in out, "")
    check("a nested dc sweep is refused with the `sweep` pointer", "not monotonic (a nested sweep)" in out, "")
    n_fail = out.count("track failed!")
    check("every refusal ended in `track failed!`: 8 of them", n_fail == 8, f"{n_fail}")

    # ---- Enhancement-581: $track_plot / $track_hits for a per-trial loop
    print("[9] $track_plot and $track_hits")
    body = "V1 in 0 pulse(0 1 0 1n 1n 1m 2m)\nR1 in a {rr}\nL1 a out 1m\nC1 out 0 1u\n.param rr = agauss(20, 30, 3)\n"
    ctl = ("setseed 5\nlet n = 0\nlet npk = vector(6)\nrepeat 6\n  reset\n  tran 2u 1m\n  set tp = $curplot\n"
           "  track v(out) -spec localmax -prominence 0.4\n  echo trial $&n hits=$track_hits plot=$track_plot\n"
           "  if $track_hits gt 0\n    setplot $track_plot\n    let npk[n] = $track_hits\n    destroy $track_plot\n"
           "  else\n    let npk[n] = 0\n  end\n  destroy $tp\n  let n = n + 1\nend\nprint npk\n"
           "track v(out) -spec localmax\necho after-a-refusal hits=$track_hits plot=[$track_plot]\n")
    out = ngspice(deck(body, ctl))
    trials = re.findall(r"^trial (\d+) hits=(\d+) plot=(\S*)$", out, re.M)
    check("$track_hits and $track_plot follow every trial of a loop (6 trials reported)", len(trials) == 6, f"{len(trials)}")
    hit = [t for t in trials if int(t[1]) > 0]
    miss = [t for t in trials if int(t[1]) == 0]
    check("a trial with hits names the plot it made, one with none has an empty $track_plot and 0 hits",
          hit and all(t[2].startswith("track") for t in hit) and miss and all(t[2] == "" for t in miss),
          f"hits={len(hit)} misses={len(miss)}")
    check("the loop collected the counts through $track_hits, not by plot number",
          re.search(r"^Index\s+npk", out, re.M) is not None and "no such plot" not in out, "")
    check("a refusal after the loop clears both (no track plot exists after the destroys)",
          "after-a-refusal hits=0 plot=[]" in out, "")

    print("\nALL PASSED" if ok else "\nSOME FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
