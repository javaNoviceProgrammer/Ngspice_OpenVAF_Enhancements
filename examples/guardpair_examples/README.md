# Enhancement-486 — twelve guards that one sibling had and the other did not

```
python3 verify_guardpair.py
```

65 checks, a few seconds. **24/65** against the pre-fix binary — **41** checks discriminate.

## What it is

Round 50 hunted ngspice + OSDI for an hour. OSDI itself came back clean: state
restoration holds across all nine analyses including the `hb` of E-483/484, array
instantiation builds real devices (four parallel diodes differ from one by exactly
`n·Vt·ln 4`), out-of-range instance parameters are refused by name, and round-34's
`.dc @inst[param]` finding is still fixed. What the hour actually found was one
shape, over and over:

> the check **exists** somewhere in the tree, and is simply absent next door.

Nine of the sixteen findings are that. Often the sibling is in the same directory.
Once it is ten lines away in the same function. Once it is the same file's own
history.

## The headline: a SIGSEGV from a file that declares its own size

`xspice/icm/table/table2D`. The data-row loop was driven by the **file** —
`while (*cThisPtr)` — and wrote `table_data[lLineCount - 1]` with no upper bound,
while every *other* dimension of that same file was checked: the x row, the y row,
the width of each individual data row, even a premature EOF inside the comment
block. A file declaring 3 y values and supplying 5 data rows indexed past the
allocation:

```
EXC_BAD_ACCESS (code=1, address=0x0)  table.cm`cm_table2D + 2904
```

rc = 139, no diagnostic. Too *few* rows was the mirror image: the shortfall stayed
as `calloc`'s zeros and a probe in the missing region returned `0.0` — a perfectly
plausible "no current".

Enhancement-247 had already worked in this exact file (*"fix OOB **read** +
interpolation UB on degenerate/**too-small** tables"*). It addressed the read side
and the too-small case; the **write** and the too-many case were left. The sibling
`table3D` refuses the truncated file outright — so the two disagreed about one
input, and only one of them crashed.

## The second headline: an error return used as a point count

`spicelib/analysis/cktsens.c`. `count_steps()` is declared to return a **point
count**, and E-362's overflow guard signalled failure from it with
`return(E_PARMVAL)`. `E_PARMVAL` is **11**, and the sole caller assigned the result
straight to `nfreqs` with no error test — so an "impossible" sweep ran **eleven
points**. Worse, that early return happened before `*stepsize = s`, so the step was
never written and every frequency after the first collapsed to zero.

Below it sat two silent repairs of values the *user stated*:

```c
case SENS_DECADE:
    if (low  <= 0.0)  low  = 1e-3;        /* a stated 0 Hz start, rewritten  */
    if (high <= low)  high = 10.0 * low;  /* a stated stop, rewritten        */
```

Both rewrote only the **local** copy, so the count came from the repaired bounds
while the sweep still ran from `job->start_freq`. That is why
`.sens ac dec 5 0 1meg` printed a full table of 0 Hz rows, and
`.sens ac dec 5 1k 1k` swept a full decade past the stop that was asked for.
`.ac`, `.noise`, `.disto` and `.sp` all get both cases right; the rules are now
`.ac`'s own (`acan.c`).

## Withdrawn at fix time — and why the suite pins them

Three things that looked like defects are not, and the suite holds the line so a
later pass does not "fix" them:

* **Negative capacitance and inductance.** The built-in `C` device accepts
  `C = -1u` and produces *exactly* the sign-inverted response the XSPICE model
  produces; the built-in `L` device diverges the same way at `L = -1u`
  (7.5e+288 against 1.8e+285, both ending in the same timestep abort). The two
  agree, so a negative reactance is a legitimate equivalent-circuit element here.
  Only `c = 0` / `l = 0` — a real division by zero that surfaced as
  *"Timestep too small; cause unrecorded"* — is fixed. Checks 12–16.
* **`mlin`'s `rho = 0`.** It looked like an ordinary "perfect conductor"
  idealisation and was first classified as one. Measuring it returned a bare
  `NaN`, so it is strictly positive after all — while `t`, `tand` and `d` at zero
  are genuinely fine. Checks 49–52 hold both halves.
* **`xfer`'s duplicate frequencies.** The `table` path of the same model
  deliberately allows equal successive frequencies. The fix makes the `file` path
  apply *the table path's rule*, not a stricter one of its own. Check 34.

## The rest

| # | model / file | the sibling that already had the check |
|---|---|---|
| 3 | `d_state` undefined next state → row 0 | its own `index_error`, which only covered non-contiguity |
| 4 | `file_source` non-monotonic time | `pwl`, monotonic since E-480 |
| 5 | `xfer` file path frequency column | the `table` path, ten lines above |
| 6 | `hyst` `input_domain` unbounded → 250,000× escape | `pwl` / `pwlts`, `[1e-12 0.5]` |
| 7 | `core` `h_array`/`b_array` lengths | `pwl`, which compares its pair |
| 8 | `mlin` / `cpline` / `cpmlin` geometry | the built-in `T` device |
| 9 | `poly()` diagnostics | each fault carried the other's message |
| 10 | `d_state` / `d_process` delays | 20+ digital models, `[1e-12 -]` |
| 11 | `real_gain` delay | `real_delay`, `[1e-15 -]` |
| 12 | `oneshot` rise/fall delay | 22 models — bounded here at `[0 -]`, see below |

`oneshot` is an **analog** model, so the parameter name it shares with the 22
digital models does not by itself make it the same contract. Only a *negative*
delay was measured to do harm (it killed the output entirely), and `rise_delay=0`
demonstrably works — so it is bounded at `[0 -]`, matching the evidence rather
than the digital models' convention.

## Provenance

`git -S` on the defective lines puts both headlines at **`4f29ffad`, the vanilla
upstream import** — these are pre-existing upstream defects, not regressions from
this tree's work.
