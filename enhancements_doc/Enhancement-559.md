# Enhancement-559: a loop command's `-seed` pins the model-declared draws, and the f-string edges

**Scope:** F13 and F12 of the
[bug hunt of 2026-09-05](../docs/bug_hunts/2026-09-05_strings-mcexpr-and-osdimc-distributions.md):
the osdimc draw key and its verbose line (`src/osdi/osdisetup.c`,
`src/include/ngspice/osdiitf.h`), the loop commands' seed bracket
(`src/frontend/com_sweep.c`), the f-string pass (`src/frontend/control.c`)
and the lexer's prefixed single-quoted string (`src/frontend/parser/lexical.c`).
**ngspice only; the compiler is unchanged.**

**Suites:** [`mcpolicy_examples`](../examples/mcpolicy_examples/) 41 → 46
(one existing one-sided limit widened to a two-sided band, since it happened
to sit above both re-keyed draws), [`rawfstring_examples`](../examples/rawfstring_examples/)
19 → 23, both solvers; the Monte Carlo, high-sigma, wcd, osdimc and
distribution suites pass; full sweep 459 of 459. Handbook
[§3.6](../docs/handbook/03-ngspice-workflows.md) (the osdimc keying and the
E-537 paragraph) and [§3.10](../docs/handbook/03-ngspice-workflows.md) (the
f-string row), README_OSDI, the two suite READMEs.

## What was wrong

**F13.** E-537 mixed a loop command's `-seed` into the osdimc draw key so that
replications would be independent, but left the session-wide trial counter in
the key too. So `montecarlo 3 -seed 1 …` run twice reproduced the netlist
`agauss` values exactly and not the model-declared draws (1020.17 / 815.62 /
719.15, then 1213.59 / 1198.65 / 1133.03); `highsigma 1000 -scale 2 -seed 3`
gave 0.0594 and 0.0481 for one seed; the published `montecarlo_seed` could
not regenerate an ensemble; and a `reset` between two runs made them repeat
only when the commands before them matched too — what the draws depended on
was how many run-class commands had happened earlier in the session. On a
never-run deck, `montecarlo`'s fast path (no per-sample reset) spent its
first sample on the nominal baseline as well: the first run's new circuit
pointer restarted the count that E-537's baseline skip had just set.

**F12.** Small edges of the f-string pass. `{1e20:d}` printed
9223372036854775807 with no note — the cast to `long` is undefined for it
and saturates on arm64; `{{1+1}}` failed, rightly, but the message named a
vector `{1`; `{ }` was reported as an expression that does not evaluate;
`{1+1:.3}` — a precision without a conversion letter — was handed to the
expression evaluator with no hint that a format needs the letter; and an
unterminated `r'abc` came out of the lexer re-quoted as `r"abc`.

## What changed

* **A loop command's draws are a function of `(-seed, sample number)`.**
  Inside `montecarlo`, `highsigma` and `wcd` the draw key carries the seed and
  the sample number counted from the command's start instead of the trial
  counter; the seed defaults to 1, exactly as the netlist half's always has,
  so an unseeded run repeats itself whole and equals `-seed 1`, and the
  unseeded NOTE says so. The counter itself still advances, so the plain run
  after a loop command is a fresh trial as before. Setting the seed steps past
  the baseline and blesses a never-run deck's first circuit pointer, so the
  fast path draws on sample 0. `.option osdimc_verbose` shows the pair:
  `osdimc: trial 3: mm:r = 966.375 (nominal 1000) [sample 2 of -seed 1]`.
* **The f-string edges.** `:d` and `:i` print a whole number beyond a `long`
  exactly (through `%.0f`, flags and width kept); `:x`, `:X` and `:u` refuse a
  negative or too-large value naming it — *{-1:x}: -1 cannot be shown as hex
  (use :d for a whole number or :g for any)*; `{{1+1}}` is told *braces do not
  nest — an expression cannot start with '{' (write \{ for a literal
  brace)*; `{ }` is *an empty {}*; a colon tail with a format's shape but no
  conversion letter gets *if ':.3' was meant as a format, it needs a
  conversion letter (e, f, g, d, i, u, x, X): :.3f*, a wrong letter is named,
  and a ternary's colon gets no hint; an unterminated `r'abc` passes through
  as typed.

## Verification

| check | result |
|---|---|
| `montecarlo 3 -seed 1 -analysis op -expr ro=@mm[r]` twice, two `op`s between | `ro` 1005.891 / 1020.166 / 815.617 both times (the `op`s between draw differently) |
| the same with `-seed 2` | 803.53 / 729.98 / 1016.27 |
| the same without `-seed` | the seed-1 values; NOTE: *the random .params and the model-declared statistics are drawn from the default seed 1, so running this montecarlo again repeats them* |
| `highsigma 800 -scale 2 -seed 3` before and after a `reset` | P(fail) 0.0918484 both times (it was 0.0874 and 0.0968) |
| a never-run deck with a netlist random (fast path armed) | trials 2, 3 = samples 1, 2 of seed 1; sample 0 is a draw, not the nominal |
| `echo f"{1e20:d} {-1e20:d} {255:08X}"` | `100000000000000000000 -100000000000000000000 000000FF` |
| `{-1:x}`, `{{1+1}}`, `{ }`, `{1+1:.3}`, `{1+1:.3q}`, `{1 > 0 ? 2 : 3}` | refused naming the value; *braces do not nest*; *an empty {}*; the hint `:.3f`; *'q' is not a conversion letter*; `2` with no hint |
| `echo r'abc` | `r'abc` |
| `mcpolicy_examples`, `rawfstring_examples`; full sweep | 46 / 46, 23 / 23; 459 of 459 |
