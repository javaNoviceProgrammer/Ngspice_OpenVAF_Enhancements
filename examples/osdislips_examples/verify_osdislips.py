#!/usr/bin/env python3
"""Enhancement-796..810: the smaller slips D1..D17 of the ngspice + OSDI hunt of
2026-10-08 (docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-
outputs.md), each pinned end-to-end through ngspice (and openvaf-r for the
models).

  [1] E-796 (D1): `altermod`/`alter` of an integer parameter rounded 3.7 to 4
      without a word (the card warns), rounded -2.5 to -2 (the card gives -3,
      E-399) and stored 1e300 or 3e9 as 2147483647 (the card refuses, E-509).
  [2] E-797 (D2): `.save @n1[opvar]` warned "'iop' has no value yet" at every
      load -- about a correct deck; a built-in's `.save @r1[i]` never did.
  [3] E-798 (D3): `print` of a string parameter died in vec_get ("can not
      handle string value"); it prints the text now, and an expression that
      meets one is told what it is.
  [4] E-799 (D4): an out-of-range value on a paramset member (`altermod rsm
      l=20` after the netlist bound n1 to member rs, l in [1:10)) is followed
      by the member line E-668 gave only for a corner: the sibling that
      accepts it, and that a member is chosen when the netlist is read.
  [5] E-800 (D5): `.temp 0 27 50` was "Could not set temperature to 0 27 50"
      and ran at 27 C; it runs at the first listed temperature and says how
      to run them all.
  [6] D6, kept: `@(timer(0, ...))` fires once at t = 0 in an equilibrium
      analysis (op, a dc sweep's first point) -- the state the transient
      starts from -- and a timer starting later never fires there.
  [7] E-801 (D7): `pz 1 0 1 0 pol` (no `vol`/`cur`) was "no such parameter on
      this device or parameter is missing"; each missing or wrong keyword is
      named now, with the syntax.
  [8] E-802 (D8): a batch run whose .control block ran the analyses printed
      every .meas result twice (the closing `run` re-measured, or re-ran a
      deck already run); and a .meas card's result is a vector now, as the
      `meas` command's is.
  [9] E-803 (D9): `osdi` alone lists the loaded libraries and their modules
      ("too few args"); an unknown option is refused (`-l` was read as a
      file); `-f` or `-va` with no file says so (it was silent).
 [10] E-804 (D10): a parameter set twice on a .model card names the winner,
      the last -- and an instance-parameter default repeated on a card now
      keeps its last value too (the first used to win).
 [11] E-805 (D11): too many nodes on an OSDI line names the model's terminals
      and the nodes left over.
 [12] E-806 (D12): a Verilog-A child's internal node answers to `n1#c1.mid`
      (flattened `n1#c1__mid`) in print, .save, .meas, .ic and .nodeset; a
      vector holding a subcircuit instance answers to E-410's short form
      (`onoise_x1.n1_thermal`).
 [13] E-807 (D13): `altermod nch g=7m` reaches every bin nch.1, nch.2 (it was
      "no such device or model name nch").
 [14] E-808 (D14, D15): the currents `.options savecurrents` adds are left out
      of ac, sp and noise plots (0 long for a built-in, the bias for an OSDI
      device or in noise), with a note; op, dc and tran keep them. E-835: an
      OSDI device's, in ac and sp, is its small-signal current, and is kept.
 [15] E-809 (D16): an interval measurement whose TO is past the end of the
      data says the window was cut.
 [16] E-810 (D17): a saved OSDI parameter or opvar is typed by its declared
      units (power, impedance, ...; notype for none), not by its name.
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
WORK = tempfile.mkdtemp(prefix="osdislips_")
HDR = '`include "disciplines.vams"\n'

MODELS = {
    # [1] integer parameters
    "ip": """module ip(a, b);
inout a, b; electrical a, b;
parameter integer n = 2;
(* type="instance" *) parameter integer k = 1;
analog I(a,b) <+ 1e-3*n*k*V(a,b);
endmodule
""",
    # [2] opvars
    "ov": """module ov(a, b);
inout a, b; electrical a, b;
parameter real r = 1k;
(* desc="current", units="A" *) real iop;
(* desc="power" *) real pw;
analog begin
  iop = V(a,b)/r;
  pw = iop*V(a,b);
  I(a,b) <+ iop;
end
endmodule
""",
    # [3] string parameters
    "t3": """module t3(a, b);
inout a, b; electrical a, b;
parameter string mode = "lin";
(* type="instance" *) parameter string imode = "fast";
analog I(a,b) <+ V(a,b)/1k;
endmodule
""",
    "s1": """module s1(a, b);
inout a, b; electrical a, b;
parameter string only = "x";
analog I(a,b) <+ V(a,b)/1k;
endmodule
""",
    # [4] a paramset family, and a plain ranged parameter
    "rb": """module rb(a, b);
inout a, b; electrical a, b;
parameter real r = 1k;
analog I(a,b) <+ V(a,b)/r;
endmodule
paramset rs rb;
  parameter real l = 1 from [1:10);
  .r = 100*l;
endparamset
paramset rs rb;
  parameter real l = 10 from [10:100];
  .r = 1000*l;
endparamset
""",
    "rg": """module rg(a, b);
inout a, b; electrical a, b;
(* type="instance" *) parameter real l = 1 from [1:10);
analog I(a,b) <+ V(a,b)/(100*l);
endmodule
""",
    # [6] timers
    "tm": """module tm(a, b);
inout a, b; electrical a, b;
integer n;
analog begin
  @(initial_step) n = 0;
  @(timer(0, 1u)) begin n = n + 1; $strobe("TIMER n=%0d t=%g", n, $abstime); end
  @(timer(2.5u)) $strobe("ONESHOT t=%g", $abstime);
  I(a,b) <+ V(a,b)/1k;
end
endmodule
""",
    # [11] a two-terminal model
    "gr": """module gr(a, b);
inout a, b; electrical a, b;
parameter real g = 1e-3;
analog I(a,b) <+ g*V(a,b);
endmodule
""",
    # [12] a Verilog-A hierarchy, and a noisy resistor
    "par": """module child(a, b);
inout a, b; electrical a, b; electrical mid;
analog begin I(a,mid) <+ V(a,mid)/1k; I(mid,b) <+ V(mid,b)/1k + ddt(1n*V(mid,b)); end
endmodule
module gc(a, b);
inout a, b; electrical a, b;
child k1(a, b);
endmodule
module par(p, n);
inout p, n; electrical p, n;
child c1(p, n);
gc g1(p, n);
endmodule
""",
    "nr": """module nr(a, b);
inout a, b; electrical a, b;
parameter real r = 1k;
analog begin
  I(a,b) <+ V(a,b)/r;
  I(a,b) <+ white_noise(4*1.380649e-23*$temperature/r, "thermal");
end
endmodule
""",
    # [13] binned cards
    "bm": """module bm(a, b);
inout a, b; electrical a, b;
parameter real g = 1e-3;
parameter real lmin = 0; parameter real lmax = 1;
parameter real wmin = 0; parameter real wmax = 1;
(* type="instance" *) parameter real l = 1e-6;
(* type="instance" *) parameter real w = 1e-6;
analog I(a,b) <+ g*V(a,b);
endmodule
""",
    # [15] a model that ends the run at V > 1.5
    "fin": """module fin(a, b);
inout a, b; electrical a, b;
analog begin
  I(a,b) <+ V(a,b)/1k;
  if (V(a,b) > 1.5) $finish;
end
endmodule
""",
    # [16] opvars with units
    "uv": """module uv(a, b);
inout a, b; electrical a, b;
parameter real r = 1k;
(* units="A" *) real iop;
(* units="W" *) real pw;
(* units="Ohm" *) real rr;
(* units="F" *) real cc;
(* units="S" *) real gg;
(* units="V" *) real vv;
(* desc="no units" *) real nounit;
(* desc="named like a current" *) real ifoo;
(* units="furlong" *) real odd;
analog begin
  iop = V(a,b)/r; pw = iop*V(a,b); rr = r; cc = 1p; gg = 1/r; vv = V(a,b);
  nounit = 3; ifoo = 2; odd = 1;
  I(a,b) <+ iop;
end
endmodule
""",
    # [10] a model and an instance parameter
    "dp": """module dp(a, b);
inout a, b; electrical a, b;
parameter real g = 1e-3;
(* type="instance" *) parameter real k = 1;
analog I(a,b) <+ k*g*V(a,b);
endmodule
""",
}


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    return ok


for name, src in MODELS.items():
    path = os.path.join(WORK, f"{name}.va")
    with open(path, "w") as f:
        f.write(HDR + src)
    r = subprocess.run([VAF, path, "-o", os.path.join(WORK, f"{name}.osdi")],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)


def ngrun(text, tag):
    path = os.path.join(WORK, f"{tag}.cir")
    with open(path, "w") as f:
        f.write(text)
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=120,
                       cwd=WORK, errors="replace")
    return p.stdout + p.stderr


def run(models, body, ctl, tag):
    pre = "".join(f"pre_osdi {m}.osdi\n" for m in models)
    return ngrun(f"* osdislips {tag}\n.control\n{pre}.endc\n{body}\n.control\n{ctl}\n.endc\n.end\n", tag)


def val(out, name):
    m = re.search(r"^" + re.escape(name) + r" = (\S+)", out, re.M)
    return float(m.group(1)) if m else None


print("Enhancement-796..810: the smaller slips D1-D17 of the 2026-10-08 ngspice + OSDI hunt\n")

# ------------------------------------------------------------- [1] ---
print("[1] E-796: an integer parameter written by altermod/alter")
B1 = "v1 1 0 2\nn1 1 0 ipm k=1\n.model ipm ip n=2"
out = run(["ip"], B1, "op\naltermod ipm n=3.7\nop\nprint @ipm[n] i(v1)", "i1")
check("[1] altermod n=3.7: the card's warning, with the value and the result",
      "Warning: model ipm: parameter (n) is an integer; the given non-integral value 3.7 "
      "was rounded to 4." in out and val(out, "@ipm[n]") == 4.0, out[-300:])
out = run(["ip"], B1, "op\nalter n1 k=2.6\nop\nprint @n1[k]", "i2")
check("[1] alter n1 k=2.6: warned, naming n1; k = 3",
      "Warning: n1: parameter (k) is an integer; the given non-integral value 2.6 was "
      "rounded to 3." in out and val(out, "@n1[k]") == 3.0, out[-300:])
out = run(["ip"], B1, "op\naltermod ipm n=-2.5\nop\nprint @ipm[n]", "i3")
out2 = run(["ip"], "v1 1 0 2\nn1 1 0 ipm k=1\n.model ipm ip n=-2.5", "op\nprint @ipm[n]", "i3b")
check("[1] -2.5 rounds half away from zero, to -3, as on the card (it was -2)",
      val(out, "@ipm[n]") == -3.0 and val(out2, "@ipm[n]") == -3.0,
      f"{val(out, '@ipm[n]')} {val(out2, '@ipm[n]')}")
out = run(["ip"], B1, "op\naltermod ipm n=1e300\nop\nprint @ipm[n]", "i4")
check("[1] altermod n=1e300 is refused, not saturated (n stays 2)",
      "Error: value 1e+300 for integer parameter 'n' does not fit an integer; not applied."
      in out and val(out, "@ipm[n]") == 2.0, out[-300:])
out = run(["ip"], B1, "op\nalter n1 k=3e9\nop\nprint @n1[k]", "i5")
check("[1] alter n1 k=3e9 is refused too (k stays 1)",
      "does not fit an integer; not applied" in out and val(out, "@n1[k]") == 1.0, out[-300:])
out = run(["ip"], B1, "op\naltermod ipm n=3\nop\nprint @ipm[n]", "i6")
check("[1] an integral value says nothing", "rounded" not in out and val(out, "@ipm[n]") == 3.0,
      out[-300:])

# ------------------------------------------------------------- [2] ---
print("[2] E-797: a saved operating-point variable")
out = run(["ov"], "v1 1 0 sin(0 1 1k)\nn1 1 0 ovm\n.model ovm ov\n.save @n1[iop] @n1[pw] v(1)",
          "tran 10u 1m\nprint @n1[iop][25] v(1)[25]", "s1")
iop, v = val(out, "@n1[iop][25]"), val(out, "v(1)[25]")
check("[2] .save @n1[iop] @n1[pw]: no warning at load", "has no value yet" not in out
      and "operating-point variable" not in out, out[-300:])
check("[2] ...and the vector is recorded per point (iop = v/1k)",
      iop is not None and v is not None and abs(iop - v / 1e3) < 1e-12, f"{iop} {v}")
out = run(["ov"], "v1 1 0 1\nn1 1 0 ovm\n.model ovm ov\n.save @n1[nosuch] @nn9[iop]",
          "op", "s2")
check("[2] a parameter the device lacks, and a device that does not exist, still warn",
      "device has no parameter 'nosuch'" in out and "save '@nn9[iop]': no such device" in out,
      out[-400:])

# ------------------------------------------------------------- [3] ---
print("[3] E-798: print of a string parameter")
B3 = "v1 1 0 2\nn1 1 0 t3m\n.model t3m t3"
out = run(["t3"], B3, "op\nprint @t3m[mode]\nprint @n1[imode]\nprint @t3m[mode] v(1)", "p1")
check("[3] print @t3m[mode] and @n1[imode] show the text",
      out.count("@t3m[mode] = lin") == 2 and "@n1[imode] = fast" in out
      and val(out, "v(1)") == 2.0, out[-400:])
check("[3] ...without the vec_get error or a checkvalid warning",
      "can not handle string value" not in out and "checkvalid" not in out, out[-400:])
out = run(["t3"], B3, "op\nprint @n1", "p2")
check("[3] print @n1 lists the string parameter beside the numbers",
      "@n1[imode] = fast" in out and val(out, "@n1[i]") == 2e-3
      and "can not handle" not in out, out[-500:])
out = run(["s1"], "v1 1 0 2\nn1 1 0 s1m\n.model s1m s1", "op\nprint @s1m", "p3")
check("[3] print @s1m, a model whose only parameter is a string",
      "@s1m[only] = x" in out and "checkvalid" not in out, out[-300:])
out = run(["t3"], B3, "op\nlet x = @t3m[mode]", "p4")
check("[3] an expression is told it met a string parameter, and its value",
      'Error: @t3m[mode] is a string parameter ("lin"); a vector holds numbers, so an '
      "expression cannot use it. `print @t3m[mode]` shows it." in out, out[-400:])

# ------------------------------------------------------------- [4] ---
print("[4] E-799: an out-of-range value on a paramset member")
B4 = "v1 1 0 1\nn1 1 0 rsm\n.model rsm rs l=2"
NOTE4 = ("  'n1' was bound to member 'rs' of the paramset family 'rs' when the netlist was "
         "read (LRM 6.4.2), and a member is not chosen again after that; member 'rs__2' "
         "accepts 20: write l=20 in the netlist (the instance line, or the card) and load it "
         "again to bind there")
out = run(["rb"], B4, "op\naltermod rsm l=20\nop", "m1")
check("[4] altermod rsm l=20: the range line, then the member that takes 20",
      "Parameter l of 'n1' is out of bounds (value 20; range from [1:10))!" in out
      and NOTE4 in out, out[-600:])
out = run(["rb"], B4, "op\nalter n1 l=20\nop", "m2")
check("[4] alter n1 l=20: the same", NOTE4 in out, out[-600:])
out = run(["rb"], B4, "op\nalter n1 l=200\nop", "m3")
check("[4] a value no member accepts says so",
      "; no member of the family accepts 200" in out, out[-600:])
out = run(["rg"], "v1 1 0 1\nn1 1 0 rgm\n.model rgm rg", "op\nalter n1 l=20\nop", "m4")
check("[4] an ordinary ranged parameter gets the range line alone",
      "Parameter l of 'n1' is out of bounds (value 20" in out and "paramset" not in out,
      out[-400:])
out = run(["rb"], "v1 1 0 1\nn1 1 0 rsm l=20\n.model rsm rs", "op\nprint i(v1)", "m5")
check("[4] l=20 written in the netlist binds member rs__2 (i = 50 uA)",
      "resolved to its member 'rs__2'" in out and val(out, "i(v1)") == -5e-05, out[-300:])

# ------------------------------------------------------------- [5] ---
print("[5] E-800: a .temp card listing several temperatures")
R5 = "r1 1 0 1k tc1=0.01\nv1 1 0 1\n"


def temp_deck(card, tag, ctl="op\nprint i(v1)"):
    return ngrun(f"* temp {tag}\n{R5}{card}\n.control\n{ctl}\n.endc\n.end\n", tag)


out = temp_deck(".temp 0 27 50", "t1")
check("[5] .temp 0 27 50: runs at the first, 0 C, and says so",
      "Warning: .temp lists 3 temperatures (0 27 50); ngspice runs a circuit at one "
      "temperature, so this run uses the first, 0 C." in out
      and abs(val(out, "i(v1)") * 1e3 * (1 - 0.27) + 1) < 1e-5, out[-400:])
check("[5] ...and how to run them all",
      "`foreach t 0 27 50`, `set temp = $t`, `run`, `end` -- or `.dc temp`" in out, out[-400:])
out = temp_deck(".temp=-40, 125", "t2")
check("[5] .temp=-40, 125: two, commas read as separators, -40 C",
      "lists 2 temperatures (-40 125)" in out and "uses the first, -40 C" in out, out[-400:])
out = temp_deck(".temp abc", "t3")
check("[5] a value that is not a number keeps the old message and 27 C",
      "Could not set temperature to abc" in out and val(out, "i(v1)") == -1e-3, out[-300:])
out = temp_deck(".temp 0 27 x", "t3b")
check("[5] a list with a non-number in it: the same", "Could not set temperature to 0 27 x" in out,
      out[-300:])
out = temp_deck(".temp 85", "t4")
check("[5] one temperature: no warning", "Warning" not in out.replace(
    "Warning: can't find the initialization file spinit.", ""), out[-300:])
out = temp_deck(".op", "t5", "foreach t 0 27 50\nset temp = $t\nrun\nprint i(v1)\nend")
got = [float(x) for x in re.findall(r"^i\(v1\) = (\S+)", out, re.M)]
want = [-1 / (1e3 * (1 + 0.01 * (t - 27))) for t in (0, 27, 50)]
check("[5] the suggested foreach loop runs each temperature",
      len(got) == 3 and all(abs(a / b - 1) < 1e-5 for a, b in zip(got, want)), f"{got}")

# ------------------------------------------------------------- [6] ---
print("[6] D6 (kept): a timer in an equilibrium analysis")
B6 = "v1 1 0 1\nn1 1 0 tmm\n.model tmm tm"
out = run(["tm"], B6, "op", "e1")
check("[6] op: timer(0, 1u) fires once, at t = 0; timer(2.5u) not at all",
      re.findall(r"TIMER n=(\d+) t=(\S+)", out) == [("1", "0")] and "ONESHOT" not in out,
      out[-300:])
out = run(["tm"], B6, "dc v1 0 2 1", "e2")
check("[6] dc sweep: once, at the first point",
      re.findall(r"TIMER n=(\d+) t=(\S+)", out) == [("1", "0")] and "ONESHOT" not in out,
      out[-300:])
out = run(["tm"], B6, "tran 0.1u 3.2u", "e3")
check("[6] tran: at 0 (its operating point), 1u, 2u, 3u, and the one-shot at 2.5u",
      re.findall(r"TIMER n=(\d+) t=(\S+)", out)
      == [("1", "0"), ("2", "1e-06"), ("3", "2e-06"), ("4", "3e-06")]
      and "ONESHOT t=2.5e-06" in out, out[-500:])

# ------------------------------------------------------------- [7] ---
print("[7] E-801: the pz keywords")
R7 = "v1 1 0 dc 0 ac 1\nr1 1 2 1k\nc1 2 0 1n\n"


def pz(args, tag):
    return ngrun(f"* pz {tag}\n{R7}.control\npz {args}\nprint all\n.endc\n.end\n", tag)


SYN = "(pz in1 in2 out1 out2 vol|cur pol|zer|pz)"
for args, want, tag in [
        ("1 0 2 0 pol", "pz: the transfer type (`vol` or `cur`) is missing", "z1"),
        ("1 0 2 0 vol", "pz: the analysis (`pol`, `zer` or `pz`) is missing", "z2"),
        ("1 0 2 0", "pz: both keywords are missing", "z3"),
        ("1 0 2 0 vol pole", "pz: 'pole' is not a pole-zero keyword", "z4"),
        ("1 0 2 0 vol pz extra", "pz: 'extra' is not a pole-zero keyword", "z5"),
        ("1 0 2 0 vol cur", "pz: two transfer types are given", "z6"),
        ("1 0 2 0 vol pz pol", "pz: 'pol' follows both keywords", "z7")]:
    out = pz(args, tag)
    check(f"[7] pz {args}: named, with the syntax", want in out and SYN in out
          and "no such parameter on this device" not in out, out[-400:])
for args, tag in [("1 0 2 0 vol pz", "z8"), ("1 0 2 0 pz vol", "z9")]:
    out = pz(args, tag)
    check(f"[7] pz {args} runs (the pole at -1e6)", re.search(r"-1\.00000e\+06", out) is not None
          and "Error" not in out, out[-300:])
out = pz("1 0 2 0 cur pol", "z10")
check("[7] pz 1 0 2 0 cur pol is accepted and runs", "Error" not in out and "all =" in out,
      out[-300:])

# ------------------------------------------------------------- [8] ---
print("[8] E-802: .meas in a batch run with a .control block")
R8 = "v1 1 0 pulse(0 2 0 1n 1n 1u 2u)\nr1 1 0 1k\n.meas tran vmax max v(1)\n"


def mdeck(rest, tag):
    return ngrun(f"* meas {tag}\n{R8}{rest}.end\n", tag)


def nmeas(out):
    return len(re.findall(r"^vmax\s+=\s+\S+\s+at=", out, re.M))


out = mdeck(".control\ntran 1n 2u\nprint vmax\nlet x = vmax*2\nprint x\n.endc\n", "c1")
check("[8] analysis in the .control block, none on a card: measured once, run once",
      nmeas(out) == 1 and out.count("Doing analysis") == 1, out[-500:])
check("[8] ...and the result is a vector: print vmax, let x = vmax*2",
      val(out, "vmax") == 2.0 and val(out, "x") == 4.0 and "checkvalid" not in out, out[-500:])
out = mdeck(".tran 1n 2u\n.control\nrun\n.endc\n", "c2")
check("[8] a .tran card and `run` in the block: run once, measured once (it was twice each)",
      nmeas(out) == 1 and out.count("Doing analysis") == 1, out[-500:])
out = mdeck(".tran 1n 2u\n", "c3")
check("[8] a card and no .control block: once, as before",
      nmeas(out) == 1 and out.count("Doing analysis") == 1, out[-500:])
out = mdeck(".control\ntran 1n 2u\n.endc\n.print tran v(1)\n", "c4")
check("[8] a .print card still prints its table after the block's tran",
      nmeas(out) == 1 and "Index" in out, out[-300:])
out = mdeck(".tran 1n 2u\n.print tran v(1)\n.control\ntran 1n 2u\n.endc\n", "c5")
check("[8] a deck .tran beside a block `tran` (two analyses asked for): both run, as before",
      nmeas(out) == 2 and out.count("Doing analysis") == 2, out[-300:])
out = ngrun("* meas fail\nv1 1 0 pulse(0 2 0 1n 1n 1u 2u)\nr1 1 0 1k\n"
            ".meas tran bad when v(1)=5\n.control\ntran 1n 2u\nprint bad\n.endc\n.end\n", "c6")
check("[8] a failed measurement leaves no vector",
      "failed!" in out and "vector bad is not available" in out, out[-400:])
out = ngrun("* meas name\nv1 out 0 pulse(0 2 0 1n 1n 1u 2u)\nr1 out 0 1k\n"
            ".meas tran out max v(out)\n.control\ntran 1n 2u\nlet n = length(out)\nprint n\n.endc\n"
            ".end\n", "c7")
check("[8] a result named like a node does not replace the node's vector",
      (val(out, "n") or 0) > 100, out[-400:])

# ------------------------------------------------------------- [9] ---
print("[9] E-803: the osdi command")
out = ngrun("* osdi\n.control\npre_osdi dp.osdi rb.osdi\nosdi\nosdi -l\nosdi -f\nosdi -va\n"
            "osdi -f -va\n.endc\nv1 1 0 1\nn1 1 0 dpm\n.model dpm dp\n.control\nop\nprint i(v1)\n"
            ".endc\n.end\n", "o1")
check("[9] osdi alone lists each library and its modules",
      "OSDI libraries loaded (2):" in out and re.search(r"dp\.osdi: dp$", out, re.M)
      and re.search(r"rb\.osdi: rb, rs, rs__2$", out, re.M) and "too few args" not in out,
      out[-800:])
check("[9] an unknown option is refused, not opened as a file",
      "Error: osdi: unknown option '-l'; the options are -f" in out
      and 'Error opening osdi lib "-l"' not in out, out[-800:])
check("[9] -f, -va and -f -va with no file say so",
      "Error: osdi: -f names no file to reload." in out
      and "Error: osdi: -va names no file to compile." in out
      and "Error: osdi: -f -va names no file to reload." in out, out[-800:])
check("[9] ...and the loaded model still runs", val(out, "i(v1)") == -1e-3, out[-300:])
out = ngrun("* none\nr1 1 0 1k\nv1 1 0 1\n.control\nosdi\nop\n.endc\n.end\n", "o2")
check("[9] nothing loaded: said, with how to load one",
      "No OSDI library is loaded. Load one with `osdi file.osdi`" in out, out[-300:])

# ------------------------------------------------------------- [10] ---
print("[10] E-804: a parameter set twice on a .model card")
out = run(["dp"], "v1 1 0 1\nn1 1 0 dpm\n.model dpm dp g=1m g=2m", "op\nprint i(v1)", "d1")
check("[10] a model parameter twice: the last value is used, and said",
      "Warning: .model dpm: parameter 'g' is set more than once on this card; the last value "
      "is used." in out and val(out, "i(v1)") == -2e-3, out[-300:])
out = run(["dp"], "v1 1 0 1\nn1 1 0 dpm\n.model dpm dp k=2 k=3",
          "op\nprint i(v1)\naltermod dpm k=5\nop\nprint i(v1)\nshowmod dpm", "d2")
got = [float(x) for x in re.findall(r"^i\(v1\) = (\S+)", out, re.M)]
check("[10] an instance-parameter default twice: the last too (3, the first used to win)",
      "parameter 'k' is set more than once on this card; the last value is used." in out
      and got[:1] == [-3e-3], f"{got}")
check("[10] ...one entry on the card, which altermod moves (5)",
      got[1:2] == [-5e-3] and len(re.findall(r"^\s+k\s+\S+$", out, re.M)) == 1, f"{got}")
out = run(["dp"], "v1 1 0 1\nn1 1 0 dpm k=2 k=3\n.model dpm dp", "op\nprint i(v1)", "d3")
check("[10] the instance line: unchanged ('the last value is used', 3)",
      "parameter 'k' is set more than once on this line; the last value is used." in out
      and val(out, "i(v1)") == -3e-3, out[-300:])

# ------------------------------------------------------------- [11] ---
print("[11] E-805: too many nodes on an OSDI instance line")
out = run(["gr"], "v1 1 0 1\nr9 2 0 1k\nn1 1 2 3 grm\n.model grm gr", "op", "n11")
check("[11] one extra: the terminals and the node left over",
      "too many nodes: n1 connects 3, but model grm (module gr) has 2 terminals (a, b); "
      "'3' is left over" in out, out[-400:])
out = run(["gr"], "v1 1 0 1\nn1 1 0 3 4 grm\n.model grm gr", "op", "n12")
check("[11] two extra: both named", "connects 4" in out and "'3 4' are left over" in out,
      out[-400:])
out = run(["gr"], "v1 1 0 1\nn1 1 0 grm\n.model grm gr", "op\nprint i(v1)", "n13")
check("[11] the right count still runs", val(out, "i(v1)") == -1e-3, out[-300:])

# ------------------------------------------------------------- [12] ---
print("[12] E-806: a Verilog-A child's internal node, and the short form of a subcircuit instance")
B12 = "v1 1 0 2\nn1 1 0 parm\n.model parm par"
out = run(["par"], B12, "op\nprint v(n1#c1__mid) v(n1#c1.mid) v(n1#g1.k1.mid)", "h1")
check("[12] print: n1#c1.mid and n1#g1.k1.mid name n1#c1__mid and n1#g1__k1__mid",
      val(out, "v(n1#c1.mid)") == 1.0 and val(out, "v(n1#g1.k1.mid)") == 1.0
      and "checkvalid" not in out, out[-400:])
out = run(["par"], "v1 1 0 pwl(0 0 1u 2)\nn1 1 0 parm\n.model parm par\n"
          ".save v(n1#c1.mid) v(n1#g1.k1.mid) v(1)\n.meas tran vm max v(n1#g1.k1.mid)",
          "tran 10n 1u\nprint vm", "h2")
check("[12] .save and .meas take the hierarchical spelling",
      "nothing of that name" not in out and val(out, "vm") is not None
      and abs(val(out, "vm") - 0.5677) < 1e-3, out[-400:])
out = run(["par"], B12 + "\n.ic v(n1#c1.mid)=0.5", "tran 1n 10n uic\nprint v(n1#c1__mid)[0]", "h3")
check("[12] .ic v(n1#c1.mid) is applied", abs((val(out, "v(n1#c1__mid)[0]") or 0) - 0.5) < 1e-3
      and "non-existent" not in out, out[-400:])
out = run(["par"], B12 + "\n.nodeset v(n1#c1.mid)=0.7 v(n1#nosuch.mid)=1", "op", "h4")
check("[12] .nodeset takes it too, and a name that is no node is still refused",
      "non-existent node - n1#nosuch.mid" in out and "n1#c1.mid" not in out, out[-400:])
out = run(["nr"], "v1 1 0 dc 0 ac 1\nr1 1 2 1k\nx1 2 0 sub\n.subckt sub a b\nn1 a b nrm\n"
          ".model nrm nr r=1k\n.ends",
          "noise v(2) v1 lin 1 1k 1k 1\nsetplot noise1\nprint onoise_n.x1.n1_thermal "
          "onoise_x1.n1_thermal\nprint onoise_x1.nosuch_thermal", "h5")
a, b = val(out, "onoise_n.x1.n1_thermal"), val(out, "onoise_x1.n1_thermal")
check("[12] onoise_x1.n1_thermal is onoise_n.x1.n1_thermal", a is not None and a == b,
      f"{a} {b}")
check("[12] ...and a short form that names nothing is still not available",
      "vector onoise_x1.nosuch_thermal is not available" in out, out[-300:])

# ------------------------------------------------------------- [13] ---
print("[13] E-807: altermod on a binned model's name")
B13 = ("v1 1 0 1\nv2 2 0 1\nn1 1 0 nch l=0.5u w=1u\nn2 2 0 nch l=5u w=1u\n"
       ".model nch.1 bm g=1m lmin=0 lmax=1u wmin=0 wmax=10u\n"
       ".model nch.2 bm g=3m lmin=1u lmax=10u wmin=0 wmax=10u")
out = run(["bm"], B13, "op\naltermod nch g=7m\nop\nprint i(v1) i(v2)", "b1")
check("[13] altermod nch g=7m: both bins, and a note naming them in bin order",
      "Note: altermod: 'nch' is a binned model; g was given to its 2 bins (nch.1, nch.2)."
      in out and val(out, "i(v1)") == -7e-3 and val(out, "i(v2)") == -7e-3, out[-400:])
out = run(["bm"], B13, "op\naltermod @nch[g]=7m\nop\nprint i(v2)", "b2")
check("[13] the @nch[g] spelling too", val(out, "i(v2)") == -7e-3, out[-300:])
out = run(["bm"], B13, "op\naltermod nch nosuch=1\naltermod nchx g=1m", "b3")
check("[13] a parameter no bin has: each refusal, then 'no bin took'",
      "no bin took nosuch" in out and "was given" not in out, out[-400:])
check("[13] a name with no bins is still 'no such device or model name'",
      "no such device or model name nchx" in out, out[-400:])
out = ngrun("* bsim4 bins\nvd d 0 1\nvg g 0 1\nm1 d g 0 0 nch l=0.5u w=1u\nm2 d g 0 0 nch l=5u w=1u\n"
            ".model nch.1 nmos level=54 vth0=0.5 lmin=0 lmax=1u wmin=0 wmax=10u\n"
            ".model nch.2 nmos level=54 vth0=0.5 lmin=1u lmax=10u wmin=0 wmax=10u\n"
            ".control\nop\nprint @m2[id]\naltermod nch vth0=0.3\nop\nprint @m2[id]\n"
            ".endc\n.end\n", "b4")
ids = [float(x) for x in re.findall(r"^@m2\[id\] = (\S+)", out, re.M)]
check("[13] built-in BSIM4 bins the same way (the current rises as vth0 falls)",
      "given to its 2 bins (nch.1, nch.2)" in out and len(ids) == 2 and ids[1] > ids[0], f"{ids}")

# ------------------------------------------------------------- [14] ---
print("[14] E-808: savecurrents outside op, dc and tran")
B14 = "v1 1 0 dc 0.6 ac 1\nr1 1 2 1k\nc1 2 0 1n\nd1 2 0 dm\n.model dm d is=1e-14\nn1 1 0 grm\n.model grm gr\n.option savecurrents"
out = run(["gr"], B14, "ac lin 2 1k 1meg\ndisplay", "c14a")
check("[14] ac: no savecurrents vector of a built-in device (each was 0 long); the OSDI "
      "device's three are kept, its small-signal current since E-835 (they held its bias)",
      "@c1[i]" not in out and "@d1[id]" not in out and "@n1[i]" in out, out[-600:])
check("[14] ...and one note for the built-in three, with the .probe hint",
      len(re.findall(r"Note: \.options savecurrents saves device currents in op, dc and tran "
                     r"analyses; this AC analysis leaves its 3 out \(they would hold nothing: "
                     r"a built-in device answers no current there\)", out)) == 1
      and "`.probe i(<device>)`" in out, out[-600:])
out = run(["gr"], B14, "noise v(2) v1 lin 2 1k 2k 1\nsetplot noise1\ndisplay\nsetplot noise2\ndisplay",
          "c14b")
check("[14] noise: none in either noise plot, said once",
      "@c1[i]" not in out and "@n1[i]" not in out
      and out.count("this NOISE analysis leaves its 6 out (they would hold the bias currents, "
                    "repeated at every frequency)") == 1, out[-600:])
out = run(["gr"], B14, "op\nprint @r1[i] @n1[i]\ndc v1 0 0.6 0.3\ndisplay", "c14c")
check("[14] op and dc keep them", val(out, "@r1[i]") is not None and "@d1[id]" in out
      and "leaves its" not in out, out[-600:])
out = run(["gr"], B14.replace(".option savecurrents", ".save @r1[i] v(1)"), "ac lin 1 1k 1k\ndisplay", "c14d")
check("[14] an explicit .save of a current in ac is the user's, kept as before",
      "@r1[i]" in out and "leaves its" not in out, out[-400:])

out = ngrun("* probe\nv1 1 0 dc 0 ac 1\nr1 1 2 1k\nc1 2 0 1n\n.probe i(r1) i(c1)\n.control\n"
            "ac lin 2 1k 1meg\nlet pd1 = vecmax(mag(i(r1) + i(v1)))\nlet pd2 = vecmax(mag(i(r1) - i(c1)))\n"
            "let pd3 = vecmin(mag(i(c1)))\nprint pd1\nprint pd2\nprint pd3\n.endc\n.end\n", "c14e")
pd = [float(x) for x in re.findall(r"pd\d = (\S+)", out)]
check("[14] the hinted .probe i(<device>) records the ac current: i(r1) = -i(v1) = i(c1), non-zero",
      len(pd) == 3 and pd[0] < 1e-12 and pd[1] < 1e-12 and pd[2] > 1e-6, f"{pd}")

# ------------------------------------------------------------- [15] ---
print("[15] E-809: an interval measurement whose window the data did not reach")
F15 = ("v1 1 0 pwl(0 0 1u 3)\nn1 1 0 fm\n.model fm fin\n"
       ".meas tran vavg avg v(1) from=0 to=1u\n.meas tran vrms rms v(1) from=0 to=1u\n"
       ".meas tran vint integ v(1) from=0 to=1u\n.meas tran vmx max v(1) from=0 to=1u\n"
       ".meas tran vpp pp v(1) from=0 to=1u\n.meas tran vok avg v(1) from=0 to=0.4u\n"
       ".meas tran vnoto avg v(1)")
out = run(["fin"], F15, "tran 10n 1u", "w15")
for m, f in (("vavg", "avg"), ("vrms", "rms"), ("vint", "integ"), ("vmx", "max"), ("vpp", "pp")):
    check(f"[15] {f}: said that the data end at 5.028e-07, before TO=1e-06",
          f"Warning: measure {m}: the data end at 5.028e-07, before TO=1e-06; the {f} covers "
          "the window up to 5.028e-07 only." in out, out[-900:])
check("[15] pp's echo is the window used (it printed to= 1e-06)",
      re.search(r"^vpp\s+=\s+\S+ from=\s+0\.00000e\+00 to=\s+5\.02800e-07", out, re.M) is not None,
      out[-500:])
check("[15] a window inside the data, and one without TO, say nothing",
      "measure vok" not in out and "measure vnoto" not in out, out[-500:])

# ------------------------------------------------------------- [16] ---
print("[16] E-810: a saved OSDI opvar is typed by its units")
out = run(["uv"], "v1 1 0 pwl(0 0 1u 2)\nn1 1 0 uvm\n.model uvm uv\n"
          ".save all @n1[iop] @n1[pw] @n1[rr] @n1[cc] @n1[gg] @n1[vv] @n1[nounit] @n1[ifoo] "
          "@n1[odd] @n1[i_a]", "tran 10n 1u\ndisplay", "u16")
types = dict(re.findall(r"^\s+@n1\[(\w+)\]\s+:\s+([\w-]+),", out, re.M))
for vec, want in (("pw", "power"), ("rr", "impedance"), ("cc", "capacitance"), ("gg", "admittance"),
                  ("iop", "current"), ("vv", "voltage"), ("nounit", "notype"), ("ifoo", "notype"),
                  ("odd", "notype"), ("i_a", "current")):
    check(f"[16] @n1[{vec}] is {want}", types.get(vec) == want, f"{types.get(vec)}")

print(f"\n    {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
