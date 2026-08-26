# Enhancement-486 — twelve guards that one sibling had and the other did not

**Files:** `src/spicelib/analysis/cktsens.c`, `src/xspice/enh/enhtrans.c`,
`src/xspice/mif/mifmpara.c`, and eleven code models under `src/xspice/icm/`
(`table/table2D`, `table/table3D`, `digital/d_state`, `xtradev/capacitor`,
`xtradev/inductor`, `xtradev/core`, `tlines/mlin`, `tlines/cpline`,
`tlines/cpmlin`, `analog/file_source`, `analog/xfer`), plus declared `Limits` in
five `ifspec.ifs` files.

**Suite:** `examples/guardpair_examples/` — 65 checks.

## Why

Round 50 hunted ngspice + OSDI for an hour. OSDI came back clean: state
restoration holds across all nine analyses including the `hb` of E-483/484, array
instantiation builds real devices, out-of-range instance parameters are refused by
name, and round-34's `.dc @inst[param]` finding is still fixed. What the hour
found instead was a single recurring shape:

> the check **exists** somewhere in the tree, and is simply absent next door.

Nine of the sixteen findings are that. Often the sibling is in the same directory;
once it is ten lines away in the same function; once it is the same file's own
history.

## The headline: a SIGSEGV from a file that declares its own size

`icm/table/table2D/cfunc.mod`. The data-row loop is driven by the **file** —
`while (*cThisPtr)` — and wrote `table_data[lLineCount - 1]` with no upper bound,
while every *other* dimension of that same file was checked: the x row, the y row,
the width of each individual data row, even a premature EOF inside the comment
block. A file declaring 3 y values and supplying 5 data rows indexed past the
allocation and crashed:

```
EXC_BAD_ACCESS (code=1, address=0x0)   table.cm`cm_table2D + 2904
```

rc = 139, with no diagnostic at all. A 12-line table file was enough.

Too *few* rows was the mirror image: the shortfall stayed as the zeros `calloc`
had supplied, the table went to `sf_eno2_set` as though complete, and a probe in
the missing region returned `0.0` — a physically plausible "no current" that no
one would question.

The sharp part is the history. `5ea36feb` — *"E-247: XSPICE table2d/table3d — fix
OOB **read** + interpolation UB on degenerate/**too-small** tables"* — had already
worked in this exact file. It addressed the read side and the too-small case; the
**write** and the too-many case were left. And the sibling `table3D` refuses the
truncated file outright (*"Not enough data in file"*), so the two models disagreed
about the same malformed input, and only one of them crashed.

Both directions are now bounded, and `table3D` — which is bounded by its `iz`/`iy`
loops and so never crashed — now warns about the surplus it silently dropped.

## The second headline: an error return used as a point count

`spicelib/analysis/cktsens.c`. `count_steps()` is declared to return a **point
count**, and E-362's overflow guard signalled failure from it with
`return(E_PARMVAL)`. `E_PARMVAL` is **11**, and the sole caller assigned the result
straight to `nfreqs` with no error test:

```c
nfreqs = count_steps(...);        /* unchecked */
for (i = 0; i < nfreqs; i++)      /* ...so an "impossible" sweep ran 11 points */
```

Measured: `.sens v(a) ac dec 2000000000 1 100` produced exactly **11 output rows**.
And because that early return happened before `*stepsize = s`, the step size was
never written, so every frequency after the first collapsed to zero. A guard whose
error return is indistinguishable from a valid answer is not a guard.

Below it sat two silent repairs of values the **user stated**:

```c
case SENS_DECADE:
    if (low  <= 0.0)  low  = 1e-3;        /* a stated 0 Hz start, rewritten */
    if (high <= low)  high = 10.0 * low;  /* a stated stop, rewritten       */
```

Both rewrote only the **local** copy. The count came from the repaired bounds while
the sweep itself still ran from `job->start_freq` — so with a stated start of 0,
`freq *= s` held every point at 0 Hz. `.sens ac dec 5 0 1meg` printed a full table
of 0 Hz rows; `.sens ac dec 5 1k 1k` swept a full decade past the stop asked for
(6 rows where `.ac` gives 1). The arithmetic predicts each observed count exactly:
6 for `dec`, 3 for `oct`, 5 for `lin`.

`.ac`, `.noise`, `.disto` and `.sp` all handle both cases correctly, so the new
rules are `.ac`'s own (`acan.c`): refuse a logarithmic sweep starting at or below
0, treat stop == start as the single point `.ac` produces, and let a **linear**
sweep start at 0 Hz because there 0 Hz is a legitimate DC point rather than
`log(0)`. Errors now leave `count_steps` out of band in an `int *errp`, and
`*stepsize` is written on every path.

## The same shape, ten more times

* **`d_state`** — `cm_set_indices()` presets `index0 = indexN = 0`, scans for a row
  matching `current_state`, and if **nothing** matched fell through and returned
  `FALSE` ("no error"), leaving the machine on **row 0**. A transition naming a
  state the file never defines therefore ran the first row of the table, silently.
  Proved by construction: with row 0 declaring `0s 0s` the outputs sat at 0
  forever; with row 0 declaring `1z 1z` they sat at 1. The one diagnostic the
  function could produce covered only the *non-contiguous* case.
* **`file_source`** — the file-driven sibling of `pwl`, which has required a
  monotonic `x_array` since E-480. This model had no such check: a time column that
  steps backwards, repeats, or starts below zero silently produced a different
  waveform (a file whose first two times were `0.0` then `-1e-6` started the output
  at 0.667 instead of 0.0). All three are one fault, so one strict-increase test
  covers them.
* **`xfer`** — the `table=` path of this model already refuses a negative frequency
  and one lower than its predecessor. The `file=` path, **in the same function ten
  lines below**, validated nothing: an out-of-order Touchstone column moved
  `max|v(out)|` from 40.0 to 20.0 with no diagnostic. The file path now applies the
  table path's own rule. A missing file also now states what it costs.
* **`hyst`** — `input_domain` was unbounded here while `pwl` and `pwlts` declare
  `[1e-12 0.5]`. With `out_lower_limit = 0` and `out_upper_limit = 1`, an
  `input_domain` of `1e6` drove the output to **250,000** — a model whose stated
  job includes clamping to those limits, silently violating that contract by five
  orders of magnitude.
* **`core`** — `PARAM_SIZE` appeared exactly once in the file (on `H_array`), yet
  `B[size-1]` and `B[size-2]` are indexed with H's size. `pwl` has carried exactly
  this paired-length check all along.
* **`mlin` / `cpline` / `cpmlin`** — no declared limits on any geometry. A negative
  microstrip length returned `max|v(b)| = 0.5011` against `0.4992` for the same
  line at `+1e-2`: not a failure anyone would notice, but a real, different,
  entirely plausible answer from a geometry that cannot exist. The built-in `T`
  device sets the precedent for the refusal — *"Fatal error: t1: td = 0 is not a
  usable value"*.
* **`poly()`** — the two failure modes were each reported with the *other's*
  message. A card with too few **coefficients** was told *"Number of connections
  differs from poly dimension"* (the connections matched); a card with too few
  **node pairs** was told *"Too few values for parameter 'coef'"* (the coefficients
  were all there). The first now prints the arithmetic instead of guessing. The
  second is genuinely ambiguous — a bare number is a legal node name, so
  `enhtrans.c` cannot tell a missing node pair from a surplus coefficient — so that
  ambiguity is now *stated* rather than resolved wrongly.
* **`d_state` / `d_process` delays** — the only two digital models of 20-plus with
  no declared limit on `clk_delay` / `reset_delay`. A negative value escaped the
  parse-time check its siblings have and surfaced instead as a generic per-event
  error, repeated once per event (80 in a longer run), that never named the
  parameter — while the machine ran on, never resetting.
* **`real_gain`** — `delay` unbounded while `d_to_real`, `real_delay` and
  `real_to_v` all bound theirs. `real_delay` uses the parameter identically.
* **`oneshot`** — `rise_delay` / `fall_delay` unbounded while 22 models bound them.

## The repair is the codebase's own pattern

Every refusal here is a shape the tree already used: `cm_message_printf` naming the
parameter and the value, then `cm_cexit(1)` where the model cannot continue —
which is what `table2D`, `table3D` and `file_source` already do for a missing file.
The declared `Limits` route was chosen for the five delay/domain parameters because
`mif/mifmpara.c` both **warns by name and clamps** to the valid range, so those
fixes cost nothing at runtime and read identically to the siblings they now match.

## What this deliberately does NOT change

Three things that looked like defects are not, and the suite pins them so a later
pass does not "fix" them:

* **Negative capacitance and inductance.** The built-in `C` device accepts
  `C = -1u` and produces *exactly* the sign-inverted response the XSPICE model
  produces; the built-in `L` device diverges the same way at `L = -1u` (7.5e+288
  against 1.8e+285, both ending in the same timestep abort). The two agree, so a
  negative reactance is a legitimate equivalent-circuit element. Only `c = 0` /
  `l = 0` is fixed — a real division by zero that had surfaced as
  *"Timestep too small; cause unrecorded"*, naming neither model nor parameter.
* **`mlin`'s `rho = 0`.** First classified as an ordinary "perfect conductor"
  idealisation. Measuring it returned a bare `NaN`, so it is strictly positive
  after all — while `t`, `tand` and `d` at zero are genuinely fine and stay legal.
* **`xfer`'s duplicate frequencies.** The `table` path deliberately allows equal
  successive frequencies; the fix gives the file path *that* rule, not a stricter
  one.

`oneshot` is bounded at `[0 -]` rather than the digital models' `[1e-12 -]`: it is
an analog model, only a *negative* delay was measured to do harm, and
`rise_delay = 0` demonstrably works. The bound matches the evidence, not the
convention.

## Provenance

`git -S` on both headline defects lands on **`4f29ffad`, the vanilla upstream
import**. These are pre-existing upstream defects, not regressions from this
tree's work.

## Verification

```
python3 examples/guardpair_examples/verify_guardpair.py     # 65/65
python3 examples/run_regression.py                          # 400/400
```

The suite scores **24/65** against the pre-fix binary, so **41 of the 65 checks
discriminate**. Every fix is paired with the control that must not move: a
well-formed table still answers `-0.001`, a valid decade sweep still gives 16 rows,
`lin` from 0 Hz is still allowed, `t`/`tand`/`d` at zero stay legal, a duplicate
`xfer` frequency stays legal, a negative capacitance still runs *and still agrees
with the built-in `C` device*, and a valid truncated `poly()` still returns 3.0.

The round-50 crash reproducer now exits 1 with
*"Too many data rows in file crash.table: the header declares 3, and row 4 is past
the end."* instead of 139.
