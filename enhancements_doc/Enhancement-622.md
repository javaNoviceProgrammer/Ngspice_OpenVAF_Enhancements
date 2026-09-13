# Enhancement-622: `highsigma -inflate` scopes the netlist dimensions too

**Scope:** `src/maths/misc/randnumb.c` / `include/ngspice/randnumb.h` — the `-inflate`
scope table moves here from the OSDI side and is consulted by the netlist SSS draw
(`mc_sample_gauss()`): a dimension out of scope draws at its nominal spread and weighs 1;
the evaluator names the dimension it is about to draw (`mc_dim_push()`/`pop()`), and a
`.param → slot` alias table (`mc_dim_alias_add()`) lets a spec name the `.param` the
inliner dissolved. `src/frontend/numparam/xpressn.c` — the `.param` evaluation and the
device brace push their savemc names. `src/frontend/inpcom.c` — `inp_fix_agauss_in_param()`
records the alias when it rewrites a reader of a random `.param`
(`inp_stat_alias_register()`), and the table is cleared when a new deck is read.
`src/osdi/osdisetup.c` — `OSDImcScaleScopeAdd/Clear/Hits()` and `osdimc_scale_for()`
become views on the shared table. `examples/highsigma_examples/` grows 8 → 12 checks;
handbook [§3.6](../docs/handbook/03-ngspice-workflows.md), the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §4.1, the
suite README. **ngspice only.** F4 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`highsigma_examples`](../examples/highsigma_examples/) 12 of 12;
`mcpolicy` (E-538's own checks), `osdidist`, `agestate`, `rng`, `silentloss`,
`sweepguard`, `guardmatch`, `loopbar` green; full sweep 505 of 505.

## What was wrong

```spice
.param rr = agauss(1000, 100, 3)      ; the only statistics in the deck
R1 a 0 {rr}
highsigma 2000 -scale 3.0 -seed 1 -analysis op -inflate rr -metric -1/i(v1) -max 1150
```
```
highsigma: 2000 samples, scale (sigma inflation) = 3 on the -inflate parameters only, ...
  failures observed : 132 / 2000 (in the inflated sampling)          <- identical to the unscoped run
  NOTE    : none of the 1 -inflate parameter matched a statistical parameter in this circuit, so NOTHING was inflated and this run
            sampled the nominal spread; check the names against the model's (* std *) parameters.
```

Enhancement-538's scope table lived with the OSDI draws; the netlist's scaled-sigma
sampler (`mc_sample_gauss()`) never looked at it and inflated every Gaussian `.param` at
full `-scale` whatever the specs said. So `-inflate rr`, `-inflate r1` and
`-inflate @r1[resistance]` all "matched nothing" while `rr` was inflated regardless — the
banner and the NOTE both false — and, the damaging direction, an OSDI metric beside ten
netlist bystander `.param`s collapsed its weights to an ESS of 2.6 of 3000, and
`-inflate @mm[r] -inflate @n1[dr]` could not rescue it: the bystanders stayed inflated
and kept multiplying the weight.

## What changed

- **One scope table**, in `randnumb.c`, consulted by both kinds of draw. The OSDI entry
  points keep their names and their behaviour; the hit count now covers both.
- **The netlist SSS draw honours it.** Under a scoped run the evaluator names each
  dimension it is about to draw — a `.param` by its name (scoped by the subcircuit
  instance whose parameter it is), a device brace by its slot (`r1`, `r1:key`, `rm:r`,
  `x1.p`), the same names `.option savemc` writes in its header — and
  `mc_sample_gauss()` inflates and weighs a dimension in scope, draws the others from the
  nominal spread with weight 1. A subcircuit's device is known as `r.x1.r1` once
  expanded and matches a spec `r1` by its own name.
- **A `.param`'s name still works.** ngspice inlines a random `.param` into every line
  that reads it (`.param rr = agauss(…)` → `.func rr()`, each reader rewritten), so at
  draw time only the slot exists. The inliner now records `rr → r1` (and `rr → k` for a
  derived `.param k = rr*2`, which draws under its own name) when it rewrites the line,
  and a bare spec is expanded through the aliases when it is added. The table is cleared
  when a new deck is read and survives a `reset` — the reload has no `.param` lines left
  to record from, and `highsigma` itself resets per sample.

```
  failures observed : 132 / 2000       -inflate rr, -inflate r1: as the unscoped run, no note
  failures observed : 0 / 2000         -inflate nosuch: the nominal spread, and the note
```

The OSDI metric beside ten netlist bystanders, scoped to `@mm[r]` and `@n1[dr]`:
ESS 2.6 → **631** of 3000, P(fail) 6.3·10⁻⁷ ± 46 % (flagged as collapsed) →
**3.94·10⁻⁴ ± 14 %**, against Φ(−3.35) = 4.15·10⁻⁴ for the deck's 25 Ω and 10 Ω sigmas.

An unscoped run is untouched: no `-inflate`, no names computed, every Gaussian inflates
as before. Uniform `.param`s are bounded and were never inflated; `wcd` and `montecarlo`
have no `-inflate` and draw as before.

## Verification

| check | result |
|---|---|
| `-inflate rr` and `-inflate r1` after an unscoped run, the three in one session (resets between) | 132 / 2000 and the same P(fail) as the unscoped run, no note |
| `-inflate nosuch` | 0 / 2000 at the nominal spread; the "NOTHING was inflated" note once |
| an OSDI metric beside ten netlist bystanders, unscoped | ESS 2.6 of 3000, flagged as collapsed |
| the same, `-inflate @mm[r] -inflate @n1[dr]` | ESS 631; P(fail) within 35 % of Φ(−3.35) |
| E-538's own checks (`mcpolicy` [29]–[33]: the OSDI scoping, the accessor spelling, the note, the malformed spec) | unchanged |
| the 8 existing checks; `osdidist`, `agestate`, `rng`, `silentloss`, `sweepguard`, `guardmatch`, `loopbar` | unchanged |
| `highsigma_examples` | 12 / 12 |
| full sweep | 505 of 505 |
