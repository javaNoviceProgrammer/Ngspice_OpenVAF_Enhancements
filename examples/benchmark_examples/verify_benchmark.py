#!/usr/bin/env python3
"""
verify_benchmark.py -- deterministic checks for the Enhancement-74/-79
performance benchmark, end-to-end through the committed openvaf-r +
ngspice.

Timing numbers are machine-dependent, so the *pass/fail* checks here pin
only what is deterministic or generously bounded:

  [1] the twin modules compile and the RC-ladder twin circuits produce
      waveforms that agree to machine precision (identical physics =>
      identical timestep trajectory);
  [2] the rectifier (diode) twins agree below 1e-3 V through a nonlinear
      transient;
  [3] the BSIM4 twins (VA-Models bsim4.va vs the built-in level-14 4.8
      model, default cards) agree on the op drain current within 10%
      (different codebases -- a correspondence pin, not an identity);
  [4] a compile-time sanity bound: the flagship BSIM4 model compiles in
      under 60 s;
  [5] an OSDI-overhead sanity bound: the OSDI RC ladder runs within 25x
      of the built-in twin (catches only catastrophic regressions);
  [6] the harness artifacts (RESULTS.md, plots) exist in the folder;
  [7] (round 2, E-79) both BSIM4 ring oscillators oscillate and their
      frequencies correspond within 10%;
  [8] (round 2) the noisy-resistor ladder's .noise spectrum is identical
      to the built-in resistors' (the E-57 4kT/R identity, re-pinned);
  [9] (round 2) KLU and SPARSE produce the same waveform (solver
      independence) -- skipped on binaries built without KLU.

Corpus-dependent checks skip gracefully when VA_TEST is absent.
Every SPICE deck starts with a title line (SPICE treats line 1 as the title!).
"""
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from bench_common import (OPENVAF, NGSPICE, CORPUS, binary_has_klu, bsim4_deck,
                          compile_va, max_wave_diff, noise_ladder_deck,
                          osc_freq, rc_ladder_deck, rectifier_deck,
                          ro_deck, run_ngspice, with_klu, write_deck)
from _setup import check_both_solvers as _check_both_solvers
_check_both_solvers(__file__)   # verify under BOTH KLU and Sparse solvers

checks = []


def check(name, ok, detail):
    checks.append(ok)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")


def main():
    print("[1] RC-ladder twins: machine-precision waveform match")
    compile_va(os.path.join(HERE, "rcseg.va"), os.path.join(HERE, "rcseg.osdi"))
    for kind in ("bi", "osdi"):
        write_deck(f"_v_rc_{kind}.cir",
                   rc_ladder_deck(kind, 50, "2n", "100u", f"_v_rc_{kind}.txt"))
    t_bi = run_ngspice("_v_rc_bi.cir")
    t_osdi = run_ngspice("_v_rc_osdi.cir")
    d = max_wave_diff("_v_rc_bi.txt", "_v_rc_osdi.txt")
    check("waveform match", d < 1e-9, f"max|dV| = {d:.2e} V (< 1e-9)")

    print("[5] OSDI-overhead sanity bound (generous)")
    ratio = t_osdi / t_bi
    check("overhead bound", ratio < 25.0, f"OSDI/built-in = {ratio:.2f} (< 25)")

    print("[2] rectifier twins: nonlinear transient agreement")
    compile_va(os.path.join(HERE, "vadiode.va"), os.path.join(HERE, "vadiode.osdi"))
    for kind in ("bi", "osdi"):
        write_deck(f"_v_dio_{kind}.cir",
                   rectifier_deck(kind, 10, "20n", "200u", f"_v_dio_{kind}.txt"))
        run_ngspice(f"_v_dio_{kind}.cir")
    d = max_wave_diff("_v_dio_bi.txt", "_v_dio_osdi.txt")
    check("diode twin", d < 1e-3, f"max|dV| = {d:.2e} V (< 1e-3)")

    bsim4_src = os.path.join(CORPUS, "bsim4", "vacode", "bsim4.va")
    if os.path.isfile(bsim4_src):
        print("[4] flagship compile-time bound")
        t0 = time.monotonic()
        compile_va(bsim4_src, os.path.join(HERE, "bsim4va.osdi"))
        dt = time.monotonic() - t0
        check("bsim4 compile", dt < 60.0, f"{dt:.2f} s (< 60)")

        print("[3] BSIM4 op-current correspondence (VA 4.8 vs built-in 4.8)")
        deck = ("* bsim4 twin op\n"
                "vd d 0 dc 1.0\nvg g 0 dc 1.0\n"
                "nm1 d g 0 0 mos_va\n.model mos_va bsim4va()\n"
                "vd2 d2 0 dc 1.0\nmd2 d2 g 0 0 mos_bi\n"
                ".model mos_bi nmos(level=14 version=4.8)\n"
                ".control\npre_osdi bsim4va.osdi\nop\n"
                "wrdata _v_b4.txt i(vd) i(vd2)\nquit\n.endc\n.end\n")
        write_deck("_v_b4.cir", deck)
        run_ngspice("_v_b4.cir")
        vals = open(os.path.join(HERE, "_v_b4.txt")).read().split()
        i_va, i_bi = float(vals[1]), float(vals[3])
        rel = abs(i_va - i_bi) / abs(i_bi)
        check("op current", rel < 0.10,
              f"OSDI {i_va:.4e} A vs built-in {i_bi:.4e} A ({100*rel:.1f}% < 10%)")
    else:
        print("[3][4] SKIP: VA_TEST corpus not found")

    if os.path.isfile(os.path.join(CORPUS, "bsim4", "vacode", "bsim4.va")):
        print("[7] round 2: BSIM4 ring-oscillator twins (short run)")
        for kind in ("bi", "osdi"):
            write_deck(f"_v_ro_{kind}.cir",
                       ro_deck(kind, 9, "5p", "50n", f"_v_ro_{kind}.txt"))
            run_ngspice(f"_v_ro_{kind}.cir")
        f_bi = osc_freq("_v_ro_bi.txt")
        f_osdi = osc_freq("_v_ro_osdi.txt")
        check("both ring oscillators oscillate", bool(f_bi and f_osdi),
              f"bi={f_bi} osdi={f_osdi}")
        if f_bi and f_osdi:
            rel = abs(f_osdi - f_bi) / f_bi
            check("frequencies correspond", rel < 0.10,
                  f"{f_bi/1e9:.3f} vs {f_osdi/1e9:.3f} GHz ({100*rel:.1f}% < 10%)")
    else:
        print("[7] SKIP: corpus absent")

    print("[8] round 2: noisy-resistor .noise spectrum identity")
    compile_va(os.path.join(HERE, "nres.va"), os.path.join(HERE, "nres.osdi"))
    for kind in ("bi", "osdi"):
        write_deck(f"_v_nz_{kind}.cir",
                   noise_ladder_deck(kind, 50, f"_v_nz_{kind}.txt"))
        run_ngspice(f"_v_nz_{kind}.cir")
    from bench_common import load_wave
    _, va = load_wave("_v_nz_bi.txt")
    _, vb = load_wave("_v_nz_osdi.txt")
    worst = max(abs(x - y) / x for x, y in zip(va, vb))
    check("thermal-noise ladder identical to built-in",
          len(va) > 100 and worst < 1e-4, f"worst rel {worst:.2e} (< 1e-4)")

    if binary_has_klu():
        print("[9] round 2: KLU solves match SPARSE (solver independence)")
        base = rc_ladder_deck("osdi", 50, "2n", "50u", "_v_klu.txt")
        write_deck("_v_sp.cir", base.replace("_v_klu.txt", "_v_sp.txt"))
        write_deck("_v_klu.cir", with_klu(base))
        run_ngspice("_v_sp.cir")
        out = run_ngspice("_v_klu.cir")
        d = max_wave_diff("_v_sp.txt", "_v_klu.txt")
        check("KLU and SPARSE waveforms agree", d < 1e-6,
              f"max|dV| = {d:.2e} (< 1e-6)")
    else:
        print("[9] SKIP: binary built without KLU")

    print("[6] committed reference artifacts present")
    for f in ("RESULTS.md", "plots/scaling.png", "plots/throughput.png"):
        check(f, os.path.isfile(os.path.join(HERE, f)), "exists")

    n_pass = sum(checks)
    n_fail = len(checks) - n_pass
    print(("ALL PASS" if n_fail == 0 else "FAILURES") +
          f": {n_pass} passed, {n_fail} failed")
    sys.exit(0 if n_fail == 0 else 1)


if __name__ == "__main__":
    main()
