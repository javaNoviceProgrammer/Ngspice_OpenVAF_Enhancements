# Enhancement-667: a parameter the corner in force holds is not a `wcd` dimension — the count is of the free axes, the held ones are named, and a metric flat in the free axes says which parameters the corner pins

**Scope:** F9 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md).
ngspice: `src/osdi/osdisetup.c` (`osdimc_walk_count` gains the cornered count,
`osdimc_apply_type` consumes no coordinate for a cornered entry,
`OSDImcWalkCornered`, `osdimc_join_name`), `src/include/ngspice/osdiitf.h`,
`src/frontend/com_sweep.c` (`com_wcd`: the banner, the nothing-to-search and
flat-metric refusals). `examples/wcd_examples/` (`wcdcorner.va`, `wcdheld.va`,
eight checks; 39 per solver). Handbook
[§3.7](../docs/handbook/03-ngspice-workflows.md). **ngspice only.**

**Suites:** [`wcd_examples`](../examples/wcd_examples/) 39 of 39 per solver,
both solvers (4 of 39 fail on the E-666 binaries); `highsigma`, `osdidist`,
`mcpolicy`, `vacorner`, `cornerscmd`, `silentloss`, `sweepguard`, `hunt12diag`,
`agestate`, `osdireload`, `loopbar` unchanged; full sweep 530 of 530.

## What was wrong

[E-654](Enhancement-654.md) made a cornered parameter sit at its corner under
`.option osdimc` and not draw, and kept the `wcd` walk's dimensions from
shifting by counting the held parameter as a dimension whose coordinate the
applier consumed and ignored. So under `.option osdimc corner=ss` with `r`,
`p` and `q` cornered and `dr` free:

```
wcd: 4 statistical dimensions (0 netlist .param, 4 model-declared), analysis 'op', ...
  MPFP (standardised normal coordinates):
    u0=+4.0000 u1=-0.0000 u2=-0.0000 u3=-0.0000
```

Three of the four axes did nothing, and a metric of `p` alone ended with
*the metric does not respond to any statistical parameter (zero gradient)*,
which is not what happened: the parameter it depends on is pinned by the
corner. A deck whose every statistical parameter is cornered was refused as
*its models declare no Gaussian statistics*. The search itself found the
right point — the free axis carried the whole distance — but the count, the
coordinates and both refusals treated the held axes as free.

## What changed

- **A cornered entry is not a walk dimension.** `osdimc_walk_count` counts it
  apart, and `osdimc_apply_type` gives it no coordinate (E-654's
  consume-and-ignore is gone; `osdimc_apply_derived` already skipped it, and
  the two agree now, so a cornered parameter declared before a derived one
  no longer shifts the derived one's coordinate). `OSDImcWalkNdim` is the
  free count. The mean-shift refinement shifts the free axes alone.
- **`OSDImcWalkCornered(buf, cap)`** counts the held entries and names them
  `owner:param` — a process parameter under its model card, a mismatch one
  under each instance — cut with `...` at the buffer's end.
- **`wcd` says so.** The banner: *1 statistical dimension (0 netlist .param,
  1 model-declared; 3 held by corner ss: mm:r mm:p mm:q)*. A flat metric:
  *the metric does not respond to any free statistical parameter (zero
  gradient); 3 are held by corner ss (mm:r mm:p mm:q) and not searched —
  cannot locate an MPFP (run without the corner to search over them)*.
  Nothing free at all: *the deck draws no Gaussian .params and every
  model-declared statistical parameter is held by corner ss (2: mm:r mm:p) —
  nothing to search over*. Without a corner every message is as it was.

## Verification

| check | result |
|---|---|
| `wcdcorner` (r, p, q cornered, dr free), `.option osdimc corner=ss`, spec at R = 1050 + 4·10 | *1 statistical dimension (…; 3 held by corner ss: mm:r mm:p mm:q)*, beta 4.0000, one MPFP coordinate `u0=+4.0000` |
| the same with `-is 2000 -seed 1` | P(fail) 3.13e-5 against Φ(−4) = 3.17e-5 |
| the same, metric `@mm[p]` | the flat-metric refusal names the three held, no beta |
| `wcdheld` (every parameter cornered) | the nothing-to-search refusal names the two held; no *declare no Gaussian statistics* |
| a cornered `r` before a derived `r2 = r*0.5` (std 10), corner ss | 1 dimension, beta 4 at R = 1575 + 40 (the coordinate lands on `r2`); without the corner 2 dimensions, beta 4 |
| no corner, the four-parameter model | *4 statistical dimensions*, beta 4, as before |
| the E-666 binaries on the suite | 4 of 39 fail |

Full sweep 530 of 530 on both solvers.

## What this does not do

- `highsigma` does not walk; its sigma inflation and importance weights skip
  a cornered parameter already (E-654), and a probe of its estimate in one
  and four dimensions over three seeds scatters around the analytic tail.
- A cornered parameter under a plain `montecarlo` is E-654's flow, untouched.
