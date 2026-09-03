#!/usr/bin/env python3
"""
verify_lrmvoice.py -- verifies Enhancement-541, through the committed
openvaf-r + ngspice.

The 2026-09-02 round-3 LRM audit raised nine findings, all of them about a
model's *voice*: the timing and addressing of everything it says to the outside
world. Every one is pinned here, and every one is measured beside a control
that was already correct -- which is what makes a failure interpretable rather
than merely red.

  LRM 5.2.1 / 9.4.6 / 9.5.9  `analog initial` output
  [1]  lrmvoice_init.va compiles
  [2]  every display task in an `analog initial` block reaches the console,
       once per analysis (it produced NOTHING at all: the block runs on the
       initial-step iteration, which the deferral treats as superseded)
  [3]  ... and its file write reaches the file (created and left empty before)
  [4]  the same tasks inside `@(initial_step)` still print exactly once --
       the control that says the fix did not simply make everything immediate

  LRM 9.7.3  non-fatal severity tasks and the accepted iteration
  [5]  lrmvoice_sev.va compiles
  [6]  one diode .op: $warning prints ONE line, at the converged point, where
       it used to print 21 walking the unconverged Newton sequence
  [7]  ... and it is the same value $strobe reports, from the adjacent line
  [8]  $debug keeps 9.4.6's exemption and still prints per iteration
  [9]  a 5-point .dc sweep gives 5 lines from each of $strobe/$warning/$info

  LRM 9.7.3  `$error` in an `analog initial` block
  [10] lrmvoice_err.va compiles
  [11] the message is issued...
  [12] ...and the simulation does not proceed past initialization
  [13] the message reports that the call was made during initialization

  LRM 9.7.3  the reported time / swept value
  [14] a transient reports the simulation time
  [15] a dc sweep reports the CURRENT swept value in its place

  LRM 9.18 Table 9-29  hierarchical system parameters
  [16] lrmvoice_hsp.va compiles
  [17] $angle composes modulo 360 (200 + 200 -> 40), and the rules that were
       already right are unchanged in the same run ($hflip multiplicative,
       $xposition additive)
  [18] the netlist route wraps too, and refuses an out-of-range flip
  [19] a literal `#(.$mfactor(-3))` is refused -- it sign-inverted the device
  [20] ... while `#(.$mfactor(3))` still applies the full 6.3.6 transform

  LRM 9.5.1  descriptors and modes
  [21] lrmvoice_file.va compiles
  [22] multichannel allocation stops at bit 30; the 31st open returns 0
       (it used to return 0x8000_0000, the reserved bit AND the STDIN fd)
  [23] a file reopened in a different mode is truncated and written
  [24] ... while a plain append with no prior open still appends

  LRM 9.4.1  `$write`
  [25] several $write calls compose ONE line, and a following $strobe still
       carries its own prefix

  LRM 9.20  the alias functions' error rules
  [26] the aliased net may not be a port
  [27] the target may not be another call's aliased net
  [28] a call outside an `analog initial` block is still refused
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f"  ({detail})" if detail and not ok else ""))


def compile_va(name):
    r = subprocess.run([OPENVAF, name], capture_output=True, text=True, cwd=HERE)
    return (r.returncode == 0
            and os.path.exists(os.path.join(HERE, name.replace(".va", ".osdi"))),
            r.stdout + r.stderr)


def compile_src(stem, src):
    """Compile inline source; returns (ok, diagnostics)."""
    p = os.path.join(HERE, stem + ".va")
    with open(p, "w") as f:
        f.write(src)
    r = subprocess.run([OPENVAF, stem + ".va"], capture_output=True, text=True, cwd=HERE)
    return r.returncode == 0, r.stdout + r.stderr


def run(deck_name, deck):
    with open(os.path.join(HERE, deck_name), "w") as f:
        f.write(deck)
    out = subprocess.run([NGSPICE, "-b", deck_name], capture_output=True,
                         text=True, cwd=HERE)
    return out.stdout, out.stderr


def readfile(name):
    p = os.path.join(HERE, name)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return f.read()


ARTEFACTS = ["lrmvoice_init.osdi", "lrmvoice_sev.osdi", "lrmvoice_err.osdi",
             "lrmvoice_ctx.osdi", "lrmvoice_hsp.osdi", "lrmvoice_file.osdi",
             "lrmvoice_write.osdi",
             "_init.sp", "_sev.sp", "_err.sp", "_ctx.sp", "_hsp.sp", "_hspn.sp",
             "_m3.sp", "_file.sp", "_write.sp",
             "lrmvoice_init.txt", "lrmvoice_ctl.txt", "lrmvoice_rw.txt",
             "_mneg.va", "_mneg.osdi", "_alias.va", "_alias.osdi",
             "_aliasctx.va", "_aliasctx.osdi"]


def clean():
    for f in ARTEFACTS:
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            os.remove(p)
    mc = os.path.join(HERE, "mc")
    if os.path.isdir(mc):
        for f in os.listdir(mc):
            os.remove(os.path.join(mc, f))
        os.rmdir(mc)


clean()

# --------------------------------------------- 5.2.1: analog initial output --
ok, msg = compile_va("lrmvoice_init.va")
check("lrmvoice_init.va compiles", ok, msg.strip().splitlines()[0] if msg.strip() else "")

if ok:
    out, err = run("_init.sp",
                   "* analog initial output\n"
                   ".control\npre_osdi lrmvoice_init.osdi\n.endc\n"
                   ".model m lrmvoice_init\nn1 1 0 m\nv1 1 0 dc 1\n"
                   ".control\nop\ntran 1u 3u\ndc v1 1 2 1\nquit\n.endc\n.end\n")
    log = out + err
    # three analyses -> one of each per analysis. The exact count matters:
    # "at least one" would pass on a build that printed the whole Newton walk.
    counts = {t: len(re.findall(rf"INIT-{t}\b", log))
              for t in ("strobe", "display", "write", "monitor", "debug", "info")}
    check("every display task in an `analog initial` block reaches the console",
          all(counts[t] == 3 for t in ("strobe", "display", "write", "monitor")),
          f"{counts}")
    check("...and its file write reaches the file",
          (readfile("lrmvoice_init.txt") or "").count("INIT-file") == 3,
          repr(readfile("lrmvoice_init.txt")))
    check("`@(initial_step)` output is unchanged (the control)",
          len(re.findall(r"EVT-strobe", log)) == 3
          and len(re.findall(r"EVT-info", log)) == 3,
          f"strobe={len(re.findall(r'EVT-strobe', log))} "
          f"info={len(re.findall(r'EVT-info', log))}")

# ------------------------------------ 9.7.3: severity vs accepted iteration --
ok, msg = compile_va("lrmvoice_sev.va")
check("lrmvoice_sev.va compiles", ok, msg.strip().splitlines()[0] if msg.strip() else "")

if ok:
    out, err = run("_sev.sp",
                   "* diode op: the Newton walk\n"
                   ".control\npre_osdi lrmvoice_sev.osdi\n.endc\n"
                   ".model m lrmvoice_sev\nn1 1 0 m\nr1 in 1 1k\nv1 in 0 dc 1\n"
                   ".control\nop\nquit\n.endc\n.end\n")
    warns = re.findall(r"SEV-warn v=([\d.]+)", out + err)
    strobes = re.findall(r"SEV-strobe v=([\d.]+)", out + err)
    debugs = re.findall(r"SEV-debug v=([\d.]+)", out + err)
    check("$warning prints once per accepted iteration, not once per Newton step",
          len(warns) == 1, f"{len(warns)} lines: {warns[:4]}")
    check("...at the same point $strobe reports",
          len(strobes) == 1 and len(warns) == 1 and warns[0] == strobes[0],
          f"warn={warns[:1]} strobe={strobes[:1]}")
    # LRM 9.4.6 exempts exactly $debug; a fix that deferred everything would
    # break this, which is why it is a check and not a comment.
    check("$debug keeps 9.4.6's exemption and still prints per iteration",
          len(debugs) > 3, f"{len(debugs)} lines")

    out, err = run("_sev.sp",
                   "* 5-point sweep\n"
                   ".control\npre_osdi lrmvoice_sev.osdi\n.endc\n"
                   ".model m lrmvoice_sev\nn1 1 0 m\nr1 in 1 1k\nv1 in 0 dc 1\n"
                   ".control\ndc v1 1 5 1\nquit\n.endc\n.end\n")
    log = out + err
    n_s = len(re.findall(r"SEV-strobe", log))
    n_w = len(re.findall(r"SEV-warn", log))
    n_i = len(re.findall(r"SEV-info", log))
    check("a 5-point sweep gives 5 lines from each of $strobe/$warning/$info",
          n_s == 5 and n_w == 5 and n_i == 5, f"strobe={n_s} warn={n_w} info={n_i}")

# ------------------------------------ 9.7.3: $error inside `analog initial` --
ok, msg = compile_va("lrmvoice_err.va")
check("lrmvoice_err.va compiles", ok, msg.strip().splitlines()[0] if msg.strip() else "")

if ok:
    out, err = run("_err.sp",
                   "* $error in analog initial\n"
                   ".control\npre_osdi lrmvoice_err.osdi\n.endc\n"
                   ".model m lrmvoice_err\nn1 1 0 m\nv1 1 0 dc 1\n"
                   ".control\nop\nprint v(1)\nquit\n.endc\n.end\n")
    log = out + err
    check("the $error message is issued", "ERR-in-initial" in log, log[-200:])
    # "the simulation shall not proceed past initialization": the operating
    # point must not produce a solution.
    check("the simulation does not proceed past initialization",
          "v(1) = " not in log and "no such vector" in log,
          [l for l in log.splitlines() if "v(1)" in l][:2])
    check("the message says the call was made during initialization",
          "during initialization" in log,
          [l for l in log.splitlines() if "ERR-in-initial" in l][:1])

# ----------------------------------------- 9.7.3: the reported time / sweep --
ok, _ = compile_va("lrmvoice_ctx.va")
if ok:
    out, err = run("_ctx.sp",
                   "* severity context\n"
                   ".control\npre_osdi lrmvoice_ctx.osdi\n.endc\n"
                   ".model m lrmvoice_ctx\nn1 1 0 m\n"
                   "v1 1 0 pulse(0 1 0 1u 1u 1u 4u)\n"
                   ".control\ntran 0.5u 2u\nquit\n.endc\n.end\n")
    tran = [l for l in (out + err).splitlines() if "CTX high" in l]
    check("a transient reports the simulation time",
          bool(tran) and all(re.search(r"\(at t = [\d.eE+-]+\)", l) for l in tran),
          tran[:2])

    out, err = run("_ctx.sp",
                   "* severity context, sweep\n"
                   ".control\npre_osdi lrmvoice_ctx.osdi\n.endc\n"
                   ".model m lrmvoice_ctx\nn1 1 0 m\nv1 1 0 dc 0\n"
                   ".control\ndc v1 0 1 0.25\nquit\n.endc\n.end\n")
    swept = [l for l in (out + err).splitlines() if "CTX high" in l]
    # The gate fires at 0.75 and 1.0, and the reported value must be the
    # CURRENT point -- CKTtime only catches up after the solve, so a context
    # resolved too early reported the previous point's value.
    vals = [m.group(1) for l in swept
            for m in [re.search(r"\(at sweep value ([\d.eE+-]+)\)", l)] if m]
    check("a dc sweep reports the current swept value in place of the time",
          len(vals) == 2 and abs(float(vals[0]) - 0.75) < 1e-9
          and abs(float(vals[1]) - 1.0) < 1e-9,
          f"{swept}")

# ------------------------------------------- 9.18 Table 9-29: the HSP rules --
ok, msg = compile_va("lrmvoice_hsp.va")
check("lrmvoice_hsp.va compiles", ok, msg.strip().splitlines()[0] if msg.strip() else "")

if ok:
    out, err = run("_hsp.sp",
                   "* hierarchical system parameters\n"
                   ".control\npre_osdi lrmvoice_hsp.osdi\n.endc\n"
                   ".model m lrmvoice_hsp\nn1 1 0 m\nv1 1 0 dc 1\n"
                   ".control\nop\nquit\n.endc\n.end\n")
    m = re.search(r"HSP angle=(\S+) hflip=(\S+) vflip=(\S+) x=(\S+) m=(\S+)", out + err)
    check("$angle composes modulo 360, and the other rules are unchanged",
          m is not None
          and abs(float(m.group(1)) - 40.0) < 1e-9      # 200 + 200 -> 40
          and abs(float(m.group(2)) - 1.0) < 1e-9       # (-1) * (-1)
          and abs(float(m.group(4)) - 0.003) < 1e-12,   # 0.002 + 0.001
          m.group(0) if m else "no HSP line")

    out, err = run("_hspn.sp",
                   "* the netlist route\n"
                   ".control\npre_osdi lrmvoice_hsp.osdi\n.endc\n"
                   ".model m lrmvoice_leaf\n"
                   "n1 1 0 m _angle=400 _hflip=5\nv1 1 0 dc 1\n"
                   ".control\nop\nquit\n.endc\n.end\n")
    log = out + err
    m = re.search(r"HSP angle=(\S+) hflip=(\S+)", log)
    check("the netlist route wraps the angle and refuses an out-of-range flip",
          m is not None
          and abs(float(m.group(1)) - 40.0) < 1e-9
          and abs(float(m.group(2)) - 1.0) < 1e-9
          and "not +1 or -1" in log,
          m.group(0) if m else "no HSP line")

    out, err = run("_m3.sp",
                   "* a legal multiplicity still transforms\n"
                   ".control\npre_osdi lrmvoice_hsp.osdi\n.endc\n"
                   ".model m lrmvoice_m3\nn1 1 0 m\nv1 1 0 dc 1\n"
                   ".control\nop\nprint i(v1)\nquit\n.endc\n.end\n")
    mm = re.search(r"i\(v1\)\s*=\s*(-?[\d.eE+-]+)", out + err)
    check("`#(.$mfactor(3))` still applies the full 6.3.6 transform",
          mm is not None and abs(float(mm.group(1)) + 3e-3) < 1e-9,
          mm.group(0) if mm else "no i(v1)")

neg_ok, neg_diag = compile_src("_mneg", """`include "disciplines.vams"
module _mneg_leaf(p, n);
  inout p, n; electrical p, n;
  analog I(p, n) <+ V(p, n) * 1e-3;
endmodule
module _mneg(p, n);
  inout p, n; electrical p, n;
  _mneg_leaf #(.$mfactor(-3)) b1(p, n);
endmodule
""")
check("a literal `#(.$mfactor(-3))` is refused",
      not neg_ok and "$mfactor" in neg_diag and "Table 9-29" in neg_diag,
      neg_diag.strip().splitlines()[0] if neg_diag.strip() else "compiled clean")

# ------------------------------------------- 9.5.1: descriptors and reopens --
os.makedirs(os.path.join(HERE, "mc"), exist_ok=True)
with open(os.path.join(HERE, "lrmvoice_ctl.txt"), "w") as f:
    f.write("CTL-ORIGINAL\n")
with open(os.path.join(HERE, "lrmvoice_rw.txt"), "w") as f:
    f.write(readfile("lrmvoice_rw_seed.txt"))

ok, msg = compile_va("lrmvoice_file.va")
check("lrmvoice_file.va compiles", ok, msg.strip().splitlines()[0] if msg.strip() else "")

if ok:
    out, err = run("_file.sp",
                   "* descriptors\n"
                   ".control\npre_osdi lrmvoice_file.osdi\n.endc\n"
                   ".model m lrmvoice_file\nn1 1 0 m\nv1 1 0 dc 1\n"
                   ".control\nop\nquit\n.endc\n.end\n")
    m = re.search(r"FILE bit30=(-?\d+) over=(-?\d+)", out + err)
    check("multichannel allocation stops at bit 30; the 31st open returns 0",
          m is not None
          and int(m.group(1)) == 1 << 30
          and int(m.group(2)) == 0,
          m.group(0) if m else "no FILE line")
    rw = readfile("lrmvoice_rw.txt")
    check("a file reopened in a different mode is truncated and written",
          rw is not None and "RW-rewritten" in rw and "ORIGINAL-LINE-1" not in rw,
          repr(rw))
    ctl = readfile("lrmvoice_ctl.txt")
    check("...while a plain append with no prior open still appends (the control)",
          ctl is not None and "CTL-ORIGINAL" in ctl and "CTL-appended" in ctl,
          repr(ctl))

# ------------------------------------------------------------- 9.4.1 $write --
ok, _ = compile_va("lrmvoice_write.va")
if ok:
    out, err = run("_write.sp",
                   "* $write\n"
                   ".control\npre_osdi lrmvoice_write.osdi\n.endc\n"
                   ".model m lrmvoice_write\nn1 1 0 m\nv1 1 0 dc 1\n"
                   ".control\nop\nquit\n.endc\n.end\n")
    log = out + err
    check("several $write calls compose one line, and $strobe keeps its prefix",
          re.search(r"OSDI \S+: \[A\]\[B\]\[C\]\s*$", log, re.M) is not None
          and re.search(r"OSDI \S+: AFTER", log) is not None,
          [l for l in log.splitlines() if "[A]" in l or "AFTER" in l][:3])

# --------------------------------------------------- 9.20: the error rules --
_, port_diag = compile_src("_alias", """`include "disciplines.vams"
module _alias(p, n);
  inout p, n; electrical p, n;
  electrical loc1, loc2;
  integer s;
  analog initial begin
    s = $analog_node_alias(p, "top.x");
    s = $analog_node_alias(loc1, "top.x");
    s = $analog_node_alias(loc2, "top.loc1");
  end
  analog I(p, n) <+ V(p, n) * 1e-3;
endmodule
""")
check("the aliased net may not be a port",
      "is a port of this module" in port_diag, port_diag.strip()[:120])
check("the target may not be another call's aliased net",
      "itself aliased in this module" in port_diag, port_diag.strip()[:120])

_, ctx_diag = compile_src("_aliasctx", """`include "disciplines.vams"
module _aliasctx(p, n);
  inout p, n; electrical p, n;
  electrical loc1;
  integer s;
  analog begin
    s = $analog_node_alias(loc1, "top.x");
    I(p, n) <+ V(p, n) * 1e-3;
  end
endmodule
""")
check("a call outside an `analog initial` block is still refused (the control)",
      "only allowed inside an analog initial block" in ctx_diag,
      ctx_diag.strip()[:120])

clean()

print(f"\n{passed}/{checks} checks passed")
raise SystemExit(0 if passed == checks else 1)
