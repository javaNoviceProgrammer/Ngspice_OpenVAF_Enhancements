#!/usr/bin/env python3
"""run_benchmark.py -- the Enhancement-74 performance benchmark.

Three sections:
  [A] compile time: openvaf-r over 12 flagship compact models from the
      VA_TEST corpus (median of 3; skipped gracefully if the corpus is
      absent);
  [B] simulation throughput: OSDI-vs-built-in *twin* circuits with
      identical physics (RC ladder, rectifier bank, one BSIM4 stage) --
      wall time, timepoints/second, and the OSDI/built-in ratio, with the
      waveform agreement printed alongside so the speed numbers are known
      to compare the same work;
  [C] scaling: RC ladder wall time vs circuit size, both device kinds.

Writes results.json + RESULTS.md and (via plot_benchmark.py) plots/*.png.
Timing numbers are machine-dependent -- the committed RESULTS.md records
the reference machine; regenerate on yours for comparable numbers.
"""
import json
import os
import statistics
import subprocess
import sys
import time

from bench_common import (HERE, OPENVAF, CORPUS, COMPILE_MODELS, ac_ladder_deck,
                          binary_has_klu, bsim4_deck, compile_va, count_loc,
                          load_wave, machine_info, max_wave_diff, median_time,
                          noise_ladder_deck, osc_freq, rc_ladder_deck,
                          rectifier_deck, ro_deck, with_klu, write_deck)

RESULTS_JSON = os.path.join(HERE, "results.json")
RESULTS_MD = os.path.join(HERE, "RESULTS.md")


def bench_compile():
    if not os.path.isdir(CORPUS):
        print("  corpus not found -- skipping the compile benchmark")
        return None
    rows = []
    for label, rel in COMPILE_MODELS:
        src = os.path.join(CORPUS, rel)
        if not os.path.isfile(src):
            print(f"  {label:16s} MISSING ({rel})")
            continue
        loc = count_loc(src)
        out = os.path.join(HERE, "_bench_" + os.path.basename(rel) + ".osdi")
        times = [compile_va(src, out) for _ in range(3)]
        t = statistics.median(times)
        rows.append({"model": label, "file": rel, "loc": loc, "seconds": round(t, 3)})
        print(f"  {label:16s} {loc:6d} LOC   {t:7.2f} s")
    return rows


def bench_twin(title, gen, sizes_or_none, tstep, tstop, match_tol_desc):
    """One twin benchmark: generate both decks, run 3x each, compare waves."""
    decks = {}
    for kind in ("bi", "osdi"):
        name = f"_tw_{title}_{kind}.cir"
        txt = f"_tw_{title}_{kind}.txt"
        write_deck(name, gen(kind, txt))
        decks[kind] = (name, txt)
    t_bi = median_time(decks["bi"][0])
    t_osdi = median_time(decks["osdi"][0])
    pts = len(load_wave(decks["osdi"][1])[0])
    diff = max_wave_diff(decks["bi"][1], decks["osdi"][1])
    r = {"bench": title, "builtin_s": round(t_bi, 3), "osdi_s": round(t_osdi, 3),
         "ratio": round(t_osdi / t_bi, 3), "timepoints": pts,
         "osdi_pts_per_s": int(pts / t_osdi), "max_wave_diff": float(f"{diff:.3g}")}
    print(f"  {title:12s} built-in {t_bi:6.2f} s | OSDI {t_osdi:6.2f} s | "
          f"ratio {r['ratio']:5.2f} | {pts} pts | max|dV| = {diff:.2e} ({match_tol_desc})")
    return r


def bench_scaling():
    rows = []
    for n in (10, 20, 50, 100, 200, 500):
        row = {"n": n}
        for kind in ("bi", "osdi"):
            name = f"_sc_{kind}_{n}.cir"
            write_deck(name, rc_ladder_deck(kind, n, "2n", "50u", f"_sc_{kind}_{n}.txt"))
            row[kind + "_s"] = round(median_time(name, runs=2), 3)
        row["ratio"] = round(row["osdi_s"] / row["bi_s"], 3)
        rows.append(row)
        print(f"  N={n:4d}  built-in {row['bi_s']:7.2f} s | OSDI {row['osdi_s']:7.2f} s"
              f" | ratio {row['ratio']:5.2f}")
    return rows


def write_report(res):
    lines = ["# Enhancement-74 benchmark results (reference run)", "",
             f"- Machine: {res['machine']}",
             f"- Toolchain: this repository's openvaf-r + ngspice-46 (see the git tag)",
             f"- Date: {time.strftime('%Y-%m-%d')}",
             "", "Timing is machine-dependent; regenerate with "
             "`python3 run_benchmark.py` for numbers comparable on your machine.", ""]
    if res.get("compile"):
        lines += ["## [A] Compile time (openvaf-r, median of 3)", "",
                  "| Model | Lines (incl. includes) | Compile |",
                  "|---|---:|---:|"]
        for r in res["compile"]:
            lines.append(f"| {r['model']} | {r['loc']} | {r['seconds']:.2f} s |")
        total = sum(r["seconds"] for r in res["compile"])
        lines += ["", f"Total for the 12 flagships: **{total:.1f} s**.", ""]
    lines += ["## [B] Simulation throughput: OSDI vs built-in twins", "",
              "Identical physics on both sides (same equations, same model card),",
              "so ngspice does the same numerical work and the waveforms agree;",
              "the ratio isolates the OSDI evaluation overhead.", "",
              "| Benchmark | built-in | OSDI | OSDI/built-in | timepoints | OSDI pts/s | max waveform diff |",
              "|---|---:|---:|---:|---:|---:|---:|"]
    for r in res["twins"]:
        lines.append(f"| {r['bench']} | {r['builtin_s']:.2f} s | {r['osdi_s']:.2f} s | "
                     f"{r['ratio']:.2f} | {r['timepoints']} | {r['osdi_pts_per_s']} | "
                     f"{r['max_wave_diff']:.2e} V |")
    lines += ["", "## [C] RC-ladder scaling (wall time vs circuit size)", "",
              "| N segments | built-in | OSDI | ratio |", "|---:|---:|---:|---:|"]
    for r in res["scaling"]:
        lines.append(f"| {r['n']} | {r['bi_s']:.2f} s | {r['osdi_s']:.2f} s | {r['ratio']:.2f} |")
    if res.get("ring_osc"):
        ro = res["ring_osc"]
        lines += ["", "## [D] 9-stage BSIM4 ring oscillator", "",
                  "18 BSIM4 devices, evaluation-dominated; the oscillation",
                  "frequencies double as a correspondence pin.", "",
                  "| | built-in | OSDI | OSDI/built-in |",
                  "|---|---:|---:|---:|",
                  f"| wall time | {ro['builtin_s']:.2f} s | {ro['osdi_s']:.2f} s | {ro['ratio']:.2f} |",
                  f"| frequency | {ro['f_builtin_ghz']:.3f} GHz | {ro['f_osdi_ghz']:.3f} GHz | — |",
                  ""]
    if res.get("smallsig"):
        lines += ["## [E] Small-signal throughput (ladders, N = 200)", "",
                  "| Analysis | built-in | OSDI | OSDI/built-in | max output diff |",
                  "|---|---:|---:|---:|---:|"]
        for r in res["smallsig"]:
            lines.append(f"| .{r['bench']} | {r['builtin_s']:.2f} s | {r['osdi_s']:.2f} s | "
                         f"{r['ratio']:.2f} | {r['max_diff']:.2e} |")
        lines.append("")
    if res.get("klu"):
        lines += ["## [F] KLU vs SPARSE 1.3", "",
                  "| Benchmark | devices | SPARSE | KLU | KLU speedup |",
                  "|---|---|---:|---:|---:|"]
        for r in res["klu"]:
            lines.append(f"| {r['bench']} | {r['kind']} | {r['sparse_s']:.2f} s | "
                         f"{r['klu_s']:.2f} s | {r['speedup']:.2f}x |")
        lines.append("")
    lines += ["", "![scaling](plots/scaling.png)", "",
              "![throughput](plots/throughput.png)", ""]
    if res.get("compile"):
        lines += ["![compile](plots/compile_times.png)", ""]
    with open(RESULTS_MD, "w") as fh:
        fh.write("\n".join(lines))


def main():
    sys.stdout.reconfigure(line_buffering=True)
    res = {"machine": machine_info()}
    print("compiling the twin modules ...")
    compile_va(os.path.join(HERE, "rcseg.va"), os.path.join(HERE, "rcseg.osdi"))
    compile_va(os.path.join(HERE, "vadiode.va"), os.path.join(HERE, "vadiode.osdi"))
    bsim4_src = os.path.join(CORPUS, "bsim4/vacode/bsim4.va")
    have_bsim4 = os.path.isfile(bsim4_src)
    if have_bsim4:
        compile_va(bsim4_src, os.path.join(HERE, "bsim4va.osdi"))

    print("[A] compile time over the flagship corpus models")
    res["compile"] = bench_compile()

    print("[B] twin throughput (median of 3 runs each)")
    twins = [bench_twin("rcladder", lambda k, o: rc_ladder_deck(k, 200, "2n", "200u", o),
                        None, "2n", "200u", "expect ~machine zero"),
             bench_twin("rectifier", lambda k, o: rectifier_deck(k, 50, "20n", "400u", o),
                        None, "20n", "400u", "expect < 1e-3")]
    if have_bsim4:
        twins.append(bench_twin("bsim4stage", lambda k, o: bsim4_deck(k, "1n", "50u", o),
                                None, "1n", "50u", "different codebases; expect < 0.1"))
    res["twins"] = twins

    print("[C] RC-ladder scaling")
    res["scaling"] = bench_scaling()

    # ------------------------------------------------------- round 2 (E-79)
    if have_bsim4:
        print("[D] 9-stage BSIM4 ring oscillator (multi-device nonlinear)")
        for kind in ("bi", "osdi"):
            write_deck(f"_ro_{kind}.cir",
                       ro_deck(kind, 9, "5p", "200n", f"_ro_{kind}.txt"))
        t_bi = median_time("_ro_bi.cir")
        t_osdi = median_time("_ro_osdi.cir")
        f_bi = osc_freq("_ro_bi.txt")
        f_osdi = osc_freq("_ro_osdi.txt")
        res["ring_osc"] = {
            "builtin_s": round(t_bi, 3), "osdi_s": round(t_osdi, 3),
            "ratio": round(t_osdi / t_bi, 3),
            "f_builtin_ghz": round(f_bi / 1e9, 4) if f_bi else None,
            "f_osdi_ghz": round(f_osdi / 1e9, 4) if f_osdi else None,
        }
        print(f"  built-in {t_bi:6.2f} s @ {f_bi/1e9:.3f} GHz | "
              f"OSDI {t_osdi:6.2f} s @ {f_osdi/1e9:.3f} GHz | "
              f"ratio {t_osdi/t_bi:5.2f}")

    print("[E] .ac and .noise throughput (RC / noisy-resistor ladders, N=200)")
    smallsig = []
    for label, gen, extra in (
            ("ac", lambda k, o: ac_ladder_deck(k, 200, o), None),
            ("noise", lambda k, o: noise_ladder_deck(k, 200, o), "spectrum")):
        for kind in ("bi", "osdi"):
            write_deck(f"_ss_{label}_{kind}.cir", gen(kind, f"_ss_{label}_{kind}.txt"))
        t_bi = median_time(f"_ss_{label}_bi.cir")
        t_osdi = median_time(f"_ss_{label}_osdi.cir")
        diff = max_wave_diff(f"_ss_{label}_bi.txt", f"_ss_{label}_osdi.txt")
        row = {"bench": label, "builtin_s": round(t_bi, 3),
               "osdi_s": round(t_osdi, 3), "ratio": round(t_osdi / t_bi, 3),
               "max_diff": float(f"{diff:.3g}")}
        smallsig.append(row)
        print(f"  .{label:6s} built-in {t_bi:6.2f} s | OSDI {t_osdi:6.2f} s | "
              f"ratio {row['ratio']:5.2f} | max diff {diff:.2e}")
    res["smallsig"] = smallsig

    if binary_has_klu():
        print("[F] KLU vs SPARSE (RC ladder N=500 + the ring oscillator)")
        klu_rows = []
        benches = [("rcladder500",
                    lambda k, o: rc_ladder_deck(k, 500, "2n", "50u", o))]
        if have_bsim4:
            benches.append(("ringosc",
                            lambda k, o: ro_deck(k, 9, "5p", "200n", o)))
        for label, gen in benches:
            for kind in ("bi", "osdi"):
                base = gen(kind, f"_klu_{label}_{kind}.txt")
                write_deck(f"_sp_{label}_{kind}.cir", base)
                write_deck(f"_klu_{label}_{kind}.cir", with_klu(base))
                t_sp = median_time(f"_sp_{label}_{kind}.cir", runs=2)
                t_klu = median_time(f"_klu_{label}_{kind}.cir", runs=2)
                klu_rows.append({"bench": label, "kind": kind,
                                 "sparse_s": round(t_sp, 3),
                                 "klu_s": round(t_klu, 3),
                                 "speedup": round(t_sp / t_klu, 3)})
                print(f"  {label:12s} {kind:4s}: SPARSE {t_sp:6.2f} s | "
                      f"KLU {t_klu:6.2f} s | speedup {t_sp/t_klu:5.2f}x")
        res["klu"] = klu_rows
    else:
        print("[F] SKIP: this ngspice binary was built without KLU")
        res["klu"] = None

    with open(RESULTS_JSON, "w") as fh:
        json.dump(res, fh, indent=1)
    write_report(res)
    print("plotting ...")
    subprocess.run([sys.executable, os.path.join(HERE, "plot_benchmark.py")],
                   cwd=HERE, check=True)
    print(f"wrote RESULTS.md, results.json, plots/")


if __name__ == "__main__":
    main()
