# Enhancement-425 — three things the compiler accepted that were not numbers

A table row that is not a row, a literal too large to be a double, and a literal
whose size is zero. All three compiled clean; two of them changed the answer.

## A corrupt row in a data file was silently dropped

A table `(0,0) (1,100) (2,20)` queried at x = 0.5 gives **50**. Replace the middle
row with `N/A N/A`, `abc def` or `--- ---` and it still compiles clean — and gives
**5**. The row simply vanishes.

Both `table_file_is_usable` and the readers in `hir_lower` did
`filter_map(|tok| tok.parse::<f64>().ok())` — non-numeric tokens silently skipped
— and the **only shape check was global token-count parity**, `nums.len() % 2 == 0`.
Detection was therefore luck: dropping *two* tokens keeps the count even and sails
through; dropping *one* makes it odd and is caught. The source's own E-396 comment
states the premise that is false — *"A non-numeric token such as `abc` was already
rejected"* — it was not, except by accident.

### The N-dimensional form was strictly worse, and was not in the report

Corrupting **one token** in a real 2-D grid file
(`examples/mdtable_examples/mos_iv.tbl`) leaves 50 numbers — even, so parity
accepted it — `read_table_grid_nd` then returns `None` and `lower_table_model` does
`return F_ZERO`. **The whole table contributes exactly zero.**

```
clean            i(vd) = -3.20000000000e-04
one token wrong  i(vd) =  0.00000000000e+00     compile clean
```

Adding a surplus token instead restores the count and silently *shifts* the grid,
because the reader consumes the stream positionally and ignores leftovers.

## Why the fix needed the dimensionality of the *call*

The two forms have genuinely different grammars, and **they cannot be told apart by
looking at the file**: `2 3 / 4 5 / 6 7` is a perfectly good 1-D table whose leading
numbers also read as a 2-dimensional header. The old code guessed
(`let d = nums[0];`), which false-positives on real 1-D data.

`ndim` is now carried in the diagnostic, computed at the validator's push site
exactly as `lower_table_model` computes it — the number of input arguments before
the data argument. Then:

* **`ndim == 1`**, and every `noise_table` file (always 1-D): each non-comment line
  must yield **exactly two finite numbers**. That is the reader's own grammar —
  `read_noise_table_file` reads `it.next(), it.next()` and discards the rest of the
  line — and it catches both faces of the defect: a corrupt row, and a surplus
  column the reader was silently dropping.
* **`ndim >= 2`**: every token must be a finite number, and the self-describing
  header must account for the count **exactly**. The parity fallback is gone for
  this case, which is what closes the `F_ZERO` hole.

**A per-line rule for everything would have been wrong**, and this is the part worth
recording. The N-D form is free-form whitespace across lines — `grid4.tbl` puts its
entire 36-value tensor on one line. A line rule applied to it would have rejected
`mos_iv.tbl`, `grid4.tbl` and `grid5.tbl`, all of which back live example suites.
That was the first plan, and an adversarial review of the scope killed it before any
code was written.

## A real literal that overflows to infinity

`r = 1e309;` compiled clean and the model returned **INF**. `f64::from_str` does not
fail on an overflowing exponent — it returns an infinity — and
`StdRealNumber::value` is `src.parse().unwrap()`, so the `.unwrap()` never fires.

This compiler had **already decided twice** that this is a mistake worth reporting:
E-396 refuses `1e400` inside a data file (its comment names this exact `from_str`
behaviour) and E-422 refuses `abstol = 1e400`. A bare literal in an expression is
the same mistake in the same compiler.

**Only the literal.** `1e308*10.0` is also an infinity, but that is *arithmetic*
overflow — a runtime property of the expression, not a mis-written constant — and
E-396 drew exactly that line. Underflow is left alone too: `1e-320` is a legitimate
subnormal and `1e-400` is 0.0, both defined by IEEE 754. `inf` as a range bound is
untouched.

## A based literal with a zero size

IEEE 1364-2005 §3.5.1: the size "shall be a **non-zero** unsigned decimal number".
`parse_based_int_masked` ends in `.clamp(1, 32)`, so a zero size silently became
**one bit** and the value bore no relation to the digits: `0'd5` evaluated to **1**
(5 masked to a single bit), `0'h1` to 1.

The **upper** half of that clamp is deliberately left alone. Enhancement-46
documents "clamped 1..=32 … wrap to the 32-bit `integer` type" as the intended
semantics, and truncating a wider literal is the LRM assignment rule — `4'hFF` is 15
and `32'hFFFFFFFF` is −1, both correct.

Checked in `validate_literal` rather than in `parse_based_int_masked`: that returns
`Option`, and `IntNumber::value`'s own documentation says a `None` makes callers
fall back to reading the text as a **real** — which would have swapped one silent
wrong answer for another.

## Verification

* **`examples/tabledata_examples` — 60/60**, and the table half is measured as
  *numbers*: the clean table is compiled and queried at 50, and each corruption is
  asserted rejected. The probe deliberately uses a table whose middle row matters —
  an earlier probe at `(0,0)(1,10)(2,20)`, x=1.5 returned 15 for both the full and
  the shrunken table and proved nothing.
* **Every shipped data file is pinned by name**: `diode_iv.tbl`, `elab_noise.tbl`,
  `noise_table.txt`, and the 2-D, 4-D and 5-D grids `mos_iv.tbl`, `grid4.tbl`,
  `grid5.tbl`. So is the 1-D file that *looks* N-dimensional.
* **164 real models — the 124-model VA_TEST industry corpus and the 40-model
  `integration_tests` corpus — compiled with the previous shipped binary and this
  one: ZERO differences.**
* `cargo test --features llvm18` **210/210**, no snapshot moved.
* **Full regression 342/342**, both solvers.

## Found by

Rounds 31 and 32 of the openvaf-r hunt. Three notes on method.

**The measurement nearly failed twice.** The first table probe returned 15 for both
the intact and the corrupted file, because interpolating `(0,0)→(2,20)` at 1.5 also
gives 15 — a probe that cannot distinguish the defective case proves nothing. And a
latched-event oracle in the same round read "never fired" for *every* event
including the control, because the harness reset the latch variable at the top of
the analog block.

**Round 32 withdrew four claims on evidence**, one of which is worth repeating: a
netlist override of an E-92-frozen parameter is *not* silently ignored — ngspice
warns, it just prints the warning after the `echo` output where a first-line filter
misses it.

**The N-D `F_ZERO` case and the per-line trap both came from an adversarial review
of the fix scope**, run before any code was written. The review's decisive evidence
was a census of every real data file in the repo: five of nine have per-line token
counts that a line rule would reject.
