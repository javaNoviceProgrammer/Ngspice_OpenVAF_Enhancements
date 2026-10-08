#!/usr/bin/env python3
"""Enhancement-796..804: the smaller slips D1..D10 of the ngspice + OSDI hunt of
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


print("Enhancement-796..804: the smaller slips D1-D10 of the 2026-10-08 ngspice + OSDI hunt\n")

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

print(f"\n    {passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
