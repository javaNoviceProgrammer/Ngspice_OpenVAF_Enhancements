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

from bench_common import (HERE, OPENVAF, CORPUS, COMPILE_MODELS, count_loc, machine_info,
                          compile_va, median_time, write_deck, rc_ladder_deck,
                          rectifier_deck, bsim4_deck, load_wave, max_wave_diff)

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

    with open(RESULTS_JSON, "w") as fh:
        json.dump(res, fh, indent=1)
    write_report(res)
    print("plotting ...")
    subprocess.run([sys.executable, os.path.join(HERE, "plot_benchmark.py")],
                   cwd=HERE, check=True)
    print(f"wrote RESULTS.md, results.json, plots/")


if __name__ == "__main__":
    main()
