# vafcodegen_examples — Enhancements 286-293

openvaf-r optimizer and code-generator defects: **eight** distinct root causes found by
a targeted robustness campaign against the committed compiler.

Five aborted the compile outright. The other three are the interesting ones: they
produced a malformed function or a wrong memory offset that the compiler happily carried
all the way to a `.osdi`. They survived because **every check that would have caught them
— the MIR verifier and the LLVM module verifier — sits behind a `debug_assert!`**, so a
release build never runs them. Rebuilding the compiler with assertions enabled and
replaying the model corpus is what surfaced them.

| # | Reproducer | Cause | Fix |
|---|---|---|---|
| 286 | `constfold.va` | folding `5/0` (also `5%0`, `i32::MIN/-1`, `1<<40`) EVALUATED the operation inside the compiler → internal error, no output. A *runtime* zero divisor was always accepted | `mir_opt/const_eval.rs`: return `Option`, decline the undefined cases, fold `+`/`-`/`*` with wrapping arithmetic |
| 287 | `orphanblock.va` | a noise operator in an `if` CONDITION lets the optimizer fold the branch; that orphaned a block, but the sweep never re-ran, so a phi kept an edge naming a value reachable only through the deleted edge — broken SSA | `mir_opt/simplify_cfg.rs`: flag the const-folded branch as a change so the orphan-collecting sweep runs again |
| 288 | `hypotclog2.va` | `hypot` declared with ONE parameter but called with two → "Incorrect number of arguments passed to called function!" | `mir_llvm/intrinsics.rs`: declare it binary, like its neighbour `atan2` |
| 289 | `hypotclog2.va` | `llvm.ctlz` is OVERLOADED and needs its type suffix; the bare name is invalid IR. It backs `$clog2` | `mir_llvm/intrinsics.rs` + `builder.rs`: register and look it up as `llvm.ctlz.i32` |
| 290 | `tempacstim.va` | `$temperature` as an operator ARGUMENT took a struct-GEP handed the FIELD type instead of the instance struct → offset computed as a flat `5*sizeof(double)` instead of `offsetof(instance, temperature)`. **The shipped compiler died with SIGSEGV (exit 139).** Same bug on the operating-point-variable read path | `osdi/inst_data.rs` (both sites): index the instance-data struct, as every sibling does |
| 291 | `casemax.va` | `max`/`min`/`abs` lower to a select with real control flow, so one in a `case` DEFAULT arm left the case's fall-through block unsealed → "block N is not sealed" | `hir_lower/stmt.rs`: seal that block where it is created — the branch just emitted is its only predecessor |
| 292 | `ssprune.va` | small-signal pruning classifies a contribution as linear in one place and replays it in another; the two can disagree, and the pass then indexed a key that was never inserted → "no entry found for key" | `sim_back/topology/small_signal_network.rs`: pruning is best-effort ("where possible") — bail out instead of crashing |
| 293 | `seconderiv.va` | one analog operator nested DIRECTLY inside another (`ddt(ddt(x))`): the inner one's result is deleted while a later linear contribution still names it OUTSIDE the data-flow graph, where the rewrite cannot reach it | `sim_back/topology/lineralize.rs`: retarget the pending entries onto the implicit unknown the inner operator became |

## What the verification actually proves

Where a fix changes a number, the check is against closed form, not against the old
binary:

* **290** — `ac_stim("ac", $temperature, 0)` reads back the nominal **300.15 K**.
* **291** — the `case` picks the right arm either way (`7` from the default, `11` from the
  item arm).
* **293** — in AC a `ddt` is `j*omega`, so a second derivative is `(j*omega)^2 = -omega^2`:
  `|I|` tracks `omega^2` over 1 Hz … 1 kHz, and `ddt(2*ddt(V))` — the formulation that
  already compiled — comes out at exactly **2x**, an independent cross-check of the new
  path against the old one.
* **288/289** — `hypot(3,4) + $clog2(100) == 12` exactly.

Two of the eight (287, and 288/289 on this platform) do **not** change any number here:
the invalid IR happened to lower as intended, and the malformed function was tolerated.
For those the assertions above are forward regression guards, and the authoritative
evidence is that an assertions-enabled compiler now accepts the module.

### A limitation this surfaced — use `.options method=gear`

Chained `ddt` in **transient** is unusable under ngspice's default trapezoidal
integration and perfectly usable under Gear:

| step | TRAP error | Gear error |
|---|---|---|
| 1 ms | −23.71 | +0.00101 |
| 100 µs | +23.79 | +0.00005 |
| 10 µs | +79.25 | +0.00005 |

(analytic 39.478.) It is **not** a divergence: consecutive timesteps alternate between
~76.8 and ~2.4, whose mean is the correct answer — a persistent ±oscillation at the
Nyquist rate that never decays, so a single sample lands wherever the parity puts it.
The amplitude is roughly constant in `h`, not growing. That is trapezoidal ringing
(trapezoidal is A-stable but not L-stable); Gear/BDF is L-stable and removes it. A
*single* `ddt` does not ring at all — only the chained form.

The behaviour is **pre-existing and bit-identical** between the pre-fix and post-fix
compilers, so Enhancement-293 neither causes nor cures it. The AC checks above are
deliberately the ones asserted; the transient workaround is `.options method=gear`.

## Verify

```bash
python3 verify_vafcodegen.py
```

Runs under both linear solvers and prints a combined verdict (14 checks).
