#!/usr/bin/env python3
"""Enhancement-654: process corners declared on Verilog-A parameters --
`(* corner="ss=115, ff=-10%, sf=+3sigma" *)` -- and `.option corner=<name>`.

One string attribute names the parameter's position at each corner:
`name=value` entries separated by commas and/or whitespace; a value is a
real literal with an optional scale factor (an absolute value), a number
followed by `%` (a fraction of the nominal) or by `sigma` (a multiple of
the declared `std`/`std_rel`, through the transform a draw uses: lognormal,
truncation clamp, a uniform's half-width). Names fold to lower case. The
compiler exports the entries through OSDI_CORNER_{COUNTS,INFOS,NAMES};
ngspice's `.option corner=<name>` (or `set corner=<name>` between runs)
writes every cornered parameter's value through the ordinary setter on each
run, the first one included; a cornered parameter does not draw under
`.option osdimc`; a name no loaded model declares refuses the run.

Checks (per solver):
  [1]  `.option corner=ss` on the first run: absolute, percentage, sigma,
       lognormal+truncation (clamped), an instance parameter on every instance
  [2]  `ff`: its values; a parameter without an `ff` entry at nominal
  [3]  no option, `tt`, `nom`: nominal
  [4]  comma, whitespace and mixed separators declare the same corners
  [5]  scale factors in a value (2.2n, 1.5k, 1M, 1m)
  [6]  a sigma corner on a uniform: the half-width is the unit
  [7]  `set corner=` between runs switches; `tt` and `unset` (no deck option)
       restore nominal; `unset` under `.option corner=ss` returns to ss
  [8]  `.option osdimc` beside a corner: the cornered statistical parameter
       is pinned on every trial, an uncornered one draws
  [9]  `altermod` recentres a percentage corner; an absolute one is
       re-imposed at the next run
  [10] `showmod` prints the cornered value
  [11] `.option savemc` records the cornered parameters, a corner-only one too
  [12] a corner no loaded model declares: the error names the declared ones,
       the run is refused
  [13] a model type that lacks the corner: a note once, its parameters nominal
  [14] a deck with no Verilog-A device and `.option corner=ss` simply runs
  [15] `SS` selects `ss` (the deck is folded; `set corner=SS` folds too)
  [16] compile-time diagnostics: sigma without std, a malformed entry, case
       twins, a non-string value (errors); an integer parameter, a percentage
       of a zero default, a duplicate attribute, a localparam, a variable
       (warnings)
  [17] `osdimc_verbose` says each cornered write and how it was formed
  [18] a `montecarlo` loop under a corner: every sample row holds the
       cornered value, the uncornered one varies
  [19] Enhancement-657 (hunt F4): a corner on a parameter the model tests
       with `$param_given`, not given by the deck, is left at its nominal
       with a corner-worded note once (the compiler exports the E-555 gate
       in OSDI_CORNER_GATED); an untested one beside it moves
  [20] the same parameter given on the card moves to the corner, no note
  [21] statistics beside the corner: the note is the corner's, not the
       draw's; under `.option osdimc` the parameter neither moves nor draws
  [22] the `corners` loop: the gated parameter at its nominal in every row,
       the notes once
  [23] `altermod` makes it given: the corner then moves it
  [24] Enhancement-658 (hunt F1): under `.option osdimc` a nominal run and
       then `set corner=ss`: the FIRST cornered run has every cornered
       parameter at its corner, the corner-only ones included
  [25] the `corners` loop under `.option osdimc`: the `ss` row right
  [26] a `sweep` as the first cornered run under `.option osdimc`: its
       first point right
  [27] Enhancement-662 (hunt F3): a corner named `tt`, `nom` or `nominal`
       is refused at compile time -- those spellings select the nominal in
       ngspice and the entry could never be reached
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
WORK = tempfile.mkdtemp(prefix="vacorner_")
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
(* corner="ss=115, ff=88" *)                     parameter real rsh = 100 from (0:inf);
(* corner="ss=+10% ff=-10%" *)                  parameter real k   = 2.0;
(* std=0.02, corner="ss=+3sigma, ff=-3sigma" *)  parameter real vth = 0.45;
(* std_rel=0.1, dist="lognormal", trunc=2, corner="ss=+3sigma" *) parameter real tox = 2n from (0:inf);
(* type="instance", corner="ss=1.2k" *)         parameter real ri  = 1k;
analog I(p,n) <+ V(p,n)/(rsh*k) + V(p,n)*vth/ri + V(p,n)*tox*0;
endmodule
''',
    "cs": '''`include "disciplines.vams"
module cs(p, n);
inout p, n; electrical p, n;
(* std=5, corner="ss=+2sigma, ff=-2sigma" *) parameter real r = 100 from (0:inf);
(* std=1 *)                                 parameter real q = 10;
(* corner="fs=2" *)                          parameter real w = 1;
analog I(p,n) <+ V(p,n)/r + V(p,n)*q*0 + V(p,n)*w*0;
endmodule
''',
    "cu": '''`include "disciplines.vams"
module cu(p, n);
inout p, n; electrical p, n;
(* std=2, dist="uniform", corner="ss=+1sigma" *) parameter real u = 10;
(* corner="ss=2.2n, ff=1.5k, sf=1M, fs=1m" *)     parameter real sc = 1;
(* corner="ss=3, ff=4" *)                         parameter real a = 1;
(* corner="ss=3 ff=4" *)                          parameter real b = 1;
(* corner="ss=3,ff=4" *)                          parameter real c = 1;
(* corner="  ss=3 ,  ff=4 , " *)                  parameter real d = 1;
analog I(p,n) <+ V(p,n)*(u+sc+a+b+c+d)*0 + V(p,n);
endmodule
''',
    # Enhancement-657 (hunt F4): a corner on a $param_given-tested parameter
    "cg": '''`include "disciplines.vams"
module cg(p, n);
inout p, n; electrical p, n;
(* corner="ss=2, ff=0.5" *)  parameter real a = 1;   // corner only, tested
(* std=0.1, corner="ss=2" *) parameter real b = 1;   // statistics beside it, tested
(* corner="ss=3" *)          parameter real c = 1;   // untested
real ga, gb;
analog begin
  ga = $param_given(a) ? a : 10;
  gb = $param_given(b) ? b : 10;
  I(p,n) <+ V(p,n)*(ga + gb + c)*1e-3;
end
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

HEAD = ("* vacorner {tag}\n.control\npre_osdi cr.osdi\npre_osdi cs.osdi\npre_osdi cu.osdi\n.endc\n{opts}\n"
        "v1 in 0 dc 1\nn1 in 0 rm ri=1k\nn2 in 0 rm\nn3 in 0 sm\nn4 in 0 um\n"
        ".model rm cr rsh=100\n.model sm cs r=100\n.model um cu\n.control\n{body}\n.endc\n.end\n")


def run(body, tag, opts=""):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(HEAD.format(tag=tag, opts=opts, body=body))
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300, cwd=WORK)
    return p.returncode, p.stdout + p.stderr


def vals(out, name):
    """every printed value of `name`, in order"""
    return [float(m) for m in re.findall(re.escape(name) + r" = ([-+0-9.eE]+)", out)]


def val(out, name, k=0):
    v = vals(out, name)
    return v[k] if len(v) > k else None


def near(x, y, tol=1e-6):
    return x is not None and y is not None and abs(x - y) <= tol * max(1.0, abs(y))


RM = [A + "rm[rsh]", A + "rm[k]", A + "rm[vth]", A + "rm[tox]"]
PR = "print " + " ".join(RM) + f" {A}n1[ri] {A}n2[ri]"

# [1] ss on the first run
rc, out = run("op\n" + PR, "c1", ".option corner=ss")
exp = [115.0, 2.2, 0.51, 2e-9 * 2.718281828459045 ** 0.2]
got = [val(out, n) for n in RM]
check("[1] `.option corner=ss` on the first run: absolute 115, +10% 2.2, +3 sigma 0.51, lognormal +3 sigma clamped at 2, ri=1.2k on both instances",
      all(near(g, e) for g, e in zip(got, exp)) and near(val(out, A + "n1[ri]"), 1200) and near(val(out, A + "n2[ri]"), 1200),
      f"got {got} ri={val(out, A + 'n1[ri]')},{val(out, A + 'n2[ri]')}")

# [2] ff
rc, out = run("op\n" + PR, "c2", ".option corner=ff")
got = [val(out, n) for n in RM]
check("[2] `ff`: 88, 1.8, 0.39; tox and ri (no ff entry) at nominal",
      all(near(g, e) for g, e in zip(got, [88.0, 1.8, 0.39, 2e-9])) and near(val(out, A + "n1[ri]"), 1000), f"got {got}")

# [3] nominal spellings
res = []
for opts in ("", ".option corner=tt", ".option corner=nom"):
    rc, out = run("op\n" + PR, "c3" + str(len(res)), opts)
    res.append([val(out, n) for n in RM])
check("[3] no option, `tt`, `nom`: nominal", all(all(near(g, e) for g, e in zip(r, [100.0, 2.0, 0.45, 2e-9])) for r in res), f"{res}")

# [4] separators, [5] scale factors, [6] uniform
UM = [A + f"um[{n}]" for n in ("a", "b", "c", "d", "sc", "u")]
outs = {}
for cn in ("ss", "ff", "sf", "fs"):
    rc, outs[cn] = run("op\nprint " + " ".join(UM), "c4" + cn, f".option corner={cn}")
sep_ok = all(near(val(outs["ss"], A + f"um[{n}]"), 3) and near(val(outs["ff"], A + f"um[{n}]"), 4) for n in "abcd")
check("[4] comma, whitespace and mixed separators declare the same corners", sep_ok,
      " ".join(f"{n}:{val(outs['ss'], A + f'um[{n}]')}/{val(outs['ff'], A + f'um[{n}]')}" for n in "abcd"))
check("[5] scale factors in a value: 2.2n, 1.5k, 1M, 1m",
      near(val(outs["ss"], A + "um[sc]"), 2.2e-9) and near(val(outs["ff"], A + "um[sc]"), 1500)
      and near(val(outs["sf"], A + "um[sc]"), 1e6) and near(val(outs["fs"], A + "um[sc]"), 1e-3),
      " ".join(str(val(outs[c], A + "um[sc]")) for c in ("ss", "ff", "sf", "fs")))
check("[6] a sigma corner on a uniform: +1 sigma is one half-width (10 -> 12)", near(val(outs["ss"], A + "um[u]"), 12.0),
      str(val(outs["ss"], A + "um[u]")))

# [7] switching between runs
body = (f"set corner=ff\nop\nprint {A}rm[rsh]\nset corner=tt\nop\nprint {A}rm[rsh]\n"
        f"set corner=ff\nop\nprint {A}rm[rsh]\nunset corner\nop\nprint {A}rm[rsh]\n")
rc, out = run(body, "c7a")
seq = vals(out, A + "rm[rsh]")
rc, out2 = run(f"set corner=ff\nop\nprint {A}rm[rsh]\nunset corner\nop\nprint {A}rm[rsh]\n", "c7b", ".option corner=ss")
seq2 = vals(out2, A + "rm[rsh]")
check("[7] `set corner=` switches between runs; `tt` and `unset` restore nominal; `unset` under `.option corner=ss` returns to ss",
      seq == [88.0, 100.0, 88.0, 100.0] and seq2 == [88.0, 115.0], f"{seq} {seq2}")

# [8] corner + osdimc
body = f"set corner=ss\nop\nop\nop\nprint {A}sm[r]\nprint {A}sm[q]\n"
rc, out = run("op\nprint " + A + "sm[r] " + A + "sm[q]\n" * 1 + "op\nprint " + A + "sm[r] " + A + "sm[q]\n" + "op\nprint " + A + "sm[r] " + A + "sm[q]\n",
              "c8", ".option corner=ss osdimc mcseed=3")
rs, qs = vals(out, A + "sm[r]"), vals(out, A + "sm[q]")
check("[8] `.option osdimc` beside the corner: the cornered statistical parameter is pinned on every trial (110), the uncornered one draws",
      len(rs) == 3 and all(near(r, 110.0) for r in rs) and len(qs) == 3 and near(qs[0], 10.0) and any(not near(q, 10.0) for q in qs[1:]),
      f"r={rs} q={qs}")

# [9] altermod
body = (f"op\naltermod rm k=3\nop\nprint {A}rm[k]\naltermod rm rsh=200\nprint {A}rm[rsh]\nop\nprint {A}rm[rsh]\n")
rc, out = run(body, "c9", ".option corner=ss")
check("[9] `altermod` recentres a percentage corner (k=3 -> 3.3); an absolute one is re-imposed at the next run (200 -> 115)",
      near(val(out, A + "rm[k]"), 3.3) and vals(out, A + "rm[rsh]") == [200.0, 115.0],
      f"k={val(out, A + 'rm[k]')} rsh={vals(out, A + 'rm[rsh]')}")

# [10] showmod
rc, out = run("op\nshowmod rm : rsh k", "c10", ".option corner=ss")
check("[10] `showmod` prints the cornered value", re.search(r"rsh\s+115\b", out) is not None and re.search(r"\bk\s+2\.2\b", out) is not None,
      out[-200:].replace("\n", "|"))

# [11] savemc
rc, out = run("op\nop\n", "c11", ".option corner=ss savemc=c11.csv")
csv = open(os.path.join(WORK, "c11.csv")).read().splitlines() if os.path.exists(os.path.join(WORK, "c11.csv")) else []
hdr = csv[0].split(",") if csv else []
row = csv[1].split(",") if len(csv) > 1 else []
def col(name):
    return float(row[hdr.index(name)]) if name in hdr and len(row) == len(hdr) else None
check("[11] `.option savemc` records the cornered parameters, a corner-only one too",
      near(col(A + "rm[rsh]"), 115.0) and near(col(A + "sm[r]"), 110.0) and col(A + "sm[w]") is not None and near(col(A + "n1[ri]"), 1200.0),
      f"hdr={hdr[:6]}... row={row[:6]}")

# [12] unknown corner
rc, out = run("op\nprint v(in)\n", "c12", ".option corner=sss")
check("[12] a corner no loaded model declares: the error names the declared ones and the run is refused",
      "no loaded Verilog-A model declares a corner of that name" in out and "declared:" in out and "ss" in out.split("declared:")[1]
      and "the run is refused" in out and "aborted" in out and "v(in) =" not in out, out[-300:].replace("\n", "|"))

# [13] a model type lacking the corner
rc, out = run(f"op\nop\nprint {A}rm[rsh] {A}sm[w]\n", "c13", ".option corner=fs")
check("[13] a model type that lacks the corner: the note once, its parameters at nominal; the other type cornered",
      out.count("model 'cr' declares no corner of that name") == 1 and "declared: ss, ff" in out
      and near(val(out, A + "rm[rsh]"), 100.0) and near(val(out, A + "sm[w]"), 2.0), out[-300:].replace("\n", "|"))

# [14] a plain deck
with open(os.path.join(WORK, "plain.cir"), "w") as f:
    f.write("* plain\n.option corner=ss\nv1 a 0 1\nr1 a 0 1k\n.control\nop\nprint v(a)\n.endc\n.end\n")
p = subprocess.run([NGSPICE, "-b", os.path.join(WORK, "plain.cir")], capture_output=True, text=True, timeout=120, cwd=WORK)
o = p.stdout + p.stderr
check("[14] a deck with no Verilog-A device and `.option corner=ss` simply runs", p.returncode == 0 and "v(a) = 1" in o and "refused" not in o,
      o[-200:].replace("\n", "|"))

# [15] case
rc, out = run(f"op\nprint {A}rm[rsh]\nset corner=FF\nop\nprint {A}rm[rsh]\n", "c15", ".option corner=SS")
check("[15] `SS` selects `ss`, `set corner=FF` selects `ff`", vals(out, A + "rm[rsh]") == [115.0, 88.0], str(vals(out, A + "rm[rsh]")))

# [16] compile-time diagnostics
BAD = '''`include "disciplines.vams"
module bad(p, n);
inout p, n; electrical p, n;
(* corner="ss=+3sigma" *)          parameter real a = 1;
(* corner="ss=115 ff" *)           parameter real b = 1;
(* corner="ss=115, SS=120" *)      parameter real c = 1;
(* corner="ss=1x" *)               parameter real d = 1;
(* corner=115 *)                   parameter real f = 1;
(* corner="ss=2" *)                parameter integer g = 1;
(* corner="ss=+10%" *)             parameter real h = 0;
(* corner="ss=2", corner="ff=3" *) parameter real i = 1;
(* corner="ss=2" *)                localparam real j = 1;
(* corner="ss=2" *)                real v;
analog begin v = a+b+c+d+f+g+h+i+j; I(p,n) <+ V(p,n)*v; end
endmodule
'''
with open(os.path.join(WORK, "bad.va"), "w") as f:
    f.write(BAD)
r = subprocess.run([VAF, "bad.va", "-o", "bad.osdi"], capture_output=True, text=True, cwd=WORK)
o = r.stdout + r.stderr
want = ["corner 'ss' is given in sigmas, but this parameter declares no statistics",
        "corner entry 'ff' is malformed: an entry is <name>=<value>; there is no '='",
        "corners 'ss' and 'SS' are the same corner: names are folded to lower case",
        "corner entry 'ss=1x' is malformed: the value is not a number",
        "illegal expression supplied to 'corner' attribute; expected a string of name=value entries",
        "'corner' attribute is ignored: a corner needs a real parameter; this one is an integer",
        "corner 'ss' is a percentage of a default of 0",
        "'corner' is given 2 times on this parameter",
        "'corner' attribute is ignored: a localparam cannot be set by the simulator",
        "'corner' attribute is ignored here: statistics and corner attributes apply to parameters"]
missing = [w for w in want if w not in o]
check("[16] compile-time diagnostics: five errors, five warnings, each located and worded",
      r.returncode != 0 and not missing and o.count("error:") == 6 and o.count("warning:") == 5, f"missing={missing} errors={o.count('error:')} warnings={o.count('warning:')}")

# [17] verbose
rc, out = run("op\n", "c17", ".option corner=ss osdimc_verbose")
check("[17] `osdimc_verbose` says each cornered write and how it was formed",
      "corner ss: rm:rsh = 115 (nominal 100, absolute)" in out and "corner ss: rm:k = 2.2 (nominal 2, +10%)" in out
      and "corner ss: rm:vth = 0.51 (nominal 0.45, +3 sigma)" in out and "corner ss: n1:ri = 1200 (nominal 1000, absolute)" in out,
      out[-300:].replace("\n", "|"))

# [18] a montecarlo loop under a corner
rc, out = run("set corner=ss\nmontecarlo 4 -analysis op -spec v(in) -max 10 -seed 5\n", "c18", ".option osdimc savemc=c18.csv")
csv = open(os.path.join(WORK, "c18.csv")).read().splitlines() if os.path.exists(os.path.join(WORK, "c18.csv")) else []
hdr = csv[0].split(",") if csv else []
rows = [l.split(",") for l in csv[1:] if l.strip()]
def colv(r, name):
    return float(r[hdr.index(name)]) if name in hdr and len(r) == len(hdr) else None
rs = [colv(r, A + "sm[r]") for r in rows]
qs = [colv(r, A + "sm[q]") for r in rows]
check("[18] a `montecarlo` loop under a corner: every sample row holds the cornered value, the uncornered one varies",
      len(rows) >= 4 and all(near(r, 110.0) for r in rs) and len(set(qs)) > 1, f"rows={len(rows)} r={rs} q={qs}")

# Enhancement-657 (hunt F4): the E-555 gate on a corner
HEADG = ("* vacorner {tag}\n.control\npre_osdi cg.osdi\n.endc\n{opts}\n"
         "v1 in 0 dc 1\nn1 in 0 gm\n.model gm cg {card}\n.control\n{body}\n.endc\n.end\n")


def rung(body, tag, opts="", card=""):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(HEADG.format(tag=tag, opts=opts, body=body, card=card))
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300, cwd=WORK)
    return p.returncode, p.stdout + p.stderr


NOTE_A = "corner ss: gm:a is not given by the deck and the model tests $param_given(a): the corner's write would switch the model to its \"given\" branch instead of moving it -- left at its nominal. Give it on the card, or altermod it, for the corner to move it."
NOTE_B = NOTE_A.replace("gm:a", "gm:b").replace("(a)", "(b)")
PG = f"print i(v1) {A}gm[a] {A}gm[b] {A}gm[c]\n"

# [19] corner only, not given: nominal, the note once, the untested neighbour moves
rc, out = rung("op\n" + PG + "op\n" + PG, "c19", ".option corner=ss")
check("[19] a corner on a `$param_given`-tested parameter the deck never gave: left at 1 with the corner's note once (two runs); the untested `c` moves to 3; i = -(10+10+3) mA",
      vals(out, A + "gm[a]") == [1.0, 1.0] and vals(out, A + "gm[c]") == [3.0, 3.0] and all(near(i, -0.023) for i in vals(out, "i(v1)"))
      and out.count(NOTE_A) == 1 and "a draw would switch" not in out,
      f"a={vals(out, A + 'gm[a]')} c={vals(out, A + 'gm[c]')} i={vals(out, 'i(v1)')} notes={out.count(NOTE_A)}")

# [20] given on the card: the corner moves it, no note for it
rc, out = rung("op\n" + PG, "c20", ".option corner=ss", card="a=1")
check("[20] `a=1` on the card: the corner moves it to 2, no note for `a`; i = -(2+10+3) mA",
      val(out, A + "gm[a]") == 2.0 and near(val(out, "i(v1)"), -0.015) and "gm:a is not given" not in out,
      f"a={val(out, A + 'gm[a]')} i={val(out, 'i(v1)')}")

# [21] statistics beside the corner: the corner's note, not the draw's; under osdimc neither moved nor drawn
rc, out = rung("op\n" + PG, "c21", ".option corner=ss")
rc2, out2 = rung("op\n" + PG + "op\n" + PG + "op\n" + PG, "c21b", ".option corner=ss osdimc")
check("[21] `b` (std beside the corner, tested): the note is the corner's, once, not the draw's; under `.option osdimc` b stays 1 on three trials",
      out.count(NOTE_B) == 1 and "a draw would switch" not in out and val(out, A + "gm[b]") == 1.0
      and vals(out2, A + "gm[b]") == [1.0, 1.0, 1.0] and "a draw would switch" not in out2 and out2.count(NOTE_B) == 1,
      f"b={val(out, A + 'gm[b]')} notes={out.count(NOTE_B)} osdimc b={vals(out2, A + 'gm[b]')} draw_note={'a draw would switch' in out2}")

# [22] the corners loop
rc, out = rung(f"corners -output i=i(v1) a={A}gm[a] c={A}gm[c]\necho \"A: $&a C: $&c I: $&i\"\n", "c22")
check("[22] the `corners` loop (tt ss ff): `a` 1 in every row, `c` 1 3 1, i -21 -23 -21 mA; the notes once each",
      "A: 1 1 1 C: 1 3 1 I: -0.021 -0.023 -0.021" in out and out.count(NOTE_A) == 1 and out.count(NOTE_B) == 1,
      out[-260:].replace("\n", "|"))

# [23] altermod makes it given
rc, out = rung("altermod gm a=1\nset corner=ss\nop\n" + PG, "c23")
check("[23] `altermod gm a=1` then `set corner=ss`: given now, the corner moves it to 2; i = -15 mA",
      val(out, A + "gm[a]") == 2.0 and near(val(out, "i(v1)"), -0.015) and "gm:a is not given" not in out,
      f"a={val(out, A + 'gm[a]')} i={val(out, 'i(v1)')}")

# Enhancement-658 (hunt F1): a corner selected after a nominal run under osdimc
rc, out = run("op\nset corner=ss\nop\n" + PR + "\nop\n" + PR, "c24", ".option osdimc")
got = [vals(out, n) for n in RM] + [vals(out, A + "n1[ri]")]
check("[24] `.option osdimc`, a nominal `op`, then `set corner=ss`: the first cornered run has rsh 115, k 2.2, vth 0.51, ri 1200 (not only vth), and so does the second",
      got[0] == [115.0, 115.0] and got[1] == [2.2, 2.2] and all(near(v, 0.51) for v in got[2]) and len(got[2]) == 2 and got[4] == [1200.0, 1200.0],
      f"rsh={got[0]} k={got[1]} vth={got[2]} ri={got[4]}")

rc, out = run(f"corners -list tt ss ff -output rsh={A}rm[rsh] k={A}rm[k] ri={A}n1[ri]\necho \"A: $&rsh $&k $&ri\"\n", "c25", ".option osdimc")
check("[25] the `corners` loop under `.option osdimc`: tt 100/2/1000, ss 115/2.2/1200, ff 88/1.8/1000",
      "A: 100 115 88 2 2.2 1.8 1000 1200 1000" in out, out[-160:].replace("\n", "|"))

rc, out = run(f"op\nset corner=ss\nsweep v1 1 2 1 -analysis op -output rsh={A}rm[rsh] k={A}rm[k]\necho \"A: $&rsh $&k\"\n", "c26", ".option osdimc")
check("[26] a `sweep` as the first cornered run under `.option osdimc`: both points 115 and 2.2",
      "A: 115 115 2.2 2.2" in out, out[-160:].replace("\n", "|"))

# Enhancement-662 (hunt F3): the nominal's spellings as corner names
with open(os.path.join(WORK, "ctt.va"), "w") as f:
    f.write('''`include "disciplines.vams"
module ctt(p, n);
inout p, n; electrical p, n;
(* corner="tt=5, ss=7" *)      parameter real a = 1;
(* corner="Nominal=8, ff=9" *) parameter real b = 1;
(* corner="nom=6" *)           parameter real c = 1;
analog I(p,n) <+ V(p,n)*1e-3*(a+b+c);
endmodule
''')
r = subprocess.run([VAF, "ctt.va", "-o", "ctt.osdi"], capture_output=True, text=True, cwd=WORK)
o = r.stdout + r.stderr
check("[27] corners named `tt`, `Nominal` and `nom` are refused: three errors naming the nominal, each located in its attribute, the help naming the nominal rule",
      r.returncode != 0 and o.count("names the nominal: ngspice's `.option corner=tt` (`nom`, `nominal`) selects the nominal and never reaches this entry") == 3
      and "corner 'tt' names" in o and "corner 'Nominal' names" in o and "corner 'nom' names" in o
      and "the nominal needs no entry" in o and not os.path.exists(os.path.join(WORK, "ctt.osdi")),
      f"rc={r.returncode} errors={o.count('names the nominal')}")

print(f"\n{passed} of {checks} checks passed")
sys.exit(0 if passed == checks else 1)
