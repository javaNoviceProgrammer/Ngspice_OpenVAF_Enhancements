# absdelay examples & KLU-vs-SPARSE benchmark (version2)

Self-contained examples and a performance benchmark for the OpenVAF/ngspice
`absdelay` support, comparing ngspice's two linear solvers — **KLU** and the
default **Sparse 1.3** — for **DC**, **AC**, and **transient** analysis.
Everything here uses the **version2** toolchain only:

- compiler : `../bin/openvaf-r`
- simulator: `../bin/ngspice`

The solver is selected per-run by adding `.options klu` to the netlist
(KLU) or leaving it out (Sparse 1.3 default). Both produce identical results;
they differ only in speed.

## Layout

```
absdelay_examples/
  absdelay.va            delay model:  V(out) <+ absdelay(V(in), delay)
  absdelay.osdi          compiled with version2 openvaf-r
  examples/              small correctness demos (5-stage delay line)
    dc_sim.cir           V(out) == V(in) in steady state
    ac_sim.cir           flat 0 dB magnitude, linear phase (= delay)
    tran_sim.cir         pulse delayed by 10 ns
    run_examples.sh      runs each with BOTH solvers and checks they agree
    example_results.png  DC / AC / transient waveforms, KLU vs SPARSE overlaid
  benchmark/
    gen_bench.py         generates L x L absdelay-driven resistor-mesh netlists
    run_benchmark.sh     times KLU vs SPARSE for dc/ac/tran across sizes
    plot_benchmark.py    plots runtime + speedup
    cir/                 generated benchmark netlists
    results/
      timings.csv        raw timings
      benchmark.png      runtime-vs-size and speedup-vs-size plots
```

## Reproduce

```bash
# correctness: both solvers must agree
bash examples/run_examples.sh

# performance sweep (writes results/timings.csv) + plot
bash benchmark/run_benchmark.sh           # sizes 20,30,40,50,60,70
python3 benchmark/plot_benchmark.py
```

## What the benchmark circuit is

A 1-D `absdelay` delay-line alone is trivially banded, so both solvers are
O(n) and there is no measurable difference. To expose the solvers' behaviour
the benchmark drives an **L x L resistor mesh** with the absdelay delay-line
(left column). The 2-D mesh produces realistic LU fill where ordering quality
matters — which is exactly where KLU (AMD/BTF ordering + symbolic reuse) beats
Sparse 1.3 (Markowitz). `n = L*L` nodes.

## Results (this machine, version2 ngspice)

| nodes | DC | AC | transient |
|------:|---:|---:|----------:|
|   400 | 1.2x | 1.0x | 1.6x |
|   900 | 2.7x | 1.6x | 3.1x |
|  1600 | 4.4x | 2.5x | 5.1x |
|  2500 | 5.4x | 3.2x | 5.8x |
|  3600 | 5.6x | 4.0x | 6.4x |
|  4900 | 6.5x | 4.5x | 7.0x |

(speedup = SPARSE time / KLU time; see `results/timings.csv` for absolute times)

### Takeaways
- KLU's advantage **grows with circuit size** — negligible at a few hundred
  nodes, ~5-7x by ~5000 nodes — because its better fill-reducing ordering keeps
  factorization cost far below Sparse 1.3 as the matrix grows.
- **Transient benefits most** in absolute terms (hundreds of solves reuse the
  one-time symbolic factorization), then DC sweep, then AC.
- For small or purely 1-D-sparse circuits the two solvers are comparable; use
  KLU as the default for any non-trivial design.

## Note on AC + KLU

AC analysis with KLU requires the OSDI absdelay complex-stamp fix in this
version2 ngspice (the delay-row matrix pointers are switched between the real
and complex KLU arrays on each DC<->AC transition). Without it, AC under KLU
reported a singular matrix. KLU and Sparse 1.3 AC results are bit-identical.
