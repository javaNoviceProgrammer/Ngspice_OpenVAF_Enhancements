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
rc, out = run("op\nprint in in_ss in_ff v1#branch v1#branch_ss\n", "a3")
check("[3] an op plot's first vector and the branch currents have corner copies",
      near(val(out, "in_ss"), 1.0) and near(val(out, "in_ff"), 1.0) and val(out, "v1#branch_ss") is not None
      and not near(val(out, "v1#branch_ss"), val(out, "v1#branch")), out[-200:].replace("\n", "|"))

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
check("[9] a corner whose run fails: said, no phantom vectors, the other corners intact",
      "autocorner: corner bad: the run made no plot" in out and val(out, "v(out_ss)") is not None and val(out, "v(out_bad)") is None
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
rc, out = run(f"save {A}qm[q] {A}qm[w]\nop\nop\nsetplot autocorner2\nprint \"{A}qm[q]\" \"{A}qm[q]_ss\" \"{A}qm[w]_ss\"\n", "a15",
              ".option autocorner osdimc mcseed=3", head=HEADQ)
check("[15] `.option autocorner osdimc`: the warning once for two runs; q 10 at tt and at ss on the second pass (a draw before), w 2 at ss",
      out.count("Warning: .option autocorner takes priority over .option osdimc (automc)") == 1
      and near(val(out, '"' + A + 'qm[q]"'), 10.0) and near(val(out, '"' + A + 'qm[q]_ss"'), 10.0) and near(val(out, '"' + A + 'qm[w]_ss"'), 2.0),
      f"warnings={out.count('takes priority')} " + out[-200:].replace("\n", "|"))

print(f"\n{passed} of {checks} checks passed")
sys.exit(0 if passed == checks else 1)
