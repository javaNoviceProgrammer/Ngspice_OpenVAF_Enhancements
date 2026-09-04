# Large circuits — speed and correctness, Sparse 1.3 vs KLU, OSDI vs built-in

**Date:** 2026-09-04 · **Commit under test:** `7a45a15a` (plus the CI binaries commit) ·
**Binaries:** locally built `OpenVAF-master-20260610/target/opt/openvaf-r` and
`ngspice-46/build/src/ngspice` · **Machine:** Apple M2 Ultra, 24 cores, 64 GB ·
**Script:** [`examples/benchmark_examples/large_bench.py`](../../examples/benchmark_examples/large_bench.py)
(regenerates every number below; results in `large_results.json`).

The question was simple: at thousands to tens of thousands of Verilog-A device
instances, do the two linear solvers still agree, how far apart are they in
cost, and how does a compiled compact model compare with ngspice's hand-coded
twin of the same physics? The 2026-07 solver notes had answered it to 380
bipolar instances and 4 900 resistor nodes
([`ngspice_solver_notes.md`](../internals/ngspice_internals/ngspice_solver_notes.md));
this sweep goes to **40 000 BSIM4 MOSFETs** and **67 000 OSDI instances**, adds
PSP 103 and HiCUM L2, and runs every deck under both solvers with a built-in
twin where one exists.

**Result: the two solvers agree everywhere — to 1e-15 on every node of every
operating point, 1e-13 on every transient probe, exactly on AC — and KLU is
the only solver that finishes the larger decks in reasonable time. The OSDI
compact models agree with their built-in twins to 1.6e-9 V at DC and to a 1 %
per-stage delay in transient. What the sweep turned up is not a wrong answer
but four things that cost time or mislead at scale**, the first of which is
worth an enhancement.

| # | finding | severity |
|---|---|---|
| [F1](#f1--the-osdi-mosfet-operating-point-falls-into-gmin-stepping-where-the-built-in-converges-directly) | a chain of 100 OSDI BSIM4 (or PSP 103) inverters needs dynamic gmin stepping for its operating point where the built-in BSIM4 converges in 9 iterations; the built-in only reaches that regime at 300 stages. The models call no `$limit`, so Newton runs un-limited. Cost: the op is 5–6× slower per device than the twin's, and the whole run 2.4× (KLU) to 3.8× (Sparse) | medium — cost and robustness, answer unchanged |
| [F2](#f2--under-klu-a-long-inverter-chain-is-declared-singular-at-its-last-node) | under KLU the plain-Newton attempt on a long inverter chain ends in *"singular matrix: check node s1000"* — always the chain's last node — and only then falls back to gmin stepping; Sparse fails the same attempt without a verdict. Insensitive to BTF, scaling, gmin and a 1 GΩ leak on that node; the built-in twin does it too from 300 stages. The answer is unaffected | low — a misleading warning |
| [F3](#f3--rusage-reports-a-negative-fill-in-under-klu) | `rusage` prints *"Circuit fill-in non-zeroes = -1002"* under KLU on a chain: the formula `lnz + unz − nz` omits KLU's off-diagonal-block entries | low — cosmetic. **Fixed** |
| [F4](#f4--the-bsim4-source-prints-a-line-per-instance-per-setup) | BSIM4's Verilog-A prints *"RECALCULATION for no K1 or K2"* from a `$strobe` twice per instance per setup — 13 000 lines on a 6 400-device deck, 80 000 on the 40 000-device one — and its leading newline leaves the `OSDI <inst>` head on a line of its own | low — model-side noise. **Fixed** (simulator side: shown 5 times, then counted; the head follows the newline) |

The measurements that hold are in [What was measured and holds](#what-was-measured-and-holds).

## Method

Four circuit families, each generated at three or four sizes, each written
once per (device kind, solver) and run in batch mode with `op`, `rusage all`,
`tran`, `rusage all`. The op solution (every node voltage) and two transient
probes are kept per run and diffed across solvers and across twins.

| family | topology | OSDI devices | built-in twin | sizes (equations) |
|---|---|---|---|---|
| **chain** | N-stage inverter chain, 5 fF per node, pulse in — chain-like, zero fill-in | BSIM4 4.8 (`bsim4.va`), PSP 103 | `nmos/pmos level=14 version=4.8` | 100 · 1 000 · 5 000 · 20 000 stages (105 – 20 005) |
| **mesh** | M×M grid of 1 kΩ resistors with a diode to ground at every node, pulse at a corner — dense fill-in | `nres.va` + `vadiode.va` | `r` + `d` (same card) | 30 · 60 · 100 · 150 (902 – 22 502) |
| **mosgrid** | M×M grid of BSIM4 inverters, each driven by the cell above and coupled by 10 kΩ to the cell beside it — 2-D coupling through a real compact model | BSIM4 | level 14 | 20 · 40 · 70 · 100 (405 – 10 005) |
| **hicum** | N common-emitter HiCUM L2 stages on one supply | HiCUM L2 3.0 (thermal node tied) | — | 300 · 1 000 (3 005 – 10 005) |

Transients: chain `20p 3n`, mesh `50p 3n`, mosgrid `20p 2n`, hicum `20p 3n`.
Per-run timeout 500 s. The rusage blocks give the analysis time, the load /
reorder / factor / solve split, iteration counts, fill-in and peak memory.

## Speed — Sparse 1.3 vs KLU, same deck

| deck | devices | equations | Sparse 1.3 | KLU | Sparse/KLU | fill-in Sparse / KLU |
|---|---:|---:|---:|---:|---:|---:|
| chain 100 · BSIM4 OSDI | 200 | 105 | 0.52 s | 0.18 s | 2.9× | 0 / 0 |
| chain 1 000 · BSIM4 OSDI | 2 000 | 1 005 | 3.34 s | 1.72 s | 1.9× | 0 / 0 |
| chain 5 000 · BSIM4 OSDI | 10 000 | 5 005 | 28.2 s | 12.1 s | 2.3× | 0 / 0 |
| chain 20 000 · BSIM4 OSDI | 40 000 | 20 005 | **142.6 s** | **52.1 s** | 2.7× | 0 / 0 |
| chain 5 000 · BSIM4 built-in | 10 000 | 5 005 | 7.44 s | 5.03 s | 1.5× | 0 / 0 |
| chain 1 000 · PSP 103 OSDI | 2 000 | 5 005 | 12.0 s | 10.4 s | 1.2× | 0 / 0 |
| hicum 1 000 | 1 000 | 10 005 | 0.62 s | 0.53 s | 1.2× | 0 / 2 |
| mesh 60 · OSDI | 8 700 | 3 602 | 1.93 s | 0.44 s | 4.4× | 98 k / 99 k |
| mesh 100 · OSDI | 29 800 | 10 002 | 13.2 s | 2.35 s | 5.6× | 368 k / 358 k |
| mesh 150 · OSDI | 67 200 | 22 502 | **54.2 s** | **6.9 s** | 7.9× | 1 028 k / 943 k |
| mosgrid 40 · BSIM4 OSDI | 3 200 | 1 605 | 22.6 s | 2.16 s | **10.5×** | 102 k / 30 k |
| mosgrid 40 · built-in | 3 200 | 1 605 | 2.64 s | 1.04 s | 2.5× | 44 k / 30 k |
| mosgrid 70 · BSIM4 OSDI | 9 800 | 4 905 | **> 500 s (timed out)** | 8.93 s | > 56× | — / 133 k |
| mosgrid 70 · built-in | 9 800 | 4 905 | 48.8 s | 5.19 s | 9.4× | 305 k / 133 k |
| mosgrid 100 · BSIM4 OSDI | 20 000 | 10 005 | not run | 23.1 s | — | — / 343 k |

Three regimes, as the solver notes predicted from topology:

* **Chains** (no fill-in): KLU 1.2–2.7× ahead. On the *built-in* chain the gap
  is the 1.5× of setup reuse and cache-friendly refactoring; on the *OSDI*
  chain it widens to 2.3–2.9× because of F1 — the op's many factorizations
  weigh more under Sparse. The 2026-07 finding that a ladder runs 5–8 %
  *faster* under Sparse does not carry to a MOSFET chain: an inverter chain is
  not tridiagonal (each stage's gate couples to the previous output), and the
  OSDI op adds the factorization count.
* **Meshes** (fill-in 100–1 000 k): KLU 4–8×, growing with size. Both solvers
  produce nearly the same fill-in here; the difference is Markowitz
  re-pivoting on every factorization versus KLU's fixed ordering.
* **A compact-model grid**: the same 1 605 equations carry **102 k fill-in
  under Sparse with the OSDI model and 44 k with the built-in** — identical
  structural non-zeros (11 128) and identical KLU fill-in (30 k). Sparse's
  numerical pivoting reacts to the OSDI entries' magnitudes and chooses a
  worse ordering, on top of F1's extra factorizations: 10.5× at 1 605
  equations, and at 4 905 the Sparse run does not finish in 500 s where KLU
  takes 9 s.

**Where the time goes**, mosgrid 40, OSDI BSIM4, transient: Sparse — load
3.0 s, reorder 0.8 s, factor 18.2 s, solve 0.4 s of 22.6 s; KLU — load 1.76 s,
reorder 0.01 s, factor 0.18 s, solve 0.02 s of 2.13 s. Under KLU the model
evaluation (the load) is 83 % of the run; under Sparse the factorization is
80 %.

## Speed — OSDI vs the built-in twin, same solver

| twin | size | solver | built-in | OSDI | OSDI / built-in |
|---|---:|---|---:|---:|---:|
| BSIM4 chain | 1 000 | KLU | 0.68 s | 1.72 s | 2.5 |
| BSIM4 chain | 5 000 | KLU | 5.03 s | 12.1 s | 2.4 |
| BSIM4 chain | 5 000 | Sparse | 7.44 s | 28.2 s | 3.8 |
| BSIM4 grid | 40 | KLU | 1.04 s | 2.16 s | 2.1 |
| BSIM4 grid | 40 | Sparse | 2.64 s | 22.6 s | 8.6 |
| BSIM4 grid | 70 | KLU | 5.19 s | 8.93 s | 1.7 |
| R + D mesh | 100 | KLU | 2.16 s | 2.35 s | 1.09 |
| R + D mesh | 100 | Sparse | 13.9 s | 13.2 s | 0.95 |

Per device and Newton iteration under KLU, the transient costs 1.9–2.0 µs for
an OSDI BSIM4 against 0.97 µs for the built-in (the 1.9× of the E-74
ring-oscillator benchmark, unchanged at 40 000 devices), 2.1 µs for PSP 103,
1.6 µs for HiCUM L2, and 0.5 µs for the two-line resistor and diode models.
The trivial models cost the same as their built-ins: the OSDI overhead is per
evaluation of a large model, not per instance.

**Peak memory** (KLU, transient): OSDI BSIM4 12.6 MB per 1 000 devices at
40 000 devices (506 MB) against 9.7 MB for the built-in; PSP 103 38 MB per
1 000; HiCUM L2 51 MB per 1 000 (five terminals, ten equations each); the
resistor-diode mesh 3.4 MB per 1 000 instances. Sparse holds about 27 % less
than KLU on the same deck (370 vs 506 MB on the 40 000-device chain).
Netlist loading and parsing of a 60 000-line deck take under 0.1 s.

## Correctness

**Sparse vs KLU, same deck** — the whole op solution and both transient
probes, every size, every kind:

| family | max |op Sparse − op KLU| over all nodes | max transient probe difference |
|---|---:|---:|
| chain (BSIM4 OSDI, built-in, PSP 103) | 1.0e-16 V | 9.9e-15 V |
| mesh (OSDI, built-in) | 0 – 1.7e-27 V | 0 – 1.6e-27 V |
| mosgrid (BSIM4 OSDI, built-in) | 1.0e-16 V | 1.5e-15 V |
| hicum | 0 | 0 |
| AC, mesh 100 OSDI, 46 points, dB and phase at the centre and far corner | — | **0** |
| DC sweep, chain 1 000 OSDI, 61 points | — | 1.0e-16 V |

Both solvers hit identical timepoint counts and rejected-step counts on every
deck. The transient differences on the chains (1e-14) are the accumulation of
last-bit rounding over 640 Newton iterations; the mesh differences are zero
because its Newton converges in three iterations.

**OSDI vs built-in twin, same solver** — chains at 100, 1 000 and 5 000 stages:
every node voltage of the op agrees to **1.606e-9 V**, the same figure at all
three sizes, so the DC physics of `bsim4.va` and level 14 is the same to the
solver's tolerance. In transient the probe difference is 0.18 V at stage 20
and 0.047 V at stage 5, which is timing, not level: the 0.6 V crossings sit
**0.6 ps per stage later** with the OSDI model (3.0 ps at s5, 11.7 ps at s20,
swings −0.04..1.25 V on both sides) — the same 1 % the E-74 ring oscillator
showed. The mesh twins differ by 6.6e-4 V (the `vadiode.va` transit-time
formulation against the built-in's), the BSIM4 grid twins by 0.035 V, again a
timing shift on the driven cells.

---

## F1 — the OSDI MOSFET operating point falls into gmin stepping where the built-in converges directly

| deck, `op` only | built-in level 14 | OSDI BSIM4 |
|---|---:|---:|
| 1 inverter | — | 7 iterations |
| 10-stage chain | — | 36 iterations |
| 100-stage chain | **9 iterations** | **333 iterations, dynamic gmin stepping** |
| 100-stage chain, `.nodeset` on every node at its DC value | — | 197 iterations, gmin stepping still needed |
| 100-stage chain, `gminsteps=0 srcsteps=10` | — | source stepping *fails* after 35 552 iterations |
| 300-stage chain | 36 iterations, gmin stepping | — |
| 1 000-stage chain | 243 iterations, gmin stepping | 333 (Sparse) / 126 (KLU), gmin stepping |
| 20 000-stage chain | — | 1 154 (Sparse) / 165 (KLU), gmin stepping |
| 40×40 grid | 9 | 167 (Sparse) / 70 (KLU), gmin stepping |
| 100-stage chain, PSP 103 | — | 387 (Sparse) / 90 (KLU), gmin stepping |

The plain Newton attempt from the zero initial guess fails on a long inverter
chain and ngspice falls back to dynamic gmin stepping. That happens to the
built-in too, from about 300 stages — but the OSDI model reaches the same
regime at **100** stages, and needs it even from a nodeset that is the DC
answer to a few millivolts. It is not gmin: a 1e12 Ω leak on every node, or
`gmin=1e-9`, changes nothing, and the built-in converges in 9 with `gmin=0`.
It is step limiting. ngspice's `b4ld.c` limits every junction and channel
voltage step with `DEVfetlim` / `DEVpnjlim` in its load routine; a Verilog-A
model gets the same only by calling `$limit`, which the OSDI interface
supports (`load_limit_rhs_*`, `osdi_pnjlim` / `osdi_fetlim` in
`osdicallbacks.c`, Enhancement-353) and which HiCUM, VBIC, EKV 2.6 and
`diode_cmc` use — but **`bsim4.va` and `psp103.va` contain no `$limit` at
all**, so each stage's un-limited Newton step over-drives the next, and the
error grows along the chain until only gmin stepping can bring it back.

The cost is in the table above: the op is 5–6× slower per device than the
twin's (chain 5 000: 9.7 s vs 1.5 s under Sparse, 1.8 vs 0.32 s under KLU),
and since every factorization of the op weighs more under Sparse, that solver
shows it as a 3.8× whole-run gap where KLU shows 2.4×. The transient is not
affected (its initial guess is the converged op and the timestep bounds the
step).

Two ways to close it, neither done here: the model-side one is a `$limit` in
`bsim4.va`/`psp103.va` (a model-author matter; the CMC sources ship without
one); the simulator-side one is what every built-in MOSFET already does —
apply `DEVfetlim`/`DEVpnjlim` to an OSDI MOSFET's terminal voltages in the
Newton loop when the model calls no `$limit` of its own. The second is worth
an enhancement: it would apply to every compiled MOSFET model at once.

The two solvers' iteration counts differ on the same deck (333 vs 126) because
of F2: KLU's singular verdict aborts the doomed plain-Newton attempt early and
goes straight to gmin stepping; Sparse runs the attempt to its iteration
budget first. The answers agree to 1e-16.

## F2 — under KLU a long inverter chain is declared singular at its last node

```
chain 1000, built-in, .option klu:
  Warning: singular matrix:  check node s1000
  Note: Starting dynamic gmin stepping
  Warning: singular matrix:  check node s1000
  Note: Dynamic gmin stepping completed
```

The node named is the chain's last one at every length (s100, s300, s1000),
for the built-in from 300 stages and for the OSDI model from 100; 12 such lines
on the OSDI chain, 4 on the built-in. `klu_factor` marks a BTF singleton block
singular when its one entry is exactly zero (`IS_ZERO(s)`); the last node's
column is such a singleton (nothing but itself depends on its voltage at DC),
and in the un-limited Newton excursion of F1 its conductances underflow. The
verdict is insensitive to `klu_btf=off`, `klu_scale=none`, `gmin=1e-9`,
`gmin=0` (669 iterations, still singular) and a 1 GΩ resistor on that node;
`klu_ordering=colamd` avoids it and then takes Sparse's iteration count.
Sparse's factorization of the same excursion produces no verdict, only a
non-converging Newton. Neither path changes the answer, but the warning sends
a user to inspect a node that is fine, on a deck that will converge a moment
later.

## F3 — `rusage` reports a negative fill-in under KLU

`Circuit original non-zeroes = 5008 / fill-in non-zeroes = -1002 / total
non-zeroes = 4006` on the 1 000-stage chain under KLU. `cktacct.c` computes
the KLU fill-in as `Numeric->lnz + Numeric->unz − nz`, which counts only the
entries inside the diagonal blocks' L and U; the 1 002 entries KLU keeps in
its off-diagonal-block array (`Numeric->nzoff`) are left out, so a block-
triangular matrix with no fill-in at all reports a negative one. Cosmetic;
the mesh, which has one large block, reports the right order of magnitude.

**Resolved (2026-09-04, after the sweep).** The accounting (`cktacct.c`) now
reads the factor as KLU stores it: `lnz + unz − n + nzoff`, since KLU counts
the diagonal in both L and U (`klu_kernel`: "1 added to lnz for diagonal", and
again for `unz`; a singleton block adds one to each) and keeps the entries
outside the diagonal blocks of its block-triangular form in `nzoff`. The
1 000-stage chain reports `fill-in 0, total 5008`, the same as Sparse; the
30×30 mesh 15 222 against Sparse's 15 720 (different orderings). A second
defect fell out of the same case: in this KLU build the *Sparse*-mode total
read 0 on every deck (the `#ifdef KLU` branch answered 0 whenever KLU was not
in use, instead of asking Sparse); it now reports the count. Pinned in
`klu_tuning_examples` (+3) on a one-way chain whose every coupling entry lives
in the off-block array.

## F4 — the BSIM4 source prints a line per instance per setup

```verilog
$strobe("\n RECALCULATION for no K1 or K2");     // bsim4.va:4677
```

fires for every instance whose card gives neither `k1` nor `k2` — every
instance of the default card — once at setup and once at the temperature
update: 6 399 lines on the 3 200-device grid, 80 000 on the 40 000-device
chain, on every `reset`. The message's leading newline also defeats the
display callback's one-head-per-line rule (`osdicallbacks.c`): the `OSDI np2`
head is written, then the newline, and ngspice's next `Note:` lands beside the
head. This is the model's choice, and the cost in time is invisible next to
the op; it is noted because a 40 000-device log with 80 000 identical lines
buries every real diagnostic in it.

**Resolved (2026-09-04, after the sweep) — on the simulator's side.** The
model keeps its line; the display funnel (`osdicallbacks.c`) now treats it
the way ngspice treats its own repeated warnings. Identical complete lines
(the text after the `OSDI <inst>: ` head, newline-terminated) are shown five
times within one run of output and then counted, and each count is reported
as one line when the run ends — a Newton iteration or setup begins, or a
flush ends: *"OSDI: " RECALCULATION for no K1 or K2" was repeated 3195 more
times by other instances (last from OSDI np0_0)"*. Messages are keyed by
their text in a ring of the 64 most recent distinct texts, so a constant line
survives being interleaved with a per-instance one (a model that prints
both) at a bounded cost per message; partial lines (`$write` continuations)
are never coalesced, so line assembly is untouched; the first occurrences
print exactly as before. The 3 200-device grid's 6 400 lines are now 10 plus
two summaries. And a message that begins with newlines emits them first and
then puts the head in front of its first character, so `OSDI np2` no longer
sits alone on a line. Pinned in `display_examples` (18 → 22) with a fixture
that prints one constant and one distinct line per instance; the 27 suites
that pin display output, and the full 453-suite sweep, pass.

---

## What was measured and holds

* **Both solvers, every analysis, every size**: identical op solutions to
  1e-15, identical transient timepoint and rejection counts, probes to 1e-13,
  AC to the last bit, DC sweeps to 1e-16 — on decks of up to 22 502 equations
  and 67 200 OSDI instances.
* **KLU scales.** Chain-like: 2.0 µs per OSDI BSIM4 device and iteration at
  40 000 devices against 1.3 µs at 200 — a 1.5× drift over 200× in size, all
  of it in the model load (the factorization is 3 % of the run). Mesh: 6.9 s
  for a million-entry fill-in at 22 502 equations. Grid: 23 s for 20 000
  BSIM4 MOSFETs at 10 005 equations.
* **Sparse 1.3 does not, past a few thousand equations of coupled compact
  models**: the 9 800-MOSFET grid does not finish in 500 s (KLU: 9 s), and the
  40 000-device chain spends 53 of its 143 s in the op.
* **OSDI evaluation cost is per model complexity, not per instance**: the
  resistor and diode models run at built-in speed; BSIM4 at 1.9–2.5× the
  hand-coded twin (the E-74 ratio, unchanged at scale); PSP 103 and HiCUM L2
  at 2.1 and 1.6 µs per device-iteration under KLU.
* **HiCUM L2 at 1 000 stages** (10 005 equations, thermal nodes tied) runs in
  0.5 s under either solver, six op iterations: the model's own `$limit` calls
  do their job.
* **Memory is linear** in device count for every model, 3.4–51 MB per 1 000
  instances depending on the model, and the largest deck run (67 200
  instances) peaks at 232 MB.
* **Netlist handling is not a bottleneck**: a 60 000-line deck loads and
  parses in under 0.1 s, and the OSDI setup of 40 000 instances is inside the
  op's 8 s under KLU.

## Coverage, honestly

Four topologies and four models, transient-led with an op, one AC and one DC
sweep. Not measured: post-layout parasitic networks with capacitive coupling
(the mesh is resistive with diodes), noise and pole-zero at scale, multiple
model types in one deck, the `sweep`/`montecarlo` fast paths at these sizes,
and any deck above 22 502 equations. The KLU singular verdict of F2 was
bracketed but not traced to the exact iterate at which the entry underflows.
