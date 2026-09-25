#!/usr/bin/env python3
"""Enhancement-656: `.option autocorner` -- a run-class command at every
process corner the loaded Verilog-A models declare (E-654), for decks that
hold no control script (a schematic's directive text).

With the option set, every run-class command -- `op`, `tran`, `ac`, `dc`,
..., the batch-mode `run` and the shared library's -- runs at the nominal
`tt` and then at every declared corner, as `set corner=<name>` and the
command would. The per-corner plots are kept, named with their corner, so
batch `.print`/`.plot` cards print each corner (E-602); and for each plot the
nominal run made a combined `autocorner<n>` plot is built and made current:
the nominal's vectors under their names, each corner's as `<name>_<corner>`
(`v(out_ss)`), resampled onto the nominal's scale. $autocorner_plot,
$autocorner_plots, $autocorner_names, $autocorner_n describe the run; a
plain run clears them. The option does not apply inside a loop command
(sweep, montecarlo, corners, optimize, wcd, highsigma), to `resume`, or
without a declared corner.

Checks (per solver):
  [1]  `op` under the option: the banner; the combined plot's v(out),
       v(out_ss), v(out_ff) equal the values `set corner=` runs give
  [2]  the per-corner plots are kept and named; the result variables
  [3]  an op plot's first vector and the branch currents have corner copies
  [4]  `tran`: one `time` scale, every corner's waveform on it, the corner's
       own plot agreeing at the end
  [5]  `ac`: the complex `frequency` scale kept, complex corner vectors
  [6]  batch mode: `.op` and `.print op` print every corner
  [7]  the `corner` variable is put back (a deck corner holds; none stays none)
  [8]  inside `corners`, `montecarlo`, `sweep` and `optimize` the option is
       inert
  [9]  a corner whose run fails: said, no phantom vectors, the others intact
  [10] no declared corner: a single run, no variables
  [11] `unset autocorner`: a single run, the stale variables cleared
  [12] a batch `run` under `.option savemc` tags its rows tt, ss, ff
  [13] the `run` command loops too (the shared library's path)
  [14] the combined vectors keep their type (a voltage stays a voltage)
  [15] Enhancement-663 (hunt F7): `.option autocorner` takes priority over
       `.option osdimc`: the option is disabled for the corner pass, said once
       per circuit, and the copies are deterministic (vth 0.45 at tt on the
       second run too, where it drew before)
  [16] Enhancement-666 (hunt F8): a raw-file `run <file>` puts every corner's
       plot in the file, each named with its corner, and `load` reads them
       all; no "made no plot" per corner; ascii and binary
  [17] Enhancement-666: `meas tran` (`ac`, `dc`) reads the combined plot as
       its nominal's analysis -- v(out_ss) at 200u equals the ss plot's own
  [18] Enhancement-666: `writemc` on the combined plot puts each value on
       every corner's row, evaluated on that corner's own plot; a `_ss` name
       is refused with the hint
  [19] Enhancement-666: the copies keep their accessor readable -- `i(v1_ss)`
       (the banner's own example), `v1_ss#branch`, a bare `@rm_ss[rsh]` in
       `print` and `let`
  [20] Enhancement-666: the devices follow the `corner` variable when the
       loop ends -- the nominal after the pass (`showmod`), the deck's corner
       when one holds, and after the `corners` command too
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import NG as NGSPICE, VAF  # noqa: E402
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # noqa: E402

checks = passed = 0
WORK = tempfile.mkdtemp(prefix="autocorner_")
A = "@"


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))
    return ok


MODELS = {
    "cr": '''`include "disciplines.vams"
module cr(p, n);
inout p, n; electrical p, n;
(* corner="ss=115, ff=88" *)     parameter real rsh = 100 from (0:inf);
(* corner="ss=+10% ff=-10%" *)  parameter real k   = 2.0;
analog I(p,n) <+ V(p,n)/(rsh*k);
endmodule
''',
    "cf": '''`include "disciplines.vams"
module cf(p, n);
inout p, n; electrical p, n;
(* corner="bad=-1, ss=2" *) parameter real g = 1 from (0:inf);
analog I(p,n) <+ V(p,n)*g*1e-3;
endmodule
''',
    "cn": '''`include "disciplines.vams"
module cn(p, n);
inout p, n; electrical p, n;
(* std=1 *) parameter real z = 1;
analog I(p,n) <+ V(p,n)*z*1e-3;
endmodule
''',
    # Enhancement-663 (hunt F7): a cornered parameter beside an uncornered statistical one
    "cq": '''`include "disciplines.vams"
module cq(p, n);
inout p, n; electrical p, n;
(* corner="ss=2" *) parameter real w = 1;
(* std=1 *)         parameter real q = 10;
analog I(p,n) <+ V(p,n)*w*1e-3 + V(p,n)*q*0;
endmodule
''',
}
for name, src in MODELS.items():
    with open(os.path.join(WORK, name + ".va"), "w") as f:
        f.write(src)
    r = subprocess.run([VAF, name + ".va", "-o", name + ".osdi"], capture_output=True, text=True, cwd=WORK)
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)

HEAD = ("* autocorner {tag}\n.control\npre_osdi cr.osdi\n.endc\n{opts}\n"
        "v1 in 0 dc 1 ac 1\nn1 in out rm\nc1 out 0 1u\nr2 out 0 1k\n.model rm cr rsh=100\n{cards}\n"
        ".control\n{body}\n.endc\n.end\n")


def run(body, tag, opts=".option autocorner", cards="", head=HEAD):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(head.format(tag=tag, opts=opts, cards=cards, body=body))
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=600, cwd=WORK)
    return p.returncode, p.stdout + p.stderr


def vals(out, name):
    return [float(m) for m in re.findall(re.escape(name) + r" = ([-+0-9.eE]+)", out)]


def val(out, name, k=0):
    v = vals(out, name)
    return v[k] if len(v) > k else None


def near(x, y, tol=1e-6):
    return x is not None and y is not None and abs(x - y) <= tol * max(1.0, abs(y))


# [1] op: the combined plot equals the set corner= runs
rc, out = run("op\nprint v(out) v(out_ss) v(out_ff)\nunset autocorner\nset corner=ss\nop\nprint v(out)\nset corner=ff\nop\nprint v(out)\n", "a1")
c = [val(out, "v(out)", 0), val(out, "v(out_ss)"), val(out, "v(out_ff)")]
ref = [val(out, "v(out)", 1), val(out, "v(out)", 2)]
check("[1] `op` under the option: the banner; v(out), v(out_ss), v(out_ff) of the combined plot equal what `set corner=` runs give",
      "autocorner: op at 3 corners (tt ss ff)" in out and "into 'autocorner1' (now current)" in out
      and near(c[1], ref[0]) and near(c[2], ref[1]) and c[0] is not None and not near(c[0], c[1]), f"combined={c} ref={ref}")

# [2] per-corner plots kept and named; variables
rc, out = run("op\nsetplot\necho \"plot=$autocorner_plot plots=$autocorner_plots names=$autocorner_names n=$autocorner_n\"\n", "a2")
check("[2] the per-corner plots are kept and named with their corner; the result variables",
      "Operating Point (corner ss)" in out and "Operating Point (corner ff)" in out and "Operating Point (corner tt)" in out
      and "plot=autocorner1 plots=op1 op2 op3 names=tt ss ff n=3" in out, out[-300:].replace("\n", "|"))

# [3] op: the first vector and the branch currents have copies
rc, out = run("op\nprint in in_ss in_ff v1#branch v1_ss#branch\n", "a3")
check("[3] an op plot's first vector and the branch currents have corner copies (`v1_ss#branch` since E-666)",
      near(val(out, "in_ss"), 1.0) and near(val(out, "in_ff"), 1.0) and val(out, "v1_ss#branch") is not None
      and not near(val(out, "v1_ss#branch"), val(out, "v1#branch")), out[-200:].replace("\n", "|"))

# [4] tran: one scale, resampled; the corner's own plot agrees at the end
rc, out = run("tran 5u 400u\nprint length(time) length(v(out)) length(out_ss) length(out_ff)\n"
              "let n=length(time)-1\nprint v(out_ss)[n]\nsetplot tran2\nlet m=length(time)-1\nprint v(out)[m]\n", "a4")
lens = [val(out, "length(time)"), val(out, "length(v(out))"), val(out, "length(out_ss)"), val(out, "length(out_ff)")]
end_c = val(out, "v(out_ss)[n]")
end_p = val(out, "v(out)[m]")
check("[4] `tran`: one `time` scale carries every corner's waveform (equal lengths); the corner's own plot agrees at the end",
      "autocorner: tran at 3 corners" in out and "resampled onto time" in out and None not in lens and len(set(lens)) == 1
      and near(end_c, end_p, 1e-3), f"lens={lens} end={end_c} vs {end_p}")

# [5] ac: complex scale kept
rc, out = run("ac dec 2 1 1k\nprint vp(out_ss)[6] vm(out_ff)[0]\nsetplot ac2\nprint vp(out)[6]\nsetplot ac3\nprint vm(out)[0]\n", "a5")
check("[5] `ac`: the complex `frequency` scale is kept and the corner vectors are complex",
      "resampled onto frequency" in out and near(val(out, "vp(out_ss)[6]"), val(out, "vp(out)[6]"))
      and near(val(out, "vm(out_ff)[0]"), val(out, "vm(out)[0]")), out[-300:].replace("\n", "|"))

# [6] batch mode .op + .print
HEADB = ("* autocorner {tag}\n.control\npre_osdi cr.osdi\n.endc\n{opts}\nv1 in 0 dc 1\nn1 in out rm\nr2 out 0 1k\n.model rm cr rsh=100\n"
         ".op\n.print op v(out) {A}rm[rsh]\n.end\n").replace("{A}", A)
rc, out = run("", "a6", head=HEADB + "{cards}{body}")
blocks = re.findall(r"Operating Point \(corner (\w+)\).*?\n0\s+(\S+)\s+(\S+)", out, re.S)
check("[6] batch mode: `.op` and `.print op` print every corner",
      "autocorner: run at 3 corners" in out and sorted(b[0] for b in blocks) == ["ff", "ss", "tt"]
      and {b[0]: round(float(b[2])) for b in blocks} == {"tt": 100, "ss": 115, "ff": 88}, f"blocks={blocks}")

# [7] the corner variable is put back
rc, out = run("op\necho \"var=$corner\"\n", "a7a", ".option autocorner corner=ff")
rc2, out2 = run("op\necho \"set=$?corner\"\n", "a7b")
check("[7] the `corner` variable is put back: a deck corner holds, none stays none", "var=ff" in out and "set=0" in out2,
      out[-100:].replace("\n", "|") + out2[-100:].replace("\n", "|"))

# [8] inert inside loop commands
rc, out = run("corners -list tt ss -output v(out)\nmontecarlo 2 -analysis op -spec v(out) -max 2 -seed 3\n"
              f"sweep {A}r2[r] list 1k 2k -output v(out)\n"
              "optimize -dparam r2:r 1k 500 2k -analysis op -minimize v(out) -maxiter 2\nop\n", "a8", ".option autocorner osdimc")
check("[8] inside `corners`, `montecarlo`, `sweep` and `optimize` the option is inert (one loop, the plain `op` at the end)",
      out.count("autocorner:") == 2 and out.count("autocorner: op at 3 corners") == 1, f"banners={out.count('autocorner:')}")

# [9] a failing corner
HEADF = ("* autocorner {tag}\n.control\npre_osdi cr.osdi\npre_osdi cf.osdi\n.endc\n{opts}\nv1 in 0 dc 1\nn1 in out rm\nn2 out 0 fm\n"
         "r2 out 0 1k\n.model rm cr rsh=100\n.model fm cf\n{cards}\n.control\n{body}\n.endc\n.end\n")
rc, out = run("op\nprint v(out) v(out_ss)\nprint v(out_bad)\necho \"plots=$autocorner_plots names=$autocorner_names\"\n", "a9", head=HEADF)
check("[9] a corner whose run fails: said (`the run failed` since E-666), no phantom vectors, the other corners intact",
      "autocorner: corner bad: the run failed" in out and val(out, "v(out_ss)") is not None and val(out, "v(out_bad)") is None
      and "plots=op1 op2 op3 names=tt ss ff bad" in out, out[-300:].replace("\n", "|"))

# [10] no corners declared
HEADN = ("* autocorner {tag}\n.control\npre_osdi cn.osdi\n.endc\n{opts}\nv1 in 0 dc 1\nn1 in 0 nm\n.model nm cn\n{cards}\n.control\n{body}\n.endc\n.end\n")
rc, out = run("op\nprint v(in)\necho \"set=$?autocorner_n\"\n", "a10", head=HEADN)
check("[10] no declared corner: a single run, no banner, no variables", "autocorner:" not in out and "v(in) = 1" in out and "set=0" in out,
      out[-200:].replace("\n", "|"))

# [11] unset: single run, variables cleared
rc, out = run("op\nunset autocorner\nop\necho \"set=$?autocorner_n\"\n", "a11")
check("[11] `unset autocorner`: a single run afterwards, and the stale variables are cleared",
      out.count("autocorner: op at") == 1 and "set=0" in out, out[-200:].replace("\n", "|"))

# [12] savemc rows tagged
rc, out = run("", "a12", head=HEADB.replace("{opts}", ".option autocorner savemc=a12.csv") + "{cards}{body}")
csv = open(os.path.join(WORK, "a12.csv")).read().splitlines() if os.path.exists(os.path.join(WORK, "a12.csv")) else []
hdr = csv[0].split(",") if csv else []
tags = [l.split(",")[3] for l in csv[1:] if l.strip()] if len(hdr) > 3 else []
check("[12] a batch `run` under `.option savemc` tags its rows tt, ss, ff", hdr[:4] == ["trial", "analysis", "status", "corner"] and tags == ["tt", "ss", "ff"],
      f"hdr={hdr[:4]} tags={tags}")

# [13] the run command
rc, out = run("run\nprint v(out_ss)\n", "a13", cards=".op")
check("[13] the `run` command loops too", "autocorner: run at 3 corners" in out and val(out, "v(out_ss)") is not None, out[-200:].replace("\n", "|"))

# [14] types kept
rc, out = run("op\ndisplay\n", "a14")
m = re.search(r"^\s*out_ss\s*:\s*(\w+)", out, re.M)
check("[14] the combined vectors keep their type (a voltage stays a voltage)", m is not None and m.group(1) == "voltage", m.group(0) if m else out[-200:].replace("\n", "|"))

# Enhancement-663 (hunt F7): autocorner takes priority over the automatic Monte Carlo
HEADQ = ("* autocorner {tag}\n.control\npre_osdi cq.osdi\n.endc\n{opts}\nv1 in 0 dc 1\nn1 in 0 qm\n.model qm cq\n{cards}\n.control\n{body}\n.endc\n.end\n")
rc, out = run(f"save {A}qm[q] {A}qm[w]\nop\nop\nsetplot autocorner2\nprint {A}qm[q] {A}qm_ss[q] {A}qm_ss[w]\n", "a15",
              ".option autocorner osdimc mcseed=3", head=HEADQ)
check("[15] `.option autocorner osdimc`: the warning once for two runs; q 10 at tt and at ss on the second pass (a draw before), w 2 at ss",
      out.count("Warning: .option autocorner takes priority over .option osdimc (automc)") == 1
      and near(val(out, A + 'qm[q]'), 10.0) and near(val(out, A + 'qm_ss[q]'), 10.0) and near(val(out, A + 'qm_ss[w]'), 2.0),
      f"warnings={out.count('takes priority')} " + out[-200:].replace("\n", "|"))

# Enhancement-666 (hunt F8): the autocorner follow-on gaps
# [16] a raw-file run: every corner's plot in the file, named, loadable
for fmt, ftag in (("binary", "a16b"), ("ascii", "a16a")):
    raw = os.path.join(WORK, ftag + ".raw")
    rc, out = run(f"set filetype={fmt}\nrun {ftag}.raw\nload {ftag}.raw\nsetplot\nsetplot tran3\nprint v(out)[10]\n"
                  f"setplot tran2\nprint v(out)[10]\nsetplot tran1\nprint v(out)[10]\necho n=$autocorner_n names=$autocorner_names\n",
                  ftag, cards=".tran 5u 100u")
    with open(raw, "rb") as f:
        names = [l.decode(errors="replace").strip() for l in f.read().split(b"\n") if l.startswith(b"Plotname:")]
    v = vals(out, "v(out)[10]")
    check(f"[16] a {fmt} raw-file `run`: three plots in the file, each named with its corner, `load` reads them all; no 'made no plot'",
          names == ["Plotname: Transient Analysis (corner tt)", "Plotname: Transient Analysis (corner ss)", "Plotname: Transient Analysis (corner ff)"]
          and "(appended)" in out and "into '" + ftag + ".raw'" in out and "made no plot" not in out
          and len(v) == 3 and len(set(round(x, 6) for x in v)) == 3 and "n=3 names=tt ss ff" in out,
          f"names={names} v={v} " + out[-200:].replace("\n", "|"))

# [17] meas on the combined plot
rc, out = run("tran 5u 400u\nmeas tran a find v(out_ss) at=200u\nmeas tran b find v(out_ff) at=200u\nsetplot tran2\nmeas tran c find v(out) at=200u\n"
              "setplot tran3\nmeas tran d find v(out) at=200u\nac dec 5 1 1meg\nmeas ac e max vdb(out_ss)\ndc v1 0 1 0.5\nmeas dc f find v(out_ff) at=1\n", "a17")
def meas(out, name):
    m = re.search(r"^\s*" + re.escape(name) + r"\s+=\s+([-+0-9.eE]+)", out, re.M)
    return float(m.group(1)) if m else None
mv = {k: meas(out, k) for k in "abcdef"}
check("[17] `meas tran` (`ac`, `dc`) reads the combined plot as its nominal's analysis: v(out_ss) at 200u equals the ss plot's own",
      near(mv["a"], mv["c"]) and near(mv["b"], mv["d"]) and mv["a"] is not None and not near(mv["a"], mv["b"])
      and mv["e"] is not None and near(mv["f"], 0.86326, 1e-4) and "not a tran analysis" not in out, f"{mv}")

# [18] writemc on the combined plot: each corner's row
rc, out = run("op\nwritemc y=v(out)\nwritemc y2=v(out_ss)\n", "a18", ".option autocorner savemc=a18.csv")
csv = open(os.path.join(WORK, "a18.csv")).read().splitlines() if os.path.exists(os.path.join(WORK, "a18.csv")) else []
hdr = csv[0].split(",") if csv else []
ys = [float(l.split(",")[hdr.index("y")]) for l in csv[1:] if l.strip()] if "y" in hdr else []
check("[18] `writemc` on the combined plot puts each value on every corner's row, evaluated on that corner's own plot; a `_ss` name gets the hint",
      "is the corner pass's combined plot" in out and len(ys) == 3 and near(ys[0], 0.833333, 1e-4) and near(ys[1], 0.798085, 1e-4)
      and near(ys[2], 0.863260, 1e-4) and "y2" not in hdr and "plain names (v(out), not v(out_<corner>))" in out,
      f"hdr={hdr} ys={ys} " + out[-200:].replace("\n", "|"))

# [19] the copies' names keep their accessor readable
rc, out = run(f"save all {A}rm[rsh]\nop\nprint {A}rm_ss[rsh] i(v1_ss) v1_ss#branch\nlet z={A}rm_ff[rsh]*2\nprint z\n", "a19")
check("[19] the copies keep their accessor readable: `i(v1_ss)`, `v1_ss#branch`, a bare `@rm_ss[rsh]` in `print` and in `let`",
      near(val(out, A + "rm_ss[rsh]"), 115.0) and near(val(out, "i(v1_ss)"), -7.98085e-4, 1e-4) and near(val(out, "v1_ss#branch"), -7.98085e-4, 1e-4)
      and near(val(out, "z"), 176.0) and "not available" not in out and "invalid" not in out, out[-250:].replace("\n", "|"))

# [20] the devices follow the corner variable when the loop ends
rc, out = run("op\nshowmod rm\nset corner=ss\nop\nshowmod rm\nunset corner\nunset autocorner\ncorners -output r=@rm[rsh]\nshowmod rm\n", "a20")
rsh = [float(m) for m in re.findall(r"^\s*rsh\s+([-+0-9.eE]+)", out, re.M)]
check("[20] the devices follow the `corner` variable when the loop ends: nominal after the pass, the deck's corner when one holds, nominal after `corners`",
      rsh == [100.0, 115.0, 100.0], f"rsh={rsh}")

# [16] Enhancement-724 (five-options dig F8): batch `.meas` cards under the
# option ran once per corner and printed each corner's values in turn with
# nothing to tell them apart; the corner is named once before each run's
# first result.
HEADM = ("* autocorner {tag}\n.control\npre_osdi cr.osdi\n.endc\n{opts}\nv1 in 0 dc 1\nn1 in out rm\nr2 out 0 1k\n.model rm cr rsh=100\n"
         ".tran 1u 5u\n.meas tran vend find v(out) at=5u\n.meas tran vmax max v(out)\n.end\n")
rc, out = run("", "a16", head=HEADM + "{cards}{body}")
hdrs = re.findall(r"autocorner: measures at corner (\w+)", out)
vend = re.findall(r"^vend\s*=\s*([-+0-9.eE]+)", out, re.M)
check("[16] batch `.meas` cards under the option name their corner: one header per run (tt, ss, ff), each before its own values (E-724)",
      hdrs == ["tt", "ss", "ff"] and len(vend) == 3 and len(set(vend)) == 3
      and out.index("measures at corner tt") < out.index(vend[0]) < out.index("measures at corner ss") < out.index(vend[1])
      < out.index("measures at corner ff") < out.index(vend[2]) and out.count("measures at corner") == 3,
      f"headers={hdrs} vend={vend}")
rc, out = run("", "a16b", head=HEADM.replace("{opts}", "") + "{cards}{body}")
check("[16] ...and a plain batch run prints no header", "measures at corner" not in out and len(re.findall(r"^vend\s*=", out, re.M)) == 1, out[-120:].replace("\n", "|"))

# [21] Enhancement-725 (five-options dig F3): `.option saveused` beside the
# option. A block that read only a corner copy -- `print v(out_ss)` -- had
# `out_ss` saved, a name no analysis produces; the set matched nothing and
# every run of the pass was refused ("no data saved for D.C. Operating point
# analysis; analysis not run", three times). A name ending in `_<corner>` for
# a declared corner now also saves its base, so the copy exists.
rc, out = run("op\nprint v(out_ss)\ndisplay\n", "a21", opts=".option autocorner saveused")
check("[21] `.option saveused` beside autocorner: `print v(out_ss)` alone runs the pass and prints the ss value",
      near(val(out, "v(out_ss)"), 0.798085, 1e-5) and "analysis not run" not in out
      and re.search(r"(?m)^\s+out_ss\s+:", out) is not None, out[-200:].replace("\n", "|"))
check("[21] ...and only `out` was kept of the circuit (the option still prunes: no `in`)",
      re.search(r"(?m)^\s+in\s+:", out) is None and re.search(r"(?m)^\s+out\s+:", out) is not None,
      out[-300:].replace("\n", "|"))
rc, out = run(f"op\nprint i(v1_ff) v1_ss#branch {A}rm_ss[rsh]\nlet z = out_ff*2\nprint z\ndisplay\n", "a21b", opts=".option autocorner saveused")
check("[21] the other spellings of a copy: `i(v1_ff)`, `v1_ss#branch`, `@rm_ss[rsh]`, a bare `out_ff` in a `let`",
      near(val(out, "i(v1_ff)"), -8.63260e-4, 1e-4) and near(val(out, "v1_ss#branch"), -7.98085e-4, 1e-4)
      and near(val(out, A + "rm_ss[rsh]"), 115.0) and near(val(out, "z"), 2 * 0.863260, 1e-5)
      and "not available" not in out and "invalid" not in out and "stay empty" not in out,
      out[-300:].replace("\n", "|"))

print(f"\n{passed} of {checks} checks passed")
sys.exit(0 if passed == checks else 1)
