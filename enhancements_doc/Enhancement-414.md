# Enhancement-414 — the `else` that changed which `if` it belonged to

An analog `genvar` for-loop is unrolled **textually**: the body is copied once per
iteration with the genvar replaced by a literal. Finding the body means finding
where one statement ends — and that recognised exactly two shapes, a
`begin`..`end` block and "everything through the next top-level `;`".

Every other statement was therefore cut at the first `;` inside it, and whatever
was left over stayed behind, spliced in *after* the generated block. Usually that
produced a parse error pointing at `endmodule`. Once, it produced a different
program:

```verilog
if (d > 0.5)
    for (i = 0; i < 2; i = i + 1)
        if (cc > 0.5) x = x + 1.0;
        else          x = x + 10.0;
```

The `else` fell outside the copied text and re-attached to the **enclosing**
`if (d > 0.5)`. `rc = 0`, no diagnostic:

| d | cc | unrolled | correct |
| --- | --- | --- | --- |
| 1 | 1 | 2.0 | 2.0 |
| 1 | 0 | **0.0** | 20.0 |
| 0 | 1 | **10.0** | 0.0 |
| 0 | 0 | **10.0** | 0.0 |

Three of four combinations wrong — and the one anyone would spot-check is the one
that agreed. The oracle is the identical source with an `integer` index, which is
not unrolled at all.

`statement_extent` now scans by statement shape, recursively, which is the only
way to know that an `else` belongs to the body rather than to the statement around
it. These all compile now, and none of them did before:

`case`/`casex`/`casez`, `if` whose branch is a block, `if`/`else`, `while`,
`repeat`, a nested `for`, `do`..`while`, `@(event)`, and a nested genvar loop —
each as an unbraced loop body.

Two more things the textual copy got wrong: a `begin : blk` block had its **label**
copied too, so N copies collided (`'blk' was already declared in this scope`) —
each copy is now suffixed with its iteration index, the way a generate block is
indexed; and the expansion shifted every following line, so a diagnostic ten lines
below a loop was reported a hundred-odd lines away.

## The second correctness fix, found while fixing a crash

Enhancement-92 freezes a parameter that shapes a declaration **width** into a
localparam: the OSDI descriptor has one fixed node/array count, so the value must
not change at simulation time. The pass that finds those widths scanned for
`[lo:hi]` groups mentioning a parameter — and a parameter's `from [lo:hi]` **value
constraint** is spelled with exactly the same brackets.

```verilog
parameter integer aa = 2;
parameter integer bb = 4 from [aa:8];   // aa is not a width
```

`aa` was marked structural and frozen, so `.model mm freeze(aa=5)` was accepted
and **did nothing at all** — no diagnostic, the model simply kept `aa = 2`. And
because the freeze then rewrote text the range fold had already claimed, two
overlapping rewrites indexed a string slice backwards and **panicked the
compiler** outright, which is what a range mentioning its own parameter
(`from [p:8]`) did every single time.

Constraint brackets are now left alone, and overlapping rewrites are dropped
instead of aborting.

## The rest

| what | before | now |
| --- | --- | --- |
| any `aliasparam` cycle (`pp = pp`, mutual, 3-cycle) | **crash dump, no diagnostic** — `resolve(db).unwrap()` on the resolver's cycle recovery | `aliasparam 'pp' never reaches a parameter: its target chain closes on itself` |
| `parameter real p = p;` / `localparam real ls = ls + 1;` | compiled; the initializer was folded **twice**, so `ls` was 2 and `l2 = l2*3+7` was 28 | `definition of 'ls' references itself` |
| `noise_table("mistyped.tbl")` | empty table ⇒ **no noise at all**; the spectrum came out identical to a model with no noise source | `cannot use 'mistyped.tbl' as noise_table data` |
| `white_noise(-1e-16)`, `flicker_noise(-1e-16, 1)` | the sign was discarded — same spectrum as the positive twin | `the noise power must not be negative` |
| `branch (a,a) br;` | every flow contributed to it was discarded, silently | `warning[L024]: branch 'br' names the same node 'a' twice` |
| `absdelay(x,d,m,4th)` | `expected at most 2 arguments` — while three are legal | `at most 3`; `idt` likewise says `at most 4`, not `at most 1` |
| `openvaf-r --version` | `OpenVAF-Reloaded unknown` | falls back to the crate version when `git describe` finds no tag |

A diagnostic landing in one of the synthesised elaboration buffers
(`…__generated.va`, `…__paramwidth.va`, …) now says so, instead of presenting a
line number in a file that does not exist as if it were a location in the user's
source.

## Two findings withdrawn, on evidence

**A parameter's DEFAULT is still not range-checked, deliberately.** This looked
like a defect — the identical value 5.0 against `from [0:2]` runs silently as a
default and is rejected from a netlist. It is Enhancement-56's decision: CMC
models declare a default *outside* the range as the "feature disabled" state
(`diode_cmc`'s `CORECOVERY = 0.0 from (0.0:1.0]`, FBH-HBT's `Fb = 0.0 from
(0.0:inf)`), and enforcing it rejected stock models at setup. A scan of 1551
ranged parameters across 700 corpus models finds exactly three such defaults, one
of them a shipped CMC model. Ranges bind *supplied* values, which is what
`paramrange_examples` covers.

**`transition()`/`slew()` do not abort a transient.** Reported as an abort on a
fast input edge; the report was wrong, because the hunt harness set
`reltol = 1e-11` globally. At default tolerances and at `reltol = 1e-6` both
operators complete and give the right answer. The collapse needs `reltol ≤ 1e-9`
*and* an input edge as fast as the operator's internal time constant: the
rate-limited tracking equation uses `TRACK_GAIN = 1e9`, i.e. a deliberate 1 ns
lag, and asking for 1e-9 relative accuracy of a 1 ns filter driven by a 1 ns step
is a stiffness demand, not a defect. Changing that constant would move
`transition`/`slew` accuracy everywhere for a case that only appears under
tolerances no model asks for.

**An out-of-range integer literal is left as it is**, for the same reason of scope:
`5000000000` saturates to 2147483647 on the store to an `integer`, while
`2000000000 + 2000000000` wraps to -294967296. Both are silent and they disagree
with each other, but wrap-on-arithmetic is standard Verilog integer semantics, and
an out-of-range literal is deliberately kept as a *real* constant — that is what
makes a large `laplace_nd` coefficient work. A warning narrow enough to catch the
typo without firing on those coefficients is not expressible from the literal
alone.

## Verification

* **`examples/elabguard_examples` 43/43.** On the pre-414 binary the suite cannot
  reach its second check: `elab_unroll.va` fails to compile with **129 errors**.
* The dangling-`else` module is checked against its own `integer`-loop twin at all
  four parameter combinations, so the test cannot pass by agreeing with itself.
* Each unrolled shape is checked by **value**, not by "it compiled": `s_case` 111,
  `s_ifelse` 12, `s_named` 14 (1+4+9), and so on.
* `.model mm freeze(aa=5)` now moves the current from -2.000 mA to -5.000 mA.
* **Compiler suite 210/0** (`cargo test --features llvm18`).
* **Full regression 331/331.**

## Found by

A one-hour hunt over openvaf-r. The tell for the headline was that a genvar loop
and the same loop with an `integer` index disagreed — an index type cannot change
what a program computes. The parameter-freeze defect was not in the hunt report at
all; it surfaced while root-causing the crash that a self-referential range
produced, and is the more serious of the two.
