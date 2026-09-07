#!/usr/bin/env python3
"""
verify_autoopts.py -- Enhancement-572: what a dig into `.option autobus`,
`autoadapt`, `saveused` and `automc` (osdimc) turned up, pinned on BOTH solvers.

  autobus    a ONE-BIT bus port (`inout [0:0] a`) has as many terminals as ports,
             so `N1 a b bus1` in shorthand was taken as spelled out and bound the
             token `a` as the node `a` -- a different node from `a[0]` -- while
             every other width expanded. It is indexed now. And a bus base the
             deck ALSO uses as a plain node (`Rx a 0 1k` beside `N1 a b busdev`)
             is named: the two are different nodes.
  saveused   the deck's own output cards -- `.meas`, `.print`, `.plot`, `.four`
             -- were not scanned, so `.meas tran vmax max v(out)` beside a
             control block that printed only v(in) failed with "no such vector".
  autoadapt  a control block that still refers to the bits of a node the option
             split (`print v(b[0])` after `b` became `b_f`/`b_r`) failed as
             "vector b is not available"; the split is now named.
  automc     `mcseed=1.5` and `mcseed=abc` silently became seed 1; they are
             said now. The trial rules are pinned as the documented behaviour:
             one trial per run-class command, a whole `sweep` being one trial,
             `op` and a following `tran` two, `montecarlo` one per sample.
  all four   the documented OFF spellings (`nosaveused`, `noautobus`,
             `noautoadapt`, `noautomc`, `noosdimc`) were honoured but reported
             as unknown options.

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))          # the examples/ dir (holds _setup.py)
from _setup import NG as NGSPICE, VAF as OPENVAF
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers

checks = 0
passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def ngspice(deck, name="_o.cir"):
    path = os.path.join(HERE, name)
    with open(path, "w") as fh:
        fh.write(deck)
    r = subprocess.run([NGSPICE, "-b", name], cwd=HERE, capture_output=True, text=True, timeout=300)
    return r.stdout + r.stderr


def scalars(out):
    vals = {}
    for line in out.splitlines():
        m = re.match(r"\s*([\w\(\)\[\]#@.,-]+)\s*=\s*([-+0-9.eE]+)", line)
        if m:
            try:
                vals[m.group(1).lower()] = float(m.group(2))
            except ValueError:
                pass
    return vals


def allvals(out, name):
    """every printed value of `name`, in order"""
    return [float(m) for m in re.findall(r"^\s*" + re.escape(name) + r"\s*=\s*([-+0-9.eE]+)", out, re.M)]


def near(a, b, tol=1e-6):
    return a is not None and abs(a - b) <= tol * max(1.0, abs(b))


def build(va_path, name):
    osdi = os.path.join(HERE, name + ".osdi")
    r = subprocess.run([OPENVAF, va_path, "-o", osdi], cwd=HERE, capture_output=True, text=True, timeout=300)
    return os.path.isfile(osdi), r.stdout + r.stderr


def deck(title, body, control, options=""):
    return f"* {title}\n{options}{body}\n.control\n{control}\n.endc\n.end\n"


UNKNOWN = "unknown option"


def main():
    print("Enhancement-572: autobus / autoadapt / saveused / automc, the dig")
    ex = os.path.dirname(HERE)
    ok1, l1 = build(os.path.join(HERE, "bus1.va"), "bus1")
    ok2, l2 = build(os.path.join(ex, "autobus_examples", "busdev.va"), "busdev")
    ok3, l3 = build(os.path.join(ex, "autoadapt_examples", "adapt.va"), "adapt")
    ok4, l4 = build(os.path.join(ex, "osdimc_examples", "smcres.va"), "smcres")
    check("the four Verilog-A models compile", ok1 and ok2 and ok3 and ok4, (l1 + l2 + l3 + l4)[-200:] if not (ok1 and ok2 and ok3 and ok4) else "")
    if not (ok1 and ok2 and ok3 and ok4):
        sys.exit(1)

    print("\n[autobus] a one-bit bus port")
    body = "v0 a[0] 0 1\nn1 a b bus1\nn2 a[0] b2 bus1\nrl b 0 1k\nrl2 b2 0 1k\n.model bus1 bus1"
    out = ngspice(deck("one bit", body, "pre_osdi bus1.osdi\nop\nprint v(b) v(b2)", ".option autobus\n"))
    s = scalars(out)
    check("`n1 a b bus1` for `inout [0:0] a` reads like the explicit `n1 a[0] b bus1`: v(b) = v(b2) = 0.5 (was 0: `a` bound as a plain node)",
          near(s.get("v(b)"), 0.5) and near(s.get("v(b2)"), 0.5), f"v(b)={s.get('v(b)')} v(b2)={s.get('v(b2)')}")
    body = "v0 a[0] 0 1\nn1 0 b bus1\nrl b 0 1k\n.model bus1 bus1"
    out = ngspice(deck("one bit ground", body, "pre_osdi bus1.osdi\nop\nprint v(b)", ".option autobus\n"))
    check("ground on a one-bit bus port stays ground: v(b) = 0", near(scalars(out).get("v(b)"), 0.0, 1e-9), f"v(b)={scalars(out).get('v(b)')}")
    body = ".subckt s1 p q\nn1 p q bus1\n.ends\nv0 x[0] 0 1\nx1 x y s1\nrl y 0 1k\n.model bus1 bus1"
    out = ngspice(deck("one bit subckt", body, "pre_osdi bus1.osdi\nop\nprint v(y)", ".option autobus\n"))
    check("through a subcircuit formal: v(y) = 0.5", near(scalars(out).get("v(y)"), 0.5), f"v(y)={scalars(out).get('v(y)')}")

    print("\n[autobus] a bus base the deck also uses as a plain node")
    LADDER = "v0 a[0] 0 1\nv1 a[1] 0 2\nv2 a[2] 0 3\nv3 a[3] 0 4\nv4 a[4] 0 5\n"
    out = ngspice(deck("base reuse", LADDER + "n1 a b busdev\nrl b 0 1k\nrx a 0 1k\n.model busdev busdev",
                       "pre_osdi busdev.osdi\nop\nprint v(b) v(a) v(a[0])", ".option autobus\n"))
    check("`rx a 0 1k` beside `n1 a b busdev` is named: 'a' expanded to 5 bits a[0] .., also a plain node",
          "instance n1: 'a' was expanded to the 5 bus bits a[0]" in out and "also uses 'a' as a plain node" in out
          and near(scalars(out).get("v(a)"), 0.0, 1e-9) and near(scalars(out).get("v(a[0])"), 1.0), "")
    out = ngspice(deck("no reuse", LADDER + "n1 a b busdev\nrl b 0 1k\n.model busdev busdev",
                       "pre_osdi busdev.osdi\nop\nprint v(b)", ".option autobus\n"))
    check("...and nothing is said when 'a' is only the bus", "was expanded to" not in out and near(scalars(out).get("v(b)"), 1.212766, 1e-5), "")
    out = ngspice(deck("kicad reuse", LADDER.replace("[", "_").replace("]", "_") + "n1 a b busdev\nrl b 0 1k\nrx a 0 1k\n.model busdev busdev",
                       "pre_osdi busdev.osdi\nop\nprint v(b)", ".option autobus=kicad\n"))
    check("under autobus=kicad the note spells the bit a_0_", "5 bus bits a_0_" in out and "Write a_0_ to reach a bit" in out, "")

    print("\n[saveused] the deck's own output cards")
    RC = "v1 in 0 pulse(0 1 0 1n 1n 1u 2u)\nr1 in out 1k\nc1 out 0 100p"
    out = ngspice(deck("dot meas", RC + "\n.meas tran vmax max v(out)\n.tran 10n 3u", "run\nprint v(in)[10]\ndisplay", ".option saveused\n"))
    check(".meas tran vmax max v(out) beside a block that prints only v(in): the measure works, out is kept",
          "no such vector" not in out and near(scalars(out).get("vmax"), 0.999955, 1e-4) and re.search(r"^\s*out\s*:", out, re.M) is not None,
          f"vmax={scalars(out).get('vmax')}")
    out = ngspice(deck("dot print", RC + "\n.print tran v(out)\n.tran 1u 3u", "run\nprint v(in)[1]", ".option saveused\n"))
    check(".print tran v(out): the table is filled, no 'not available'",
          "not available" not in out and re.search(r"^\d+\t[-+0-9.e]+\t[-+0-9.e]+", out, re.M) is not None, "")
    out = ngspice(deck("dot four", "v1 in 0 sin(0 1 1k)\nr1 in out 1k\nc1 out 0 100n\n.four 1k v(out)\n.tran 10u 2m", "run\nprint v(in)[3]", ".option saveused\n"))
    check(".four 1k v(out): the Fourier analysis runs, no 'no such vector'", "Fourier analysis for v(out)" in out and "no such vector" not in out, "")
    out = ngspice(deck("still restricts", "v1 in 0 1\nr1 in out 1k\nr2 out 0 1k", "op\nprint v(in)\ndisplay", ".option saveused\n"))
    check("the option still restricts: a block printing v(in) keeps in and not out",
          re.search(r"^\s*in\s*:", out, re.M) is not None and re.search(r"^\s*out\s*:", out, re.M) is None, "")

    print("\n[autoadapt] a control block that still names the split node")
    AD = ("v0 a[0] 0 1\nv1 a[1] 0 2\nv2 a[2] 0 3\nv3 a[3] 0 4\nn1 a b chan\nn2 b c chan\n"
          "rl0 c[0] 0 1k\nrl1 c[1] 0 1k\nrl2 c[2] 0 1k\nrl3 c[3] 0 1k\n.model chan chan\n.model amod adapter")
    out = ngspice(deck("adapt ctrl ref", AD, "pre_osdi adapt.osdi\nop\nprint v(c[0]) v(b[0])", ".option autobus autoadapt adapter=amod\n"))
    check("`print v(b[0])` after b became b_f/b_r: the split is named, the line quoted, the cure given",
          "autoadapt split node 'b' into 'b_f' and 'b_r'" in out and "print v(c[0]) v(b[0])" in out and "refer to b_f or b_r instead" in out, "")
    out = ngspice(deck("adapt ok ref", AD, "pre_osdi adapt.osdi\nop\nprint v(c[0]) v(b_f[0])", ".option autobus autoadapt adapter=amod\n"))
    s = scalars(out)
    check("...and nothing is said when the block refers to b_f: v(c[0]) = 0.32787, v(b_f[0]) = 0.67213",
          "autoadapt split node" not in out and near(s.get("v(c[0])"), 0.3278689, 1e-5) and near(s.get("v(b_f[0])"), 0.6721311, 1e-5),
          f"v(c[0])={s.get('v(c[0])')}")

    print("\n[automc] seeds and trials")
    MC = "v1 a 0 1\nn1 a b rm\nrload b 0 1k\n.model rm smcres"
    ref = ngspice(deck("seed 1", MC, "pre_osdi smcres.osdi\nop\nop\nprint @rm[r]", ".option osdimc mcseed=1\n"))
    r1 = scalars(ref).get("@rm[r]")
    out = ngspice(deck("seed 1.5", MC, "pre_osdi smcres.osdi\nop\nop\nprint @rm[r]", ".option osdimc mcseed=1.5\n"))
    check("mcseed=1.5 is said and truncated: 'is not an integer; using 1', draws equal to mcseed=1's",
          "mcseed=1.5 is not an integer; using 1" in out and near(scalars(out).get("@rm[r]"), r1, 1e-9), f"r={scalars(out).get('@rm[r]')} ref={r1}")
    out = ngspice(deck("seed abc", MC, "pre_osdi smcres.osdi\nop\nop\nprint @rm[r]", ".option osdimc mcseed=abc\n"))
    check("mcseed=abc is said: 'is not a number; using the default seed 1'", "mcseed=abc is not a number; using the default seed 1" in out and near(scalars(out).get("@rm[r]"), r1, 1e-9), "")
    loop = ngspice(deck("op loop", MC, "pre_osdi smcres.osdi\n" + "op\nprint @rm[r] v(b)\n" * 4, ".option osdimc mcseed=7\n"))
    seq = allvals(loop, "@rm[r]")
    vb = allvals(loop, "v(b)")
    check("reference: four `op`s are trials 1..4, the first nominal", len(seq) == 4 and near(seq[0], 1000.0, 1e-9) and len(set(seq)) == 4, f"{seq}")
    out = ngspice(deck("sweep trial", MC, "pre_osdi smcres.osdi\nop\nop\nprint v(b)\nsweep @rload[resistance] lin 2 1k 1k -analysis op -output v(b)\nprint v(b)\nop\nprint v(b)",
                       ".option osdimc mcseed=7\n"))
    vals = allvals(out, "v(b)")
    rows = [float(m) for m in re.findall(r"^[01]\t([-+0-9.e]+)", out, re.M)]
    check("a `sweep` is ONE trial: after two ops (trial 2) both its points use trial 3, and the next op is trial 4",
          len(vb) == 4 and len(vals) == 2 and len(rows) == 2 and near(vals[0], vb[1], 1e-9)
          and near(rows[0], vb[2], 1e-9) and near(rows[1], vb[2], 1e-9) and near(vals[1], vb[3], 1e-9), f"scalars={vals} sweep={rows} ref={vb}")
    out = ngspice(deck("op then tran", MC, "pre_osdi smcres.osdi\nop\nop\nprint @rm[r]\ntran 1u 2u\nprint @rm[r]", ".option osdimc mcseed=7\n"))
    vals = allvals(out, "@rm[r]")
    check("`op` then `tran` in one block are two trials: the tran runs at trial 3's value, not the op's",
          len(vals) == 2 and near(vals[0], seq[1], 1e-9) and near(vals[1], seq[2], 1e-9), f"{vals}")
    out = ngspice(deck("mc warm", MC, "pre_osdi smcres.osdi\nmontecarlo 6 -warm -seed 1 -analysis op -spec v(b) -min 0.4999 -max 0.5001", ".option osdimc mcseed=7\n"))
    check("`montecarlo -warm` draws every sample: 0 of 6 inside a +-0.02% band around the nominal", re.search(r"\(\s*0\s*/\s*6\s*pass\)", out) is not None, "")
    for opt in ("osdimc=0", "automc=no", "noosdimc"):
        out = ngspice(deck("off " + opt, MC, "pre_osdi smcres.osdi\nop\nop\nprint @rm[r]", f".option {opt} mcseed=7\n"))
        check(f".option {opt}: nothing varies, and no 'unknown option'", near(scalars(out).get("@rm[r]"), 1000.0, 1e-9) and UNKNOWN not in out, "")

    print("\n[all four] the OFF spellings are registered")
    for opt in ("nosaveused", "noautobus", "noautoadapt", "noautomc"):
        out = ngspice(deck("off " + opt, "v1 a 0 1\nr1 a 0 1k", "op\nprint v(a)", f".option {opt}\n"))
        check(f".option {opt} draws no 'unknown option' warning", UNKNOWN not in out and near(scalars(out).get("v(a)"), 1.0), "")
    out = ngspice(deck("control", "v1 a 0 1\nr1 a 0 1k", "op\nprint v(a)", ".option nosuchoption572\n"))
    check("...while a genuinely unknown name is still flagged (control)", UNKNOWN in out, "")

    for f in ("_o.cir", "bus1.osdi", "busdev.osdi", "adapt.osdi", "smcres.osdi"):
        try:
            os.remove(os.path.join(HERE, f))
        except OSError:
            pass
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


if __name__ == "__main__":
    main()
