#!/usr/bin/env python3
"""Enhancement-394: six defects from a one-hour hunt aimed at ngspice + OSDI.

Five of the six are one shape: **it works for a built-in device and silently
does not for an OSDI (compiled Verilog-A) one**. Every check below therefore
carries a built-in control in the same netlist, because "the OSDI number
changed" is not evidence -- "the OSDI number now equals what the equivalent
built-in network gives" is.

  [1] THE SUBCIRCUIT MULTIPLIER NEVER REACHED AN OSDI DEVICE.

      `X1 a 0 sub m=3` scales a built-in resistor or diode inside `sub`
      exactly; an OSDI device in the same position contributed 1x, in DC, AC,
      transient, thermal noise, flicker noise, charge and S-parameters alike.
      `$mfactor` read inside the model was always the device's own `m`, never
      multiplied by any enclosing X, at any nesting depth.

      The cause was one character. `inp_fix_subckt_multiplier` appends
      ` m={m}` to each device line inside a multiplied subcircuit, skipping
      lines whose first letter names a device that has no multiplier -- and
      'n' was in that skip list. 'N' is the OSDI dispatcher. PDKs wrap compact
      models in multiplied subcircuits, so this under-counted device area with
      no diagnostic at all.

      'N' also hosts the native n-port, which genuinely has no multiplier;
      it now accepts `m` and says so when it is not 1, rather than the
      multiplier being dropped in silence there too.

  [2] NESTED SUBCIRCUIT MULTIPLIERS DID NOT COMPOUND -- for built-in devices
      as well, so this one is not OSDI-specific at all. Only the OUTERMOST
      `m=` survived: 2 around 3 gave 2x, and 2x3x5 gave 2x instead of 30x.
      The append path multiplied an existing `m=` only in HSPICE compatibility
      mode; everywhere else it appended a second ` m={m}` which won, discarding
      the inner value. Multiplying is the SPICE meaning and is what the HSPICE
      path already did.

  [3] INSTANCE `temp=` WAS NOT CONVERTED FROM CELSIUS TO KELVIN.

      Every built-in adds CONSTCtoK when the parameter is set (`dioparam.c`:
      `DIOtemp = value->rValue + CONSTCtoK`), and ngspice's own OSDI code
      acknowledges the convention where it hands `tnom` to the model as
      `CKTnomTemp - CONSTCtoK`. The OSDI path stored the raw number and used it
      as the Kelvin device temperature, so `temp=75` reached the model as
      $temperature = 75 and $vt = 6.5 mV instead of 30 mV. On a Verilog-A
      diode that is **-2.5e+16 A where the correct answer is -4.85e-07 A**.
      `temp=0` made $vt exactly zero, so `limexp(V/$vt)` divided by zero and
      the operating point failed outright; `temp=-40` produced a negative
      absolute temperature and a negative thermal voltage.

      `temp` also STACKED with `dtemp` (75+10 meaning 85). It overrides now,
      as it does for every built-in -- `restemp.c` forces `dtemp = 0` and says
      "Instance temperature specified, dtemp ignored", which is now the message
      an OSDI instance prints too.

  [4] `.option scale` NEVER REACHED AN OSDI MODEL. Each built-in applies it in
      its own parameter setter (`b3par.c` and friends call
      `cp_getvar("scale")`); nothing scales an OSDI instance parameter, because
      the OSDI ABI carries no units. The Verilog-A way to receive it is
      `$simparam("scale")` -- which real models ask for, including the EKV
      model in this project's own VA_TEST corpus -- and ngspice answered
      nothing, so the model silently used 1.0 while a built-in MOSFET in the
      same netlist scaled. `scale` is now served.

  [5] `.options savecurrents` PRODUCED NOTHING FOR OSDI DEVICES. `@r1[i]`
      appeared for a built-in resistor and the compact model beside it produced
      no current vector at all; `@n1[i]` did not exist, so the only way to see
      a terminal current was to edit the model. Every OSDI instance now
      answers to `i_<terminal>`, and a two-terminal one also to the bare `i`
      that R/C/L use. The current is the device's own stamp into that node's
      KCL row -- the resistive residual plus, in a transient, the integrated
      charge derivative -- so it is exact, not a finite difference.

  [6] `$simparam$str("analysis_name")` CONTRADICTED `analysis()`.

      Enhancement-53 taught the ANALYSIS_* flags to consult the running job so
      that an AC job's operating-point phase reports `ac`. The string channel
      was left on the old CKTmode-only derivation, and `OSDIfinalStep` had a
      third derivation of its own (testing MODEAC without MODEINITSMSIG). Two
      contradictions followed, inside a single model evaluation: a plain `op`
      reported `name=ac` while `analysis("ac")` was false, and an AC job's op
      phase reported `name=dc` while `analysis("ac")` was true. All three now
      come from one derivation.

WHAT THE ACCEPT HALF IS GUARDING. [1] and [2] change how EVERY multiplied
subcircuit is expanded, for built-in devices too, so the built-in cases matter
more than the OSDI ones: a single level, an explicit inner `m`, a subcircuit
that declares `m` as a parameter (where X's `m` binds the parameter and must
NOT also multiply), and the unmultiplied case.
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE  # noqa: E402

checks = passed = 0
HDR = '`include "disciplines.vams"\n`include "constants.vams"\n'


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail else ""))


def build(src, tag):
    d = os.path.join(HERE, "_op_%s" % tag)
    shutil.rmtree(d, ignore_errors=True)
    os.makedirs(d)
    open(os.path.join(d, "m.va"), "w").write(src)
    env = dict(os.environ, RAYON_NUM_THREADS="1", TMPDIR=d)
    r = subprocess.run([OPENVAF, os.path.join(d, "m.va"), "-o", os.path.join(d, "m.osdi")],
                       capture_output=True, text=True, env=env, cwd=d, timeout=900)
    return d, r.returncode, (r.stdout or "") + (r.stderr or "")


def run(d, deck, guard=45):
    open(os.path.join(d, "q.cir"), "w").write(deck)
    r = subprocess.run(["perl", "-e", f"alarm {guard}; exec @ARGV", NGSPICE, "-b", "q.cir"],
                       cwd=d, capture_output=True, text=True, errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def vals(out, name):
    return [float(m) for m in
            re.findall(rf"^{re.escape(name)}\s*=\s*([-+0-9.eE]+)", out, re.M)]


RES = HDR + """
module dut(p,n);
 inout p,n; electrical p,n;
 parameter real r0 = 1000;
 (* desc="temp" *) real tt;
 (* desc="vt"   *) real vt;
 analog begin
   tt = $temperature; vt = $vt;
   I(p,n) <+ V(p,n)/r0;
 end
endmodule
"""

DIODE = HDR + """
module vadiode(p,n);
 inout p,n; electrical p,n;
 parameter real is_ = 1e-15;
 analog I(p,n) <+ is_*(limexp(V(p,n)/$vt) - 1.0);
endmodule
"""


def main():
    d, rc, out = build(RES, "res")
    check("the probe model compiles", rc == 0, out.strip().splitlines()[:1])

    def op(net, extra="", body="op\nprint i(v1)", src=1.0):
        deck = ("p\n.control\npre_osdi m.osdi\n.endc\n"
                f"V1 a 0 dc {src} ac 1\n" + net + "\n" + extra + "\n"
                ".control\noption noacct\nset numdgt=12\n" + body + "\n.endc\n.end\n")
        rc, o = run(d, deck)
        return vals(o, "i(v1)"), o

    OSDI_SUB = "\n.subckt s p n\nN1 p n md\n.model md dut()\n.ends"
    R_SUB = "\n.subckt s p n\nR1 p n 1000\n.ends"

    # ---- [1] the subcircuit multiplier reaches an OSDI device --------------
    print("\n  -- [1] subcircuit multiplier --")
    for mult, want in [("", -1e-3), (" m=2", -2e-3), (" m=5", -5e-3), (" m=0.5", -5e-4)]:
        v, _ = op("X1 a 0 s" + mult + OSDI_SUB)
        b, _ = op("X1 a 0 s" + mult + R_SUB)
        ok = v and b and abs(v[0] - want) <= 1e-9 * abs(want) and abs(v[0] - b[0]) <= 1e-9 * abs(want)
        check(f"OSDI in a subckt with X{mult or ' (no m)'} scales like the built-in",
              ok, f"osdi={v} builtin={b} want={want:g}")
    v, _ = op("X1 a 0 s m=2\n.subckt s p n\nN1 p n md m=3\n.model md dut()\n.ends")
    check("X m=2 over a device that already has m=3 gives 6x", v and abs(v[0] + 6e-3) < 1e-12, f"{v}")

    # ---- [2] nested multipliers compound (built-ins too) -------------------
    print("\n  -- [2] nested multipliers --")
    for dev, sub, label in [("N1 p n md\n.model md dut()", OSDI_SUB, "OSDI"),
                            ("R1 p n 1000", R_SUB, "built-in")]:
        for mo, mi, want in [("m=2", "m=3", -6e-3), ("m=3", "m=2", -6e-3), ("m=4", "m=5", -20e-3)]:
            net = (f"X1 a 0 outer {mo}\n.subckt outer p n\nX2 p n inner {mi}\n.ends\n"
                   f".subckt inner p n\n{dev}\n.ends")
            v, _ = op(net)
            check(f"{label}: outer {mo} x inner {mi} compounds",
                  v and abs(v[0] - want) <= 1e-9 * abs(want), f"{v} want {want:g}")
        net = (f"X1 a 0 l1 m=2\n.subckt l1 p n\nX2 p n l2 m=3\n.ends\n"
               f".subckt l2 p n\nX3 p n l3 m=5\n.ends\n.subckt l3 p n\n{dev}\n.ends")
        v, _ = op(net)
        check(f"{label}: three levels 2x3x5 = 30x", v and abs(v[0] + 0.03) <= 1e-11, f"{v}")

    # ACCEPT HALF: a subckt that DECLARES m as a parameter must not double-apply
    v, _ = op("X1 a 0 s m=2\n.subckt s p n m=1\nR1 p n 1000 m={m}\n.ends")
    check("a subckt declaring `m` as a parameter binds it and does NOT also multiply",
          v and abs(v[0] + 2e-3) < 1e-12, f"{v} want -0.002")

    # ---- [3] instance temperature ------------------------------------------
    print("\n  -- [3] instance temperature --")
    def temp_of(inst, pre=".temp 27"):
        deck = ("t\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1\n" + inst +
                "\n.model md dut()\n" + pre + "\n.control\noption noacct\nset numdgt=12\n"
                "op\nprint @n1[tt]\nprint @n1[vt]\n.endc\n.end\n")
        rc, o = run(d, deck)
        return vals(o, "@n1[tt]"), vals(o, "@n1[vt]"), o

    # $vt is checked for POSITIVITY and PROPORTIONALITY to $temperature rather
    # than against hard-coded k/q: constants.vams and ngspice use different
    # CODATA vintages (~2e-5 apart), which is a real but separate observation
    # and has nothing to do with this fix. Proportionality is the invariant the
    # Celsius bug actually broke -- it made $vt zero at temp=0 and NEGATIVE at
    # temp=-40.
    ratios = []
    for label, inst, want in [("temp=75", "N1 a 0 md temp=75", 348.15),
                              ("temp=0", "N1 a 0 md temp=0", 273.15),
                              ("temp=-40", "N1 a 0 md temp=-40", 233.15),
                              ("temp=125", "N1 a 0 md temp=125", 398.15),
                              ("dtemp=10", "N1 a 0 md dtemp=10", 310.15),
                              ("no override", "N1 a 0 md", 300.15)]:
        tt, vt, _ = temp_of(inst)
        check(f"{label} -> $temperature in KELVIN",
              tt and abs(tt[0] - want) < 1e-6, f"{tt} want {want}")
        check(f"{label} -> $vt is strictly positive",
              vt and vt[0] > 0, f"{vt}")
        if tt and vt and tt[0] > 0:
            ratios.append(vt[0] / tt[0])
    check("$vt stays proportional to $temperature across the whole range",
          len(ratios) == 6 and (max(ratios) - min(ratios)) / max(ratios) < 1e-9,
          ("k/q spread = %.2e over %d temperatures"
           % ((max(ratios) - min(ratios)) / max(ratios), len(ratios))) if ratios else "none")

    tt, _, o = temp_of("N1 a 0 md temp=75 dtemp=10")
    check("`temp` OVERRIDES `dtemp` (does not stack) and says so",
          tt and abs(tt[0] - 348.15) < 1e-6 and "dtemp ignored" in o, f"{tt} want 348.15")

    # the wrong answer this actually produced
    dd, rcd, _ = build(DIODE, "diode")
    def dcur(inst, pre):
        deck = ("v\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 0.6\n" + inst +
                "\n.model md vadiode()\n" + pre + "\n.control\noption noacct\n"
                "set numdgt=12\nop\nprint i(v1)\n.endc\n.end\n")
        rc, o = run(dd, deck)
        return vals(o, "i(v1)")
    a = dcur("N1 a 0 md", ".temp 75")
    b = dcur("N1 a 0 md temp=75", ".temp 27")
    check("a VA diode at 75 degC gives the same current both ways",
          a and b and abs(a[0] - b[0]) <= 1e-9 * abs(a[0]), f".temp={a} instance={b}")

    # ---- [4] .option scale reaches the model -------------------------------
    print("\n  -- [4] .option scale --")
    SCALE = HDR + """
module sc(p,n);
 inout p,n; electrical p,n;
 (* desc="scale" *) real s;
 analog begin s = $simparam("scale", -1.0); I(p,n) <+ V(p,n)*1e-3; end
endmodule
"""
    ds, rcs, _ = build(SCALE, "scale")
    for opt, want in [("", 1.0), (".options scale=1e-6", 1e-6), (".options scale=2", 2.0)]:
        deck = ("s\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1\nN1 a 0 md\n.model md sc()\n"
                + opt + "\n.control\noption noacct\nset numdgt=12\nop\nprint @n1[s]\n.endc\n.end\n")
        rc, o = run(ds, deck)
        v = vals(o, "@n1[s]")
        check(f'$simparam("scale") with {opt or "(no option)"}',
              v and abs(v[0] - want) <= 1e-12 * max(want, 1), f"{v} want {want:g}")

    # ---- [5] terminal currents ---------------------------------------------
    print("\n  -- [5] terminal currents --")
    deck = ("s\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1\nR1 a 0 2000\nN1 a 0 md\n"
            ".model md dut(r0=1000)\n.options savecurrents\n"
            ".control\noption noacct\nset numdgt=12\nop\ndisplay\n"
            "print @n1[i]\nprint @r1[i]\nprint @n1[i_p]\nprint @n1[i_n]\n.endc\n.end\n")
    rc, o = run(d, deck)
    check("savecurrents now creates a current vector for the OSDI device",
          "@n1[i]" in o and "current" in o)
    check("@n1[i] equals V/r0 (the built-in @r1[i] is the control)",
          vals(o, "@n1[i]") and abs(vals(o, "@n1[i]")[0] - 1e-3) < 1e-12
          and vals(o, "@r1[i]") and abs(vals(o, "@r1[i]")[0] - 5e-4) < 1e-12,
          f'osdi={vals(o,"@n1[i]")} builtin={vals(o,"@r1[i]")}')
    check("per-terminal currents are equal and opposite",
          vals(o, "@n1[i_p]") and vals(o, "@n1[i_n]")
          and abs(vals(o, "@n1[i_p]")[0] + vals(o, "@n1[i_n]")[0]) < 1e-15,
          f'i_p={vals(o,"@n1[i_p]")} i_n={vals(o,"@n1[i_n]")}')

    TRI = HDR + """
module tri(a,b,c);
 inout a,b,c; electrical a,b,c;
 analog begin
   I(a,b) <+ V(a,b)/1000;
   I(b,c) <+ V(b,c)/2000;
 end
endmodule
"""
    dt, rct, _ = build(TRI, "tri")
    deck = ("t\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1\nN1 a mid 0 md\n.model md tri()\n"
            ".control\noption noacct\nset numdgt=12\nop\n"
            "print @n1[i_a]\nprint @n1[i_b]\nprint @n1[i_c]\nprint i(v1)\n.endc\n.end\n")
    rc, o = run(dt, deck)
    ia, ib, ic = vals(o, "@n1[i_a]"), vals(o, "@n1[i_b]"), vals(o, "@n1[i_c]")
    check("a 3-terminal device's terminal currents satisfy KCL",
          ia and ib and ic and abs(ia[0] + ib[0] + ic[0]) < 1e-15, f"{ia} {ib} {ic}")
    check("and the driven terminal carries the source current",
          ia and vals(o, "i(v1)") and abs(ia[0] + vals(o, "i(v1)")[0]) < 1e-12,
          f'i_a={ia} i(v1)={vals(o,"i(v1)")}')

    CAP = HDR + """
module vcap(p,n);
 inout p,n; electrical p,n;
 parameter real c0 = 1e-9;
 analog I(p,n) <+ ddt(c0*V(p,n));
endmodule
"""
    dc_, rcc, _ = build(CAP, "cap")
    deck = ("t\n.control\npre_osdi m.osdi\n.endc\n"
            "V1 a 0 pulse(0 1 0 1u 1u 10u 20u)\nN1 a 0 md\n.model md vcap(c0=1e-9)\n"
            ".save @n1[i] v(a)\n.control\noption noacct\nset numdgt=12\ntran 20n 3u\n"
            "meas tran ic FIND @n1[i] AT=0.5u\n.endc\n.end\n")
    rc, o = run(dc_, deck)
    m = re.search(r"\bic\s*=\s*(\S+)", o)
    check("in a transient the terminal current includes the charge derivative",
          m and abs(float(m.group(1)) - 1e-3) < 1e-8, f"{m and m.group(1)} want 1e-3 (C dV/dt)")

    # ---- [6] analysis_name agrees with analysis() ---------------------------
    print("\n  -- [6] analysis_name vs analysis() --")
    BOTH = HDR + """
module both(p,n);
 inout p,n; electrical p,n;
 analog begin
   $strobe("PAIR name=%s ac=%d dc=%d tran=%d noise=%d",
           $simparam$str("analysis_name"),
           analysis("ac"), analysis("dc"), analysis("tran"), analysis("noise"));
   I(p,n) <+ V(p,n)*1e-3;
 end
endmodule
"""
    db, rcb, _ = build(BOTH, "both")
    total_bad = 0
    for label, cmd in [("op", "op"), ("dc", "dc v1 0 1 1"), ("ac", "ac dec 1 1k 1k"),
                       ("tran", "tran 1u 2u"), ("noise", "noise v(b) v1 dec 1 1k 10k")]:
        deck = ("b\n.control\npre_osdi m.osdi\n.endc\nV1 a 0 dc 1 ac 1\nRs a b 1000\n"
                "N1 b 0 md\n.model md both()\n.control\noption noacct\n" + cmd + "\n.endc\n.end\n")
        rc, o = run(db, deck)
        pairs = set(re.findall(r"PAIR name=(\S+) ac=(\d) dc=(\d) tran=(\d) noise=(\d)", o))
        bad = [p for p in pairs if {"ac": p[1], "dc": p[2], "tran": p[3], "noise": p[4]}[p[0]] != "1"]
        total_bad += len(bad)
        check(f"during `{label}`, every analysis_name is confirmed by analysis()",
              not bad and pairs, f"{sorted(bad)}" if bad else f"{len(pairs)} phase(s)")
    check("no contradiction in any analysis", total_bad == 0, f"{total_bad} found")

    for j in os.listdir(HERE):
        if j.startswith("_op_"):
            shutil.rmtree(os.path.join(HERE, j), ignore_errors=True)
    print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
    sys.exit(0 if passed == checks else 1)


main()
