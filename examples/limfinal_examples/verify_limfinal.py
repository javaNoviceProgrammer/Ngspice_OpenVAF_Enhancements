#!/usr/bin/env python3
"""Enhancements 829 to 831 (F13-F15 of the 2026-10-08 ngspice + OSDI hunt): a
Verilog-A $fatal inside @(final_step), E-543's BJT limiting on a module that is
not a transistor, and `.option saveused` with an @dev[param] in a .meas card.

Enhancement-829 (F13). `@(final_step) $fatal(...)` printed its message and
nothing more: the analysis was not marked aborted, the exit status was 0, and a
$finish or $stop there was dropped in silence. A $fatal anywhere else aborts.
  [1] op, tran, dc: the run is marked failed (exit status 1), the results
      kept; $finish and $stop are noted; a $fatal in @(initial_step) (control);
      hb, which runs outside a job

Enhancement-830 (F14). E-543 gives a module whose terminals are named c,b,e the
built-in BJT junction limiting. A linear three-terminal resistor network took
577 Newton iterations and dynamic gmin stepping for an operating point that
needs 3. A transistor model names its polarity (`type`); a module without one
is no longer limited.
  [2] the linear network converges as with `.option noosdilim`, in op and in a
      transient, and osdilim_verbose says why; a module with `type` is still
      limited (control)

Enhancement-831 (F15). `.option saveused` beside a control block with no
output command stands aside and saves ngspice's default set, which never holds
an @device[param] vector, so `.meas tran p_max max @n2[pw]` failed ("holds 1
point(s) but the analysis produced 2018").
  [3] the @-references the deck reads are saved too; with an output command
      in the block (control); without saveused (control)
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

WORK = tempfile.mkdtemp(prefix="limfinal_")
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


def iters(out):
    m = re.search(r"Total iterations = (\d+)", out)
    return int(m.group(1)) if m else None


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol * max(1e-12, abs(b))


print("Enhancements 829-831: final-step $fatal, BJT limiting, saveused and @dev[param]\n")

# ------------------------------------------------------------- [1] ---
print("[1] Enhancement-829: a $fatal in @(final_step) fails the run")
compile_va("fs", H + """module fs(a, b);
inout a, b; electrical a, b;
parameter integer which = 0;
analog begin
  @(initial_step) if (which == 3) $fatal(0, "fatal in initial_step");
  I(a,b) <+ V(a,b)/1k;
  @(final_step) begin
    if (which == 1) $fatal(0, "fatal in final_step");
    if (which == 2) $finish;
    if (which == 4) $stop;
  end
end
endmodule
""")
FINAL_ERR = "raised $fatal in @(final_step), after the analysis had produced its results"


def fs_deck(which, an, after="print i(v1)"):
    return (f"* fs {which}\n.control\npre_osdi fs.osdi\n.endc\nv1 1 0 1\nn1 1 0 fsm\n"
            f".model fsm fs which={which}\n.control\n{an}\n{after}\n.endc\n.end\n")


rc, out = run("f_op.cir", fs_deck(1, "op"))
check("[1] op, $fatal in @(final_step): the error, 'op simulation(s) aborted', exit status 1 "
      "(was 0); the op's i(v1) = -1 mA is kept",
      FINAL_ERR in out and "op simulation(s) aborted" in out and rc == 1
      and near(val(out, "i(v1)"), -1e-3), f"rc={rc} {out[-400:]}")
rc, out = run("f_tran.cir", fs_deck(1, "tran 1n 3n", "print i(v1)[length(i(v1))-1]"))
check("[1] tran: the same, the last point kept",
      FINAL_ERR in out and "tran simulation(s) aborted" in out and rc == 1
      and near(val(out, "i(v1)[length(i(v1))-1]"), -1e-3), f"rc={rc} {out[-400:]}")
rc, out = run("f_dc.cir", fs_deck(1, "dc v1 0 1 1", "print i(v1)[1]"))
check("[1] dc: the same, the sweep kept",
      FINAL_ERR in out and "dc simulation(s) aborted" in out and rc == 1
      and near(val(out, "i(v1)[1]"), -1e-3), f"rc={rc} {out[-400:]}")
rc, out = run("f_fin.cir", fs_deck(2, "op"))
check("[1] $finish in @(final_step): a note that the analysis had already ended (was silent), "
      "exit status 0",
      "$finish requested by a Verilog-A device in @(final_step); the analysis had already ended" in out
      and rc == 0 and near(val(out, "i(v1)"), -1e-3), f"rc={rc} {out[-300:]}")
rc, out = run("f_stop.cir", fs_deck(4, "op"))
check("[1] $stop in @(final_step): a note, nothing to pause (was silent)",
      "$stop requested by a Verilog-A device in @(final_step); the analysis had already ended, "
      "so there is nothing to pause" in out and rc == 0, f"rc={rc} {out[-300:]}")
rc, out = run("f_init.cir", fs_deck(3, "op"))
check("[1] $fatal in @(initial_step) (control): aborts as before, exit status 1",
      "raised $fatal during the operating point" in out and rc == 1 and FINAL_ERR not in out,
      f"rc={rc} {out[-300:]}")
rc, out = run("f_hb.cir", "* hb\n.control\npre_osdi fs.osdi\n.endc\nV1 a 0 SIN(0 1 1meg)\nR1 a b 1k\n"
                          "n1 b 0 fsm\n.model fsm fs which=1\n.control\nhb 1meg 4\n.endc\n.end\n")
check("[1] hb (outside a job): the error and exit status 1 (was 0)",
      FINAL_ERR in out and rc == 1, f"rc={rc} {out[-300:]}")

# ------------------------------------------------------------- [2] ---
print("[2] Enhancement-830: no BJT limiting for a module without a polarity")
RNET = H + """module rnet(c, b, e);
inout c, b, e; electrical c, b, e;
%s
analog begin I(c,b) <+ V(c,b)/1k; I(b,e) <+ V(b,e)/1k; I(c,e) <+ V(c,e)/10k; end
endmodule
"""
compile_va("rnet", RNET % "")
compile_va("rnett", (RNET % "parameter integer type = 1;").replace("module rnet(", "module rnett("))


def rnet_op(mod, opt=""):
    return run(f"r_{mod}{len(opt)}.cir",
               f"* rnet\n.control\npre_osdi {mod}.osdi\n.endc\nvc c 0 100\nn1 c b 0 rm\n.model rm {mod}\n"
               f"rb b 0 1meg\n{opt}\n.control\nset osdilim_verbose\nop\nprint v(b)\nrusage all\n.endc\n.end\n")


rc, out = rnet_op("rnet")
rc2, out2 = rnet_op("rnet", ".option noosdilim")
check("[2] a linear c,b,e resistor network, op at 100 V: the iterations of `.option noosdilim`, "
      "no gmin stepping, v(b) = 49.975 V (was 577 iterations and dynamic gmin stepping)",
      iters(out) is not None and iters(out) == iters(out2) and iters(out) < 10
      and "gmin stepping" not in out and near(val(out, "v(b)"), 49.975, 1e-4),
      f"{iters(out)} vs {iters(out2)} {val(out, 'v(b)')}")
check("[2] ...and `set osdilim_verbose` says why: c,b,e terminals but no polarity parameter `type`",
      "no polarity parameter `type`" in out, out[-400:])
rc, out = rnet_op("rnett")
check("[2] the same network with `parameter integer type` (control): still given the BJT limiting",
      "BJT limiting" in out and near(val(out, "v(b)"), 49.975, 1e-4), out[-400:])


def rnet_tran(opt=""):
    return run(f"rt{len(opt)}.cir",
               f"* rnet tran\n.control\npre_osdi rnet.osdi\n.endc\nvc c 0 pulse(0 100 1u 1u 1u 5u 20u)\n"
               f"n1 c b 0 rm\n.model rm rnet\nrb b 0 1meg\ncb b 0 1p\n{opt}\n.control\ntran 10n 20u\n"
               f"rusage all\n.endc\n.end\n")


rc, out = rnet_tran()
rc2, out2 = rnet_tran(".option noosdilim")
check("[2] a 0 -> 100 V pulse through it: the transient's Newton iterations equal noosdilim's "
      "(were 40 % more)",
      iters(out) is not None and iters(out) == iters(out2), f"{iters(out)} vs {iters(out2)}")

# ------------------------------------------------------------- [3] ---
print("[3] Enhancement-831: saveused saves the @dev[param] a .meas card reads")
compile_va("ov", H + """module ov(a, b);
inout a, b; electrical a, b;
(* desc="power", units="W" *) real pw;
analog begin I(a,b) <+ V(a,b)/1k; pw = V(a,b)*V(a,b)/1k; end
endmodule
""")
BASE = "v1 1 0 pulse(0 2 0 1n 1n 1u 2u)\nr1 1 0 1k\nn2 1 0 ovm\n.model ovm ov\n"


def su(name, opt, ctl):
    return run(name, f"* saveused\n.control\npre_osdi ov.osdi\n.endc\n{BASE}{opt}"
                     ".meas tran i_max max @r1[i]\n.meas tran p_max max @n2[pw]\n"
                     f".control\n{ctl}\n.endc\n.end\n")


rc, out = su("s1.cir", ".option saveused\n", "tran 1n 2u")
check("[3] saveused, a control block that only runs tran: `.meas ... max @r1[i]` (built-in) = 2 mA "
      "and `max @n2[pw]` (OSDI opvar) = 4 mW (both failed: 'holds 1 point(s)')",
      near(val(out, "i_max"), 2e-3) and near(val(out, "p_max"), 4e-3) and "holds 1 point" not in out,
      out[-400:])
rc, out = su("s2.cir", ".option saveused\n", "tran 1n 2u\nprint v(1)[0]")
check("[3] with an output command in the block (control: saveused acts): the same values",
      near(val(out, "i_max"), 2e-3) and near(val(out, "p_max"), 4e-3), out[-400:])
rc, out = su("s3.cir", "", "tran 1n 2u")
check("[3] without saveused (control): the stock rule stands, an @dev[param] needs a .save",
      "holds 1 point" in out and val(out, "i_max") is None, out[-400:])

print(f"\n{passed}/{checks} checks passed")
sys.exit(0 if passed == checks else 1)
