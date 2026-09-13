# Enhancement-621: a `.param` that calls `mvnorm()` is inlined like one that calls `agauss()`

**Scope:** `src/frontend/inpcom.c` — `mvnorm` joins the list of random functions whose
`.param` is turned into a `.func` and inlined into every line that reads it
(`inp_fix_agauss_in_param()`); `src/frontend/inp.c` — the B-source evaluation of those
functions (`eval_agauss()`) takes `mvnorm(i)`, one argument, through
`mc_corr_component()`. `examples/mcfastpath_examples/` grows 7 → 10 checks; the
[statistics guide](../docs/internals/ngspice_internals/ngspice_statistics.md) §5.
**ngspice only.** F1 of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md).

**Suites:** [`mcfastpath_examples`](../examples/mcfastpath_examples/) 10 of 10;
`montecarlo`, `yield`, `dcenter`, `lhs`, `savemc`, `writemc`, `osdimc`, `mcpolicy` green;
full sweep 505 of 505.

## What was wrong

```spice
.param pa = agauss(1000, 100, 3)
.param pm = 1000 + 50*mvnorm(1)
R1 a 0 {pa}
R2 a 0 {1000 + 50*mvnorm(1)}       ; the same draw, written in the device brace
R3 a 0 {pm}                        ; through the .param
.control
mccorr 1 1
montecarlo 5 -seed 1 -analysis op -expr direct=@r2[resistance] -expr viaparam=@r3[resistance]
```
```
montecarlo: fast path armed (2 random value bindings, no per-sample reset)
0   1.033038e+03   9.318679e+02
1   1.047202e+03   9.318679e+02
2   9.898083e+02   9.318679e+02
```

ngspice inlines a `.param` that calls `agauss`, `gauss`, `unif`, `aunif` or `limit` into
the lines that read it — the `.param` becomes a `.func`, each use a call, each use its own
draw (HSPICE's rule) — and that inlining is what lets `montecarlo`'s fast path see the
draw in the device's brace and re-draw it per sample (Enhancement-346). `mvnorm`, this
project's correlated draw (Enhancement-151), was not on that list: a `.param pm = 1000 +
50*mvnorm(1)` stayed a parameter evaluated once at expansion, the device's `{pm}` reached
the fast path as a constant, and the moment any *other* random binding armed the path
the correlated parameters kept one value for the whole run — σ = 3·10⁻¹² over 200
samples on the guide's matched divider, a yield of 0 % or 100 % with full confidence.
An `mvnorm`-only deck never armed the path and was right; the reset idiom was right;
`highsigma`, `wcd`, `mcsample lhs` were right. Only `montecarlo` with an `agauss`
beside the `mvnorm` — the guide's own process-plus-mismatch idiom — was wrong.

## What changed

`mvnorm` is on the list. A `.param` that calls it is inlined per use like the others;
the brace carries the call, the fast path counts it as a random binding and re-evaluates
it per sample, and a deck of correlated `.param`s alone arms the path too. Within a
sample every use reads the same correlated component — `mc_corr_component()` draws the
vector once per sample and `mc_sample_advance()`, which the fast path raises per pass,
clears it — so the two channels of one parameter (`{pm}` and a direct
`{…mvnorm(1)}`) are equal on every row, as the reset path had them. Before `mccorr`
registers a matrix the function is an independent draw per use, as it always was.

The B-line side follows: the inlining puts `mvnorm(1)` into a B-source that reads such
a `.param`, and `eval_agauss()` — which replaces the random calls in B-lines by a value
at deck load — now evaluates it (one argument, the index). A B-source with a bare draw
disarms the fast path (Enhancement-473, unchanged), and the reset path gives the same
per-sample equality.

```
montecarlo: fast path armed (3 random value bindings, no per-sample reset)
0   1.016845e+03   1.016845e+03
1   9.549450e+02   9.549450e+02
2   1.010633e+03   1.010633e+03
```

On the matched divider beside an unrelated `agauss`: σ = 53.4 and 51.8 on the two
correlated parameters, ρ = 0.907 for the 0.9 asked — where it was 3·10⁻¹² and a frozen
pair.

## Verification

| check | result |
|---|---|
| `{pm}` beside a direct `{1000+50*mvnorm(1)}` and an `agauss`, `montecarlo 6` | the fast path arms with 3 bindings; `pm` re-draws every sample and equals the direct brace on every row |
| the same with `B1 b 0 v=pm` | the bare draw disarms the path; on the reset path `direct` = `viaparam` = the B-source, every sample |
| the matched divider (`mccorr 2 1 0.9 0.9 1`) beside `.param r3 = agauss(…)`, 200 samples | σ ≈ 50 on each, ρ ≈ 0.9 on the fast path |
| the 7 existing checks; `montecarlo`, `yield`, `dcenter`, `lhs`, `savemc`, `writemc`, `osdimc`, `mcpolicy` | unchanged |
| `mcfastpath_examples` | 10 / 10 |
| full sweep | 505 of 505 |
