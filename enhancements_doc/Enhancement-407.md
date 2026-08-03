# Enhancement-407 — the loop the standard writes and the compiler refused

Three examples taken **verbatim from the Verilog-AMS LRM** — the page-91 ADC, the
page-117 DAC and the page-134 genvar expression — did not compile. All three fail
the same way, and it is the way the standard itself writes the construct:

```verilog
genvar i;
analog begin
   for (i = 0; i < bits; i = i + 1)
      V(out[i]) <+ transition(result[i], dly, ttime);
end
```

## Why the loop has to be a genvar

A vectored net's bit-select must be a **constant**: each bit is its own
simulator unknown. Written with an ordinary counter the compiler refuses it —

```
error: bus bit-select index must be a constant
```

— so a run-time loop cannot express "contribute to every bit" at all. Declaring
the index a `genvar` is how the LRM says *unroll this at elaboration*, turning
`out[i]` into `out[0]`, `out[1]`, … Until now openvaf rejected that too, and the
three LRM examples sat in `lrm_examples/limitations/` under the note
*"analog-block genvar unrolling is unsupported"*.

## The standard supplies its own oracle

Page 117 ships **both** forms in one file: `dac`, written with the genvar loop,
and `dac8`, hand-unrolled. The unrolled form is not an interpretation — it is the
specification, written out by the standard. Compiled together and driven
identically, the two now agree exactly:

| module | `v(out)` |
| --- | --- |
| `dac` (genvar loop, `width = 8`) | 1.953125e−02 |
| `dac8` (LRM's hand-unrolled) | 1.953125e−02 |

which is 1/64 + 1/256 for the two bits set — checked by hand, not just for
equality. The page-91 ADC was verified the same way against a hand-unrolled copy:
driven at `in = 0.75`, both give `o7..o0 = 1,0,1,1,1,1,1,1`, bit for bit.

## What was needed

The elaborator already had every piece, and in the right order.
`fold_parameter_widths` runs **before** `elaborate_generates`, and Enhancement-92
rewrites any `parameter` that shapes a declaration width into a `localparam` —
so by unroll time `bits` in `out[0:bits-1]` is already a compile-time constant.
`substitute_index` already replaces an identifier with a literal *and* folds the
resulting bit-select brackets, which is exactly the per-iteration rewrite.

What was missing was the loop itself: find a `for` whose index is a declared
genvar, fold its init/condition/step, and emit one substituted copy of the body
per iteration. Two details were not free:

* **The existing evaluator has no relational operators.** Every previous caller
  folds a *width* or an *index* — never a predicate. A loop condition is exactly a
  predicate, so `eval_const_cond` splits on the single top-level relational
  operator and folds each side with the existing arithmetic evaluator. It must
  accept a two-character operator arriving either as one token or as two adjacent
  ones; handling only the split form silently missed every `<=` and `>=`, which is
  most real loop conditions — and all three LRM examples.
* **The genvar diagnostic had to move.** Enhancement-406 rejected any genvar
  inside an analog block, which now runs *before* the unroller would see it. That
  check now runs on the **unrolled** text: a genvar the unroller consumed leaves no
  trace, and one that survives is a genuine misuse.

## Deliberately narrow

Only a `for` whose index is a declared genvar and whose init, condition and step
all fold to integers. Everything else is untouched — an ordinary `integer` loop
stays a run-time loop, and a module-level `generate for` still elaborates through
its own path. Since every affected shape is one the compiler **rejected outright**
before, nothing that previously worked can change.

Each remaining failure keeps its own message:

| shape | message |
| --- | --- |
| a genvar read as a value | *"cannot be used inside an analog block except as the index of a `for` loop…"* |
| bound is a settable `parameter` | *"the loop condition is not a compile-time constant integer"* |
| runaway loop | *"expands to more than 4096 statement copies"* |

That last cap is E-148's reasoning applied here: each iteration is a full copy of
the body, so an unbounded bound would exhaust the elaborator before the compiler
ever saw the result.

## Verification

* **The three LRM examples move from `limitations/` to `va/`** — `lrm_examples`
  goes from 44 accepted and 15 limitations to **47 and 12**, and its suite passes
  7/7 on both solvers. That is the acceptance test: three files taken verbatim
  from the standard, previously uncompilable.
* **Numerically checked, not just compiled**: the page-117 DAC against the LRM's
  own `dac8`, and the page-91 ADC against a hand-unrolled copy — identical in both
  cases.
* **Nothing else moved.** Sweeping every `.va` file this repository ships, the
  count that compiles rises by exactly the three LRM examples (plus the two files
  this release adds). The three files still failing with a genvar-related message
  are pre-existing `generate if` limitations, untouched.
* **Full regression 324/324**, **`cargo test --workspace` 210/0**, **corpus
  differential 107 compiled by both, 0 return-code and 0 byte differences** — no
  corpus model uses the construct, so nothing that already worked was disturbed.

## Found by

Following up Enhancement-406, which noted that the LRM's own pages 91, 117 and 134
use this construct and that supporting it was *"a feature worth having"*. The
feasibility check came first: hand-unrolling the page-91 ADC showed it compiled in
0.12 s and simulated correctly, proving the target form was already fully
supported and that only the unrolling was missing.
