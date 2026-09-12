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

Enhancement-614 (checks 30–36, `smcdep.va`): a statistical parameter the
deck never gave is resolved by the model's setup from its default
expression, and that expression may read another parameter — a child's
binding in a hierarchy (`leaf #(.r(rl)) c1`, flattened to `c1__r`), a plain
`rb = rl`, an instance default from an instance parameter, a default from an
integer. `altermod`/`alter` of the parameter it reads now moves the nominal
the draws sit on: the entry is marked stale, its given flag cleared, the
next setup re-resolves the default and the trial's draws are applied after
that (the draw itself is the same pure function of seed, trial, owner and
id). A parameter the user gave is not re-resolved, and `unset osdimc`
restores the user's value rather than the default (hunt F3).

Enhancement-616 (checks 37–39): one parameter on both channels — `.model mm
smcres r={agauss(1000,300,3)}` with `(* std *)` on `r`. The re-source path
composed them (the re-capture after each sample's reset takes the fresh
netlist draw as the nominal); `montecarlo`'s fast path did not — its in-place
write pinned the entry, the pin was cleared at the run, and the model's delta
was applied over the *first* sample's draw on every sample, the record
contradicting itself. The fast path's re-draw is now the sample's nominal
(`OSDImcNoteRedraw`): `@mm[r] = mm:r + delta` on every row, the same delta
per sample on both paths; under `sweep` the sweep's one trial delta sits on
each point's fresh draw instead of being pinned off for the whole sweep.

Enhancement-618 (checks 40–42): the restore that the first run after `unset
osdimc` performs wrote the nominal over a value a loop command had just
pushed — `sweep rr 500 1500 500` right after the `unset` read 1000, 1000,
1500. Under an open hold a pinned entry is the bracketed command's own write
and is kept (the command restores what it pushed when it ends); outside a
hold a pin is a completed command's leftover and the restore proceeds (a
`.dc` sweep before the `unset` still gets its nominal back). The `savemc`
rows after `unset osdimc` read the devices instead of repeating the last
trial's draws.

Run `python3 verify_osdimc.py` — 42 checks, both solvers.
