# Enhancement-530: automatic Monte-Carlo from Verilog-A parameter statistics

**Scope:** a model *declares* its variability where the parameter lives, and
the simulator handles the whole Monte-Carlo loop — `(* std= / std_rel= /
dist= *)` attributes on Verilog-A parameters, a new OSDI side-table carrying
them, and **`.option osdimc`** (alias `automc`) turning every run-class
command into a fresh trial. No `reset`, no netlist re-expansion, no
`gauss()`/`agauss()` expressions in the deck.

**Suite:** [`examples/osdimc_examples/`](../examples/osdimc_examples/) —
24 checks, both solvers, including distributions *measured* over 300
trials. The full 444-suite sweep is ALL OK on the committed binaries;
cargo fast + slow suites pass; the 13-model CMC corpus compiles
zero-warning.

## The attributes (compiler)

LRM 2.9 attributes are the sanctioned vendor-extension vehicle, and the
statistics ones follow the ecosystem's own conventions — quantities are
numeric literals, enumerations are strings, exactly like `type="instance"`:

```verilog
(* std=25.0 *)                  parameter real r  = 1000.0 from (0:inf);
(* dist="uniform", std=2e-4 *)  parameter real g  = 1e-3;   // std = half-width
(* std_rel=0.05 *)              parameter real k  = 2.0;    // σ = 5 % of nominal
(* type="instance", std=10.0 *) parameter real dr = 0.0;    // per-device mismatch
```

`std` is an absolute standard deviation, `std_rel` one relative to the
resolved nominal, `dist` picks `"gauss"` (default) or `"uniform"` (where
the value is the interval's HALF-WIDTH — "sigma of a uniform" is ambiguous,
so the manual says which). Six diagnostics guard the surface: a negative or
non-literal sigma and `std` beside `std_rel` are located **errors**; an
unknown distribution, statistics on a non-real parameter or a `localparam`,
and `dist` without a sigma are located **warnings**.

## The transport: a side-table, not an ABI change (compiler)

The values ride a new `OSDI_STAT_PARAM_{COUNTS,INFOS}` symbol pair — the
same mechanism E-401's terminal-short and the absdelay tables use — as
16-byte `{param_id, dist_flags, std}` records whose ids mirror the
`param_opvar` ordering exactly. The descriptor struct is untouched: an old
object simply lacks the symbols and carries no statistics, an object with
them loads in an old simulator unchanged. After E-529's audit of what
descriptor-layout drift costs, not touching the stride was the entire
design constraint.

## The engine: every run is a trial (ngspice)

With `.option osdimc` set, `if_run` starts a new trial for every run-class
command (`run`, `op`, `tran`, … — `resume` deliberately never redraws):
each statistical parameter is written nominal + draw through the ordinary
parameter setter — the `alter` path, so no re-parse and no `reset` — and
the existing setup/temperature machinery derives everything downstream,
node-collapse re-decisions included (E-471's rebuild logic applies
unchanged).

* **The first run after sourcing is the nominal baseline.** A parameter the
  deck never set has its nominal resolved by the model's own setup
  (E-476 recorded that defaults are applied there), so nominals are only
  knowable after one pass; draws begin with the second run — uniformly,
  for deck-set and defaulted parameters alike.
* **Process vs mismatch falls out of the existing model/instance split.**
  A model parameter draws once per model card per trial — instances
  sharing the card move in lockstep, distinct cards independently. A
  `(* type="instance" *)` parameter draws independently per instance.
  Nothing new is invented; E-62's machinery carries it.
* **Draws are pure functions of (mcseed, trial, owner name, param id)** —
  splitmix64 into Box–Muller, no stored RNG state, the same (seed, salt)
  philosophy as the compiler's `$random` contract (E-527). A fresh process
  reproduces every value bit-for-bit; `.option mcseed=` changes the whole
  ensemble; trial N is re-runnable in isolation.
* **`alter`/`altermod` recenter.** A stored scalar real IS the parameter's
  new nominal — the OSDIparam/OSDImParam hook updates the table, so draws
  are always nominal + delta and never a random walk.
* **Turning the option off restores** every drawn parameter to its nominal
  on the next run; a re-`source` invalidates the table wholesale.
* `.option osdimc_verbose` prints every draw with trial, owner, value and
  nominal. Drawn values are readable per trial via the ordinary
  `@n1[param]` / `@model[param]` channel, which is how the suite collects
  its statistics.

**Deliberate bound, documented:** a draw that violates the parameter's
Verilog-A `from` range fails that run with the device's own located range
error, exactly as the same `alter` would — the descriptor does not export
ranges, so size sigmas accordingly (README_OSDI and handbook §3.6 both say
so). Correlated parameters are future work.

## What the suite measures

Not just plumbing — the distributions themselves, over 300 trials: gauss
σ=25 measures mean 1000.6 / sd 25.1; uniform draws fill exactly
[nominal−std, nominal+std]; `std_rel` 5 % of 2.0 measures sd 0.0998;
mismatch draws center on 0 with sd 9.65 for a declared 10. Plus bit-exact
cross-process determinism, seed sensitivity, per-instance independence
beside per-card lockstep, recentering, restore-on-disable, an
attribute-free model provably untouched, and all six diagnostics. The
draw machinery adds no measurable per-trial overhead (0.036 s vs 0.038 s
for 51 trials with PSP103 in the circuit, draws on vs off).

## Documented

Handbook §2.13 (the attribute table and the composition rule: statistics
attributes compose with `type="instance"` — instance = mismatch, model =
process), §3.6 (the full workflow beside the `reset` and `alter` idioms),
and README_OSDI's new "Automatic Monte-Carlo" section.
