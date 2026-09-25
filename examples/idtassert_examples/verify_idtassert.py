#!/usr/bin/env python3
"""
verify_idtassert.py -- verifies Enhancement-52: the idt() assert/reset forms,
end-to-end through the committed openvaf-r + ngspice.

idt(expr, ic, assert[, tol]) resets the integral to `ic` while `assert` is
nonzero and resumes integration from `ic` on release. The old formulation's
reactive residual JUMPED at the reset onset (charge: integrated value -> ic),
which the transient integrator saw as an impulse -- externally-driven resets
mostly survived, but a self-referential reset (V(out) > threshold) rang
chaotically and ran away (reached ~400 V on a 1 V/s ramp). E-52 keeps the
charge smooth (react = output, always), implements reset as a stiff
first-order decay to ic (tau = 10us), and bounds the timestep only while the
decay is active (trapezoidal deadbeat region), releasing the bound once
settled so long holds stay fast.

Checks (exact):
  1. external reset: ramp 0.5 -> 1.5 in 1 s; held at 0.5 during the pulse;
     resumed to 1.5 one second after release
  2. op-dependent integrand + reset active AT the op + tol form: held 0.25,
     then 0.25 + 2 V/s after release
  3. self-referential reset stays BOUNDED at the threshold (max = 1.0; used
     to run away to ~400)
  4. relaxation oscillator (idt + hysteretic cross-event reset): peaks 1.0,
     valleys at ic, period 1.0 s, no undershoot

Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF, NG as NGSPICE
from _setup import check_both_solvers as _check_both_solvers; _check_both_solvers(__file__)  # verify under BOTH KLU and Sparse solvers


def run(deck, *names):
    with open(os.path.join(HERE, "_i.cir"), "w") as fh:
        fh.write(deck)
    out = subprocess.run([NGSPICE, "-b", "_i.cir"], cwd=HERE,
                         capture_output=True, text=True, timeout=180).stdout
    vals = {}
    for line in out.splitlines():
        stripped = line.strip().lower()
        for nm in names:
            if stripped.startswith(nm.lower() + " ") and nm not in vals:
                try:
                    vals[nm] = float(line.split("=", 1)[1].split("at=")[0])
                except ValueError:
                    pass
    return vals


def main():
    subprocess.run([OPENVAF, "idtassert_demo.va", "-o", "idtassert_demo.osdi"],
                   cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    ok = True

    def check(label, got, want, tol=2e-3):
        nonlocal ok
        good = got is not None and abs(got - want) < tol
        ok = ok and good
        gs = "None" if got is None else f"{got:.6e}"
        print(f"  {'PASS' if good else 'FAIL'}  {label}   got {gs}, want {want:.6e}")

    print("[1] externally-reset integrator")
    deck = ("* e52\nVr rst 0 DC 0 PULSE(0 1 2 1n 1n 1 4)\nNDUT rst out nm\nRL out 0 1G\n"
            ".model nm idtreset\n.tran 0.01 4\n.control\npre_osdi idtassert_demo.osdi\nrun\n"
            "meas tran v1 FIND v(out) AT=1.0\nmeas tran v2 FIND v(out) AT=2.5\n"
            "meas tran v3 FIND v(out) AT=4.0\n.endc\n.end\n")
    v = run(deck, "v1", "v2", "v3")
    check("ramp: 0.5 + 1 s", v.get("v1"), 1.5)
    check("held at ic during reset", v.get("v2"), 0.5)
    check("resumed: ic + 1 s", v.get("v3"), 1.5)

    print("[2] op-dependent integrand, reset at the op, tol form")
    deck = ("* e52b\nVr rst 0 DC 1 PULSE(1 0 2 1n 1n 10 20)\nVi in 0 DC 2\n"
            "NDUT rst in out nm\nRL out 0 1G\n.model nm idtreset2\n.tran 0.01 4\n"
            ".control\npre_osdi idtassert_demo.osdi\nrun\n"
            "meas tran v0 FIND v(out) AT=0.5\nmeas tran v1 FIND v(out) AT=3.0\n.endc\n.end\n")
    v = run(deck, "v0", "v1")
    check("held at ic while reset at op", v.get("v0"), 0.25)
    check("resumed at 2 V/s", v.get("v1"), 2.25)

    print("[3] self-referential reset stays bounded (used to reach ~400)")
    deck = ("* e52c\nNDUT out nm\nRL out 0 1G\n.model nm idtselfreset\n.tran 0.005 3.5\n"
            ".control\npre_osdi idtassert_demo.osdi\nrun\n"
            "meas tran vmax MAX v(out) FROM=0.1 TO=3.4\n.endc\n.end\n")
    v = run(deck, "vmax")
    check("max = threshold", v.get("vmax"), 1.0)

    print("[4] relaxation oscillator: idt + hysteretic reset")
    deck = ("* e52d\nNDUT out nm\nRL out 0 1G\n.model nm idtosc\n.tran 0.002 5\n"
            ".control\npre_osdi idtassert_demo.osdi\nrun\n"
            "meas tran vmax MAX v(out) FROM=0.2 TO=4.8\n"
            "meas tran vmin MIN v(out) FROM=1.2 TO=4.8\n"
            "meas tran t1 WHEN v(out)=0.99 RISE=1\n"
            "meas tran t2 WHEN v(out)=0.99 RISE=2\n.endc\n.end\n")
    v = run(deck, "vmax", "vmin", "t1", "t2")
    check("peaks at the upper threshold", v.get("vmax"), 1.0)
    check("valleys at ic, no undershoot", v.get("vmin"), 0.0, 1e-3)
    period = None
    if v.get("t1") is not None and v.get("t2") is not None:
        period = v["t2"] - v["t1"]
    check("period = 1 s (full ramp)", period, 1.0, 2e-2)

    # Enhancement-678 (hunt F9 of 2026-09-19): the same reset at the
    # microsecond scale. tau was a fixed 10 us, so a 2 us hold read 1.32 and
    # the integral resumed from there; it follows the print step now, and the
    # gain is capped at 2/h so the onset step cannot flip the trapezoidal rule.
    # The release is detected at the accepted point after the falling edge
    # (V(rst) falls through 0.5 at 3001.5 ns), so the resumed integral is
    # 0.5 + 1e6*(t - 3001.5 ns).
    print("[5] microsecond-scale reset: held at ic, resumed from it (E-678)")
    for label, opt in (("trapezoidal", ""), ("gear", ".option method=gear\n")):
        deck = ("* e678\nVr rst 0 DC 0 PULSE(0 1 1u 1n 1n 2u 100u)\nNDUT rst out nm\nRL out 0 1G\n"
                ".model nm idtfast\n" + opt + ".tran 0.1u 5u\n.control\npre_osdi idtassert_demo.osdi\nrun\n"
                "meas tran h15 FIND v(out) AT=1.5u\nmeas tran h30 FIND v(out) AT=3.0u\n"
                "meas tran r35 FIND v(out) AT=3.5u\nmeas tran r50 FIND v(out) AT=5.0u\n.endc\n.end\n")
        v = run(deck, "h15", "h30", "r35", "r50")
        check(f"{label}: held at ic 0.5 us into a 2 us reset (was 1.45)", v.get("h15"), 0.5, 1e-3)
        check(f"{label}: still at ic at the end of the reset (was 1.32)", v.get("h30"), 0.5, 1e-3)
        check(f"{label}: resumed from ic: 0.9985 at 3.5 us (was 1.82)", v.get("r35"), 0.9985, 1e-3)
        check(f"{label}: 2.4985 at 5 us (was 3.32)", v.get("r50"), 2.4985, 1e-3)

    # -----------------------------------------------------------------------
    # 5. Enhancement-722 (correctness campaign 2, F1 of 2026-09-25): an idt
    #    asserted on analysis("static") -- LRM 4.5.5's own idiom -- had no
    #    integrator in .ac and .noise: the small-signal linearisation pass
    #    carried the operating point's flags (static 1) where Table 4-22's AC
    #    and NOISE columns have static 0, and the select between ic and the
    #    integrator took ic. A 1 nF integrator behind 1 kOhm read 1/R = 1 mA in
    #    .ac (6.283e-6 A due), its dual 0 (1.59e-7 due), a topology switched on
    #    "static" a short; the same asserted on "ic" was right all along.
    # -----------------------------------------------------------------------
    print()
    print("Enhancement-722: an idt asserted on analysis(\"static\") in .ac and .noise")
    subprocess.run([OPENVAF, "idtac.va", "-o", "idtac.osdi"], cwd=HERE, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def small(module, ctl, tag):
        deck = (f"* idtac {tag}\n.options reltol=1e-6 abstol=1e-15 vntol=1e-9\n"
                f"V1 in 0 dc 0 ac 1\nR1 in x 1k\nN1 x 0 mm\n.model mm {module}\n"
                f".control\nset noinit\nset numdgt=12\npre_osdi idtac.osdi\n{ctl}\n.endc\n.end\n")
        with open(os.path.join(HERE, "_i.cir"), "w") as fh:
            fh.write(deck)
        out = subprocess.run([NGSPICE, "-b", "_i.cir"], cwd=HERE, capture_output=True,
                             text=True, timeout=180).stdout
        vals = {}
        for line in out.splitlines():
            if "=" in line and not line.lstrip().startswith("*"):
                k, _, v = line.partition("=")
                try:
                    vals[k.strip()] = float(v.split()[0])
                except (ValueError, IndexError):
                    pass
        return vals

    AC = "ac lin 1 1k 1k\nprint mag(i(v1)) ph(i(v1))"
    NOISE = "noise v(x) v1 lin 1 1k 1k\nsetplot noise1\nprint onoise_spectrum"
    TRAN = "tran 0.01u 1u\nmeas tran vx find v(x) at=1u"
    ref = small("i_ic", AC, "ic")
    v = small("i_static", AC, "static")
    check("i_static in .ac: |i| = 6.283e-6 A, the 1 nF integrator (was 1e-3, a short)",
          v.get("mag(i(v1))"), 6.28306e-6, 1e-9)
    check("  ... and its phase is the RC's, as asserted on \"ic\"", v.get("ph(i(v1))"),
          ref.get("ph(i(v1))", 9), 1e-6)
    v = small("g_static", AC, "gstatic")
    check("g_static in .ac: |i| = 1.5915e-7 A, the 1 kH inductor (was 0, an open)",
          v.get("mag(i(v1))"), 1.59155e-7, 1e-10)
    v = small("sw_static", AC, "sw")
    check("a topology switched on analysis(\"static\") linearises its dynamic branch: "
          "6.283e-6 A (was 1e-3)", v.get("mag(i(v1))"), 6.28306e-6, 1e-9)
    ref = small("i_ic", NOISE, "icn")
    v = small("i_static", NOISE, "staticn")
    check("i_static in .noise: the output noise at 1 kHz is the RC's 4.07e-9 V/sqrt(Hz), as "
          "asserted on \"ic\" (was 0: the node pinned)", v.get("onoise_spectrum"),
          ref.get("onoise_spectrum", 9), 1e-15)
    ref = small("i_ic", TRAN.replace("dc 0 ac 1", "dc 0 ac 1"), "ict")
    v = small("i_static", TRAN, "statict")
    check("i_static in tran: unchanged, equal to \"ic\" at 1 us", v.get("vx"),
          ref.get("vx", 9), 1e-9)

    print()
    print("ALL PASS" if ok else "SOME CHECKS FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
