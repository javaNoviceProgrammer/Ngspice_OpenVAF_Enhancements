# osdimc — automatic Monte-Carlo from Verilog-A parameter statistics

A parameter declares its own variability with LRM 2.9 attributes:

```verilog
(* std=25.0 *)                  parameter real r  = 1000.0 from (0:inf);
(* dist="uniform", std=2e-4 *)  parameter real g  = 1e-3;   // std = half-width
(* std_rel=0.05 *)              parameter real k  = 2.0;    // σ = 5 % of nominal
(* type="instance", std=10.0 *) parameter real dr = 0.0;    // per-device mismatch
```

The compiler exports them through the `OSDI_STAT_PARAM_{COUNTS,INFOS}`
side-table (the absdelay mechanism — no descriptor-ABI change; objects
without statistics simply lack the symbols), and **`.option osdimc`**
(alias `automc`) turns every run-class command into a fresh trial: each
statistical parameter is written nominal + draw through the ordinary
parameter setter — no `reset`, no netlist re-expansion, no `gauss()`
expressions in the deck.

What the suite pins (24 checks, both solvers):

- the **first run after sourcing is the nominal baseline** (defaults of
  unset parameters are only knowable after one setup pass); draws begin
  with the second run;
- **process vs mismatch falls out of the existing model/instance split**:
  a model parameter is one draw per model card per trial (instances
  sharing the card move in lockstep, distinct cards differ), a
  `(* type="instance" *)` parameter draws independently per instance;
- draws are **pure functions of (mcseed, trial, owner name, param id)** —
  a fresh process reproduces every value bit-for-bit, a different seed
  changes them, and `resume` never redraws;
- **measured over 300 trials**: gauss mean 1000.6 / sigma 25.1 for a
  declared σ = 25; uniform draws fill exactly [nominal−std, nominal+std];
  `std_rel` gives σ = 0.0998 for a declared 5 % of 2.0; mismatch draws
  center on 0 with σ = 9.65 for a declared 10;
- `alter` **recenters** a statistical parameter's nominal; turning the
  option off **restores** every drawn parameter exactly; a model without
  statistics attributes is untouched;
- diagnostics: unknown `dist` / non-real parameter / `localparam` /
  dist-without-sigma each warn (and compile); a negative sigma and
  `std` beside `std_rel` are located errors; the clean model compiles
  with zero warnings.

A draw that violates the parameter's `from` range fails that run with an
error naming the model and the offending value, plus an in-band notice
that the trial failed and the previous run's vectors remain current — the
descriptor does not export ranges, so size sigmas accordingly.

Hardened in the bug-hunt round (checks 25–29): machine writes — `.dc`
parameter sweeps, the `sweep` command's points and restores — deliberately
do **not** recenter nominals (only `alter`/`altermod` do); `reset`
restarts the MC deterministically; a non-finite draw (sigma too large) is
refused with a named warning and the parameter stays at nominal; `alter`
refuses non-representable values outright.

Run `python3 verify_osdimc.py` — 29 checks, both solvers.
