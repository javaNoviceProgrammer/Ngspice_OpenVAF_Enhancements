# Enhancement-659: quoted words on the `corners` line are unquoted — `-analysis "dc v1 0 1 0.5"`, `-output "g=v(out) / v(in)"`, `-list "ss ff"`, and a bare multi-word `-analysis`

**Scope:** F2 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md).
ngspice: `src/frontend/com_sweep.c` (`com_corners`: the `-analysis`, `-output`
and `-list` parsers). `examples/cornerscmd_examples/` (three checks added, 21
per solver). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md).
**ngspice only.**

**Suites:** [`cornerscmd_examples`](../examples/cornerscmd_examples/) 21 of 21
per solver, both solvers (the three new checks fail on the E-656 binaries);
`vacorner`, `autocorner`, `sweepanalysis`, `mcyield` unchanged; full sweep 529
of 529.

## What was wrong

```
corners -list tt ss -analysis "dc v1 0 1 0.5" -output v(out)
corners: 2 corners (tt ss), analysis '"dc v1 0 1 0.5"'
  0    tt                      nan
  1    ss                      nan
sweep: unknown command '"dc v1 0 1 0.5"'
```

ngspice's lexer treats the two quote characters differently: `'...'` forms one
word without the quotes, `"..."` one word with them, and each command strips
the survivors with `cp_unquote()`. `sweep`, `montecarlo`, `optimize`, `wcd` and
`highsigma` do ([E-432](Enhancement-432.md) and the MC hunt's F1); the
`corners` command of [E-655](Enhancement-655.md) did not. Its `-analysis` took
one word verbatim, so the double-quoted spelling — the handbook's own — reached
the command lookup with its quotes attached, every corner ran an unknown
command and recorded `nan`. `-output "g=v(out) / v(in)"` made a column named
`"g` whose expression carried a trailing quote and never resolved; `-list "ss
ff"` split into `"ss` and `ff"` and the first was refused as a corner no model
declares. Only the single-quoted form and the `-mc` forwarding (which keeps a
word that already starts with a quote) worked, and the E-655 suite had tested
the quoted form under `-mc` alone. An unquoted `-analysis tran 1u 3u` stopped at
`tran` and refused `1u` as an unknown option, where the other loop commands
collect the words up to the next flag.

## What changed

`com_corners` follows the `collect_until_flag` rule of the other loop
commands:

- **`-analysis`** collects the words up to the next flag, each unquoted, joined
  with single spaces — `"dc v1 0 1 0.5"`, `'dc v1 0 1 0.5'` and a bare
  `dc v1 0 1 0.5` are the same command. A negative argument (`-0.5`) is not a
  flag. A command longer than the buffer is refused rather than truncated
  ([E-434](Enhancement-434.md)); `-analysis` followed by a flag is refused with
  *needs a command*. Before `-mc` the analysis is still forwarded to
  `montecarlo`, re-quoted when it holds a space, as before.
- **`-output`** unquotes each token before the `name=expr` split.
- **`-list`** unquotes each token before the comma/space split.

## Verification

| check | result |
|---|---|
| `corners -list tt ss -analysis "dc v1 0 1 0.5" -output v(out)` | `analysis 'dc v1 0 1 0.5'`; 0.5 at both corners; no unknown command |
| `-list "ss ff" -output "g=v(out) / v(in)" rsh=@rm[rsh]` | two corners `ss ff`; `g` 0.5 0.5; `rsh` 115 88 |
| `-analysis tran 1u 3u -output rsh=@rm[rsh]` (bare words) | `analysis 'tran 1u 3u'`; 100 115 |
| `corners -analysis -output v(out)` | *corners: -analysis needs a command* |
| the single-quoted spelling; `-analysis "tran 1u 3u" -mc 2 …` | as before |
| the E-656 binaries on the same suite | the three new checks fail |

Full sweep 529 of 529 on both solvers.

## What this does not do

- The `-mc` forwarding is unchanged: the words after `-mc N` go to `montecarlo`
  verbatim, a word with a space quoted once, and `montecarlo` unquotes them.
- `-mc "3"` (a quoted count) is still refused as not a positive integer.
