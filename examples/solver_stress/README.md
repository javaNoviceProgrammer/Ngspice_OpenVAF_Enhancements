# Solver stress test — KLU vs SPARSE 1.3 on large circuits

ngspice ships **SPARSE 1.3** (Markowitz pivoting) as its default direct linear
solver. **KLU** (AMD ordering + block triangular form + cheap numeric refactor)
is opt-in with `.options klu`. Which one wins is entirely a function of the
matrix's *sparsity structure*:

* **1-D / tridiagonal** circuits (RC ladders, long lines) fill in almost
  nothing, so both solvers are `O(N)` and KLU's extra setup makes it marginally
  *slower* — this is the regime the older `benchmark_examples/[F]` measured.
* **2-D / 3-D meshes** (power grids, substrate/thermal networks, large RC
  parasitics) fill in heavily, and the *cost and quality of the fill-reducing
  ordering* dominate the solve. This is where the two solvers diverge — and the
  regime this study targets.

## What it does

`stress.py` generates parametric resistor networks of three topologies and
sweeps their size, running each size under **both** solvers with `.options acct`
so the accounting separates the *solver* cost (reorder / factor / solve) from
the identical device-load cost:

| topology | builder | size N | character |
|---|---|---|---|
| `ladder1d` | 1-D chain | up to 80 000 nodes | tridiagonal — KLU's worst case |
| `mesh2d` | s×s grid | up to 200×200 = 40 000 | 2-D fill-in — KLU's sweet spot |
| `mesh3d` | s×s×s cube | up to 28³ ≈ 22 000 | 3-D fill-in — heavy |

Every node carries a 1 MΩ shunt to ground (keeps the DC system nonsingular) and
neighbours are joined by 100 Ω resistors; a 1 mA source injects at one corner.
Recorded per (topology, size, solver): matrix reorder/factor/solve and total
analysis time, circuit fill-in non-zeroes, peak RSS (`/usr/bin/time -l`), and a
DC-op correctness check (max |V_klu − V_sparse| at two probe nodes). A separate
transient study drives a fixed 2-D mesh with a cap at every node and a pulsed
source, isolating the *repeated-factorisation* regime where KLU's numeric
refactor pays off.

## Running

```sh
python3 stress.py          # writes results.json  (a few minutes)
python3 plot_stress.py      # writes plots/*.png
```

Point `NGSPICE_BIN` at a different binary to compare builds. The sweep stops
growing a topology once a solver's analysis time exceeds ~30 s, so SPARSE's
slow large-mesh reorder can't run away. **Timing numbers are machine-dependent**
— [RESULTS.md](RESULTS.md) records the reference machine; regenerate on yours.

## Files

* `stress.py` — generators + sweep + transient study → `results.json`
* `plot_stress.py` — `results.json` → `plots/*.png`
* `RESULTS.md` — the reference-machine numbers and the takeaways
