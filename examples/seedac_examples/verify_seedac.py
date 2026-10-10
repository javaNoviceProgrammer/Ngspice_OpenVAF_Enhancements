#!/usr/bin/env python3
"""Enhancements 832 to 835 (F16-F19 of the 2026-10-08 ngspice + OSDI hunt): an
unseeded Verilog-A $random, a module's internal node with no DC path, the bins
of one model under osdimc, and an OSDI device's terminal current in ac and sp.

Enhancement-832 (F16). `$random` and `$arandom` with no seed drew with the seed
0: the same number in every analysis and in every instance, and `setseed`
changed nothing. They now draw with a per-analysis seed ngspice derives from
its generator's seed, mixed with the instance's name.
  [1] successive analyses draw new values, `setseed` reproduces them, two
      instances differ; a seeded draw repeats (control); a draw holds one
      value through an op, a transient and a dc sweep

Enhancement-833 (F17). The dc-path walk took every node named with a '#' for a
built-in device's internal node, reached by its series elements -- and an
OSDI module's internal nodes are named so too (`n1#mid`). One reached only
through ddt() went "singular matrix" down every homotopy (277 iterations).
  [2] the node gets the dc-path gmin at once, as the built-in twin does, and
      is released in a transient; a node with a resistive path is not named

Enhancement-834 (F18). Under osdimc a process parameter's draw was keyed on
the model card, so the bins nch.1 and nch.2 of one device type drew
independently. They are keyed on the base name now.
  [3] the bins move together in every trial; two unbinned cards still differ
      (control); wcd counts one dimension; highsigma's estimate matches a
      single card's

Enhancement-835 (F19). In ac and sp an OSDI device's terminal currents read
the DC bias current, real and flat at every frequency. They are the
small-signal currents now.
  [4] against the source current (KCL), with m=2, with an ac_stim() source,
      in sp; `.options savecurrents` keeps them in ac; op unchanged (control)
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

WORK = tempfile.mkdtemp(prefix="seedac_")
checks = passed = 0
H = '`include "disciplines.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))
    return ok


def compile_va(name, src):
    va = os.path.join(WORK, name + ".va")
    with open(va, "w") as f:
        f.write(src)
    r = subprocess.run([VAF, va, "-o", os.path.join(WORK, name + ".osdi")],
                       capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        print(r.stdout + r.stderr)
        sys.exit(1)


def run(name, deck):
    """(exit status, combined output)"""
    path = os.path.join(WORK, name)
    with open(path, "w") as f:
        f.write(deck)
    p = subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True, timeout=300,
                       cwd=WORK, errors="replace")
    return p.returncode, p.stdout + p.stderr


def val(out, name):
    m = re.search(r"^" + re.escape(name) + r"\s*=\s*(\S+)", out, re.M)
    return float(m.group(1).rstrip(",")) if m else None


def vals(out, name):
    return [float(x.rstrip(",")) for x in
            re.findall(r"^" + re.escape(name) + r"\s*=\s*(\S+)", out, re.M)]


def near(a, b, tol=1e-6):
    return a is not None and b is not None and abs(a - b) <= tol * max(1e-12, abs(b))


print("Enhancements 832-835: unseeded $random, internal-node dc path, osdimc bins, "
      "ac terminal currents\n")

# ------------------------------------------------------------- [1] ---
print("[1] Enhancement-832: an unseeded $random draws per analysis and per instance")
compile_va("rd", H + """module rd(a, b);
inout a, b; electrical a, b;
integer r1, r2, s;
real x;
(* desc="a draw in the analog body" *) real rb;
analog begin
  @(initial_step) begin
    s = 5;
    r1 = $random; r2 = $arandom; x = $rdist_normal(s, 0, 1);
    $strobe("RAND %m r1=%0d r2=%0d x=%.6f", r1, r2, x);
  end
  rb = $random;
  I(a,b) <+ V(a,b)/1k + 1e-12*rb/2147483648.0;
end
endmodule
""")
RD = "v1 1 0 1\nn1 1 0 rdm\nn2 1 0 rdm\n.model rdm rd\n"


def draws(out):
    """[(inst, r1, r2, x), ...] in print order"""
    return [(m.group(1), int(m.group(2)), int(m.group(3)), float(m.group(4))) for m in
            re.finditer(r"RAND (\S+) r1=(-?\d+) r2=(-?\d+) x=(\S+)", out)]


rc, out = run("r1.cir", f"* rd\n.control\npre_osdi rd.osdi\n.endc\n{RD}.control\n"
                        "op\nop\nsetseed 1\nop\nsetseed 2\nop\n.endc\n.end\n")
d = draws(out)
n1 = [t for t in d if t[0] == "n1"]
n2 = [t for t in d if t[0] == "n2"]
ok = len(n1) == 4 and len(n2) == 4
check("[1] two `op`s draw different $random and $arandom values (were identical, "
      "1366254664 every time)",
      ok and n1[0][1] != n1[1][1] and n1[0][2] != n1[1][2], f"{d}")
check("[1] `setseed 1` reproduces the first analysis' draw (1 is the startup seed); "
      "`setseed 2` draws another (setseed changed nothing)",
      ok and n1[2][1:3] == n1[0][1:3] and n2[2][1:3] == n2[0][1:3]
      and n1[3][1] not in (n1[0][1], n1[1][1]), f"{d}")
check("[1] two instances of one module draw different values (were identical)",
      ok and all(a[1] != b[1] and a[2] != b[2] for a, b in zip(n1, n2)), f"{d}")
check("[1] a seeded $rdist_normal(s, 0, 1), s re-initialised to 5, repeats in every analysis "
      "and instance (control: the seed is the user's)",
      ok and len({t[3] for t in d}) == 1, f"{d}")

rc, out = run("r2.cir", f"* rd tran\n.control\npre_osdi rd.osdi\n.endc\n{RD}.save @n1[rb]\n"
                        ".control\ntran 1n 20n\nlet sp = vecmax(@n1[rb]) - vecmin(@n1[rb])\n"
                        "let n = length(@n1[rb])\nprint sp n @n1[rb][0]\n"
                        "dc v1 0 1 0.25\nlet sd = vecmax(@n1[rb]) - vecmin(@n1[rb])\nprint sd\n"
                        ".endc\n.end\n")
check("[1] a draw in the analog body holds one value through a transient (its operating point "
      "and every step) and through a dc sweep: the draw is constant within an analysis",
      val(out, "sp") == 0.0 and (val(out, "n") or 0) > 10 and val(out, "@n1[rb][0]") not in (None, 0.0)
      and val(out, "sd") == 0.0 and "simulation(s) aborted" not in out, out[-500:])

# ------------------------------------------------------------- [2] ---
print("[2] Enhancement-833: an OSDI internal node with no DC path gets the dc-path gmin")
compile_va("fl", H + """module fl(a, b);
inout a, b; electrical a, b; electrical mid;
analog begin
  I(a,b) <+ V(a,b)/1k;
  I(a,mid) <+ ddt(1p*V(a,mid));
  I(mid,b) <+ ddt(1p*V(mid,b));
end
endmodule
""")
compile_va("flr", H + """module flr(a, b);
inout a, b; electrical a, b; electrical mid;
analog begin
  I(a,mid) <+ V(a,mid)/1k;
  I(mid,b) <+ ddt(1p*V(mid,b));
end
endmodule
""")
MSG = ("Warning: no DC path from node '{}' to ground; gmin (1e-12 S) installed to provide one; "
       "held at DC only")
rc, out = run("f1.cir", "* fl\n.control\npre_osdi fl.osdi\n.endc\nv1 1 0 1\nn1 1 0 flm\n"
                        ".model flm fl\n.control\nop\nprint v(n1#mid)\nrusage all\n.endc\n.end\n")
it = val(out, "Total iterations")
check("[2] op: 'n1#mid' is named and held by the dc-path gmin; no singular matrix, no stepping, "
      "v(n1#mid) = 0, 3 iterations (were 277: every homotopy failed, the transient "
      "operating point left it at 0.5 V)",
      MSG.format("n1#mid") in out and "ingular matrix" not in out and "stepping" not in out
      and val(out, "v(n1#mid)") == 0.0 and it is not None and it <= 5, f"it={it} {out[-500:]}")
rc, out = run("f2.cir", "* twin\nv1 1 0 1\nr1 1 0 1k\nc1 1 2 1p\nc2 2 0 1p\n"
                        ".control\nop\nprint v(2)\n.endc\n.end\n")
check("[2] the built-in twin (an external node between two capacitors) is held the same way "
      "(control)", MSG.format("2") in out and val(out, "v(2)") == 0.0, out[-400:])
rc, out = run("f3.cir", "* fl tran\n.control\npre_osdi fl.osdi\n.endc\n"
                        "v1 1 0 pulse(0 1 1n 1n 1n 1 2)\nn1 1 0 flm\n.model flm fl\n"
                        "r1 1 0 1k\nc1 1 2 1p\nc2 2 0 1p\n.control\ntran 0.1n 5n\n"
                        "print v(n1#mid)[length(v(2))-1] v(2)[length(v(2))-1]\n.endc\n.end\n")
check("[2] a 0 -> 1 V step: the node is released in the transient and divides as its twin "
      "does, 0.5 V",
      near(val(out, "v(n1#mid)[length(v(2))-1]"), 0.5, 1e-6)
      and near(val(out, "v(2)[length(v(2))-1]"), 0.5, 1e-6), out[-400:])
rc, out = run("f4.cir", "* flr\n.control\npre_osdi flr.osdi\n.endc\nv1 1 0 1\nn1 1 0 frm\n"
                        ".model frm flr\n.control\nop\nprint v(n1#mid)\n.endc\n.end\n")
check("[2] an internal node with a resistive path is not named (control)",
      "no DC path" not in out and near(val(out, "v(n1#mid)"), 1.0), out[-400:])

# ------------------------------------------------------------- [3] ---
print("[3] Enhancement-834: the bins of one model draw together under osdimc")
compile_va("bm", H + """module bm(a, b);
inout a, b; electrical a, b;
(* std_rel=0.1 *) parameter real g = 1e-3;
parameter real lmin = 0; parameter real lmax = 1;
parameter real wmin = 0; parameter real wmax = 1;
(* type="instance" *) parameter real l = 1e-6;
(* type="instance" *) parameter real w = 1e-6;
analog I(a,b) <+ g*V(a,b);
endmodule
""")
BINS = ("n1 1 0 nch l=0.5u w=1u\nn2 2 0 nch l=5u w=1u\n"
        ".model nch.1 bm g=1m lmin=0 lmax=1u wmin=0 wmax=10u\n"
        ".model nch.2 bm g=3m lmin=1u lmax=10u wmin=0 wmax=10u\n")
rc, out = run("b1.cir", "* bins\n.control\npre_osdi bm.osdi\n.endc\nv1 1 0 1\nv2 2 0 1\n"
                        "v3 3 0 1\nv4 4 0 1\n" + BINS +
                        "n3 3 0 pa\nn4 4 0 pb\n.model pa bm g=1m\n.model pb bm g=1m\n"
                        ".option osdimc mcseed=42\n.control\nrepeat 4\nop\n"
                        "print @nch.1[g]/1m @nch.2[g]/3m @pa[g]/1m @pb[g]/1m\nend\n.endc\n.end\n")
b1, b2 = vals(out, "@nch.1[g]/1m"), vals(out, "@nch.2[g]/3m")
pa, pb = vals(out, "@pa[g]/1m"), vals(out, "@pb[g]/1m")
check("[3] three trials after the nominal baseline: nch.1 (g = 1m) and nch.2 (g = 3m) move by "
      "the same relative shift every trial (drew independently: 0.930 against 0.869)",
      len(b1) == 4 and len(b2) == 4 and all(near(a, b, 1e-9) for a, b in zip(b1, b2))
      and all(abs(a - 1.0) > 1e-4 for a in b1[1:]), f"{b1} {b2}")
check("[3] two unbinned cards pa and pb still draw independently (control)",
      len(pa) == 4 and all(abs(a - b) > 1e-6 for a, b in zip(pa[1:], pb[1:])), f"{pa} {pb}")
rc, out = run("b2.cir", "* bins wcd\n.control\npre_osdi bm.osdi\n.endc\nv1 1 0 1\nv2 2 0 1\n" + BINS +
                        ".option osdimc mcseed=42\n.control\n"
                        "wcd -metric -i(v1) -max 1.2m -analysis op\n"
                        "print @nch.1[g]/1m @nch.2[g]/3m\n.endc\n.end\n")
check("[3] wcd: one statistical dimension for the two bins (was 2), and the walk puts them at "
      "one relative shift",
      "wcd: 1 statistical dimension (0 netlist .param, 1 model-declared)" in out
      and near(val(out, "@nch.1[g]/1m"), val(out, "@nch.2[g]/3m"), 1e-9), out[-600:])


def hs(models):
    rc, out = run("hs.cir", "* hs\n.control\npre_osdi bm.osdi\n.endc\nv1 1 0 1\nv2 2 0 1\n"
                            "n1 1 0 nch l=0.5u w=1u\nn2 2 0 nch l=5u w=1u\n" + models +
                            ".option osdimc mcseed=42\n.control\n"
                            "highsigma 400 -scale 2 -seed 3 -analysis op -metric -i(v1)-i(v2) "
                            "-max 2.4m\n.endc\n.end\n")
    m = re.search(r"P\(fail\)\s*:\s*(\S+)\s+\+/-\s+(\S+)", out)
    return (m.group(1), m.group(2)) if m else None, out


est_b, out = hs(".model nch.1 bm g=1m lmin=0 lmax=1u wmin=0 wmax=10u\n"
                ".model nch.2 bm g=1m lmin=1u lmax=10u wmin=0 wmax=10u\n")
est_1, out1 = hs(".model nch bm g=1m\n")
check("[3] highsigma: two bins give the estimate one unbinned card gives -- the shared deviate "
      "is one factor of the importance weight",
      est_b is not None and est_b == est_1, f"{est_b} {est_1} {out[-300:]}")

# ------------------------------------------------------------- [4] ---
print("[4] Enhancement-835: an OSDI device's terminal current in ac and sp is the small-signal one")
compile_va("rr2", H + """module rr2(a, b);
inout a, b; electrical a, b; electrical mid;
parameter real r1 = 1k; parameter real r2 = 1k; parameter real c = 1n;
analog begin
  I(a, mid) <+ V(a, mid)/r1;
  I(mid, b) <+ V(mid, b)/r2;
  I(mid, b) <+ ddt(c*V(mid, b));
end
endmodule
""")
compile_va("st", H + """module st(a, b);
inout a, b; electrical a, b;
analog begin
  I(a,b) <+ V(a,b)/1k;
  I(a,b) <+ ac_stim("ac", 1m);
end
endmodule
""")
AC = "v1 1 0 dc 2 ac 1\nr9 1 0 1k\n.model rr2m rr2\n"
KCL = ("let d = vecmax(mag(@n1[i_a] + i(v1) + v(1)/1k))\n"
       "let s = vecmin(mag(@n1[i_a]))\nlet q = vecmax(abs(imag(@n1[i_a])))\n"
       "let db = vecmax(mag(@n1[i_b] + @n1[i_a]))\nlet di = vecmax(mag(@n1[i] - @n1[i_a]))\n"
       "print d s q db di\n")
rc, out = run("a1.cir", "* ac\n.control\npre_osdi rr2.osdi\n.endc\n" + AC +
                        "n1 1 0 rr2m\n.save @n1[i_a] @n1[i_b] @n1[i] i(v1) v(1)\n"
                        ".control\nac lin 3 1k 1meg\n" + KCL + ".endc\n.end\n")
check("[4] ac: @n1[i_a] is the device's small-signal current, -i(v1) less r9's, at every "
      "frequency (was the 1 mA bias, real and flat)",
      val(out, "d") is not None and val(out, "d") < 1e-12 and val(out, "s") > 4e-4
      and val(out, "q") > 1e-4, out[-500:])
check("[4] ...@n1[i_b] = -@n1[i_a], and the bare @n1[i] is @n1[i_a]",
      val(out, "db") is not None and val(out, "db") < 1e-15 and val(out, "di") < 1e-15, out[-400:])
rc, out = run("a2.cir", "* ac m=2\n.control\npre_osdi rr2.osdi\n.endc\n" + AC +
                        "n1 1 0 rr2m m=2\n.save @n1[i_a] @n1[i_b] @n1[i] i(v1) v(1)\n"
                        ".control\nac lin 3 1k 1meg\n" + KCL + ".endc\n.end\n")
check("[4] m=2: the current doubles with the device, KCL still holds",
      val(out, "d") is not None and val(out, "d") < 1e-12 and val(out, "s") > 8e-4, out[-400:])
rc, out = run("a3.cir", "* ac_stim\n.control\npre_osdi st.osdi\n.endc\nv1 1 0 dc 0 ac 0\n"
                        "r2 2 0 1k\nn1 1 0 stm\nn2 2 0 stm\n.model stm st\n"
                        ".save @n1[i_a] @n2[i_a] i(v1) v(2)\n.control\nac lin 2 1k 2k\n"
                        "let d1 = vecmax(mag(@n1[i_a] + i(v1)))\nlet d2 = vecmax(mag(@n2[i_a] + v(2)/1k))\n"
                        "let s1 = vecmin(mag(@n1[i_a]))\nprint d1 d2 s1\n.endc\n.end\n")
check("[4] an ac_stim() source in the device is part of its current: 1 mA into a node held at "
      "0 V, and KCL against a 1k resistor",
      val(out, "d1") is not None and val(out, "d1") < 1e-15 and val(out, "d2") < 1e-15
      and near(val(out, "s1"), 1e-3), out[-400:])
rc, out = run("a4.cir", "* savecurrents ac\n.control\npre_osdi rr2.osdi\n.endc\n" + AC +
                        "n1 1 0 rr2m\n.option savecurrents\n.control\nac lin 3 1k 1meg\n"
                        "display\n" + KCL + ".endc\n.end\n")
check("[4] `.options savecurrents` in ac keeps the OSDI device's currents, right (E-808 left them "
      "out, as the bias); the built-in r9's is left out, said once",
      "@n1[i_a]" in out and "@r9[i]" not in out and val(out, "d") is not None
      and val(out, "d") < 1e-12
      and "this AC analysis leaves its 1 out (they would hold nothing: a built-in device answers "
          "no current there)" in out, out[-600:])
rc, out = run("a5.cir", "* sp\n.control\npre_osdi rr2.osdi\n.endc\n"
                        "v1 1 0 dc 2 ac 1 portnum 1 z0 50\nn1 1 0 rr2m\n.model rr2m rr2\n"
                        ".option savecurrents\n.control\nsp lin 3 1k 1meg\n"
                        "let d = vecmax(mag(@n1[i_a] + v1#branch))\nlet s = vecmin(mag(@n1[i_a]))\n"
                        "print d s\n.endc\n.end\n")
check("[4] sp: the current is the port's branch current, the device being all the port drives "
      "(was the 0.98 mA bias)",
      val(out, "d") is not None and val(out, "d") < 1e-12 and val(out, "s") > 4e-4, out[-400:])
rc, out = run("a6.cir", "* op\n.control\npre_osdi rr2.osdi\n.endc\n" + AC +
                        "n1 1 0 rr2m\n.control\nop\nprint @n1[i_a]\n.endc\n.end\n")
check("[4] op (control): the bias current, 2 V over 2 kOhm", near(val(out, "@n1[i_a]"), 1e-3),
      out[-300:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
