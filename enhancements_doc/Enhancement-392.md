# Enhancement-392 — module instantiation is validated, and eight other openvaf-r defects

Seven defects from a one-hour bug hunt against the [E-391](Enhancement-391.md)
compiler, plus two more the corpus differential turned up while verifying the
fixes. The headline is that **module instantiation was not checked at all**.

## 1. Instantiation was unvalidated

A child module instantiated inside a parent had its port connection list zipped
**positionally** against the target's declared ports, and its named connections
bound without ever asking whether the named port exists. Nothing was checked and
nothing was reported:

- the **wrong port count** — 0, 1, 2, 4 or 6 actuals on a three-port child. A
  surplus actual was dropped; a missing one left the port unconnected, so the
  device contributed nothing;
- a **port name the target does not have** — `kid c(.a(p), .b(n), .zz(p));`;
- a **parameter the target does not have** — `kid #(.zz(4e-3)) c(p,n);`, where
  the intended override silently did nothing and the default was used instead.

All three compiled clean, with zero diagnostics, and produced a device wired or
parameterised differently from what was written.

Two sharp contrasts, both already inside this project: ngspice rejects the same
mistake on a `.model` card (*"unrecognized parameter (zz) - ignored"*), and
`defparam` rejects it too (*"defparam target(s) did not resolve"*). Only the
instance port list and the `#(.param())` override were unchecked.

Verilog-A creates **implicit nets**, so a mistyped *net* name can never be caught
here — it simply becomes a new net. That is precisely why the things that *can*
be checked, the arity and the port/parameter names, matter more rather than less.

Instantiation is also where this had been hiding in plain sight: a duplicate
instance name was "caught" only when the child had a parameter, and then by an
accidental symbol collision on the *mangled parameter name* — not by any
instance-name check.

## 2. `generate` did not rename block labels or function names

Elaboration suffixes everything declared in a generate block (`_0`, `_1`, …) so
iterations do not collide. `collect_declared_names` covered nets, variables,
parameters, instances, branches and aliasparams — but an `analog function` fell
into its catch-all arm, and a named analog-block label is not a module item at
all. Two iterations therefore redeclared the same name and elaboration failed
with `'ab' was already declared in this scope`. Newly reachable because E-390
made `analog` legal inside `generate`.

## 3. The renaming rewrote the name in a named connection

Found by the corpus differential, once (1) started reporting. Substitution is
lexical over the token stream, so a generate block holding

```verilog
resistor #(.r(1e3)) r(node[i], node[i+1]);
```

— an instance whose *name* collides with the child's *parameter* — had its
override rewritten to `.r_0(1e3)`, which named no parameter of `resistor` and was
silently dropped back to the default. The name after the dot belongs to the
instantiated module's namespace and must never be renamed; it is now pinned to
itself with an identity hole.

`examples/generate_examples/resistor_ladder_generate.va` was affected. It looked
correct only because its override happened to equal the default — the same
ladder with `.r(2000)` against a default of `1000` built at **half** the intended
resistance.

## 4. A `$mfactor` override was zipped onto the first parameter

Also from the differential. A system-parameter override is written with a dot but
carries no `NAME` child, because `$mfactor` is not an ordinary identifier. Keying
*"is this named?"* off `name()` put it in the **positional** branch, so

```verilog
core #(.$mfactor(7)) C1(p,n);
```

set the target's first declared parameter to 7. The LRM's own page-263 example
does exactly this, and got `r = 7` instead of its default of `1.0` — a sevenfold
wrong answer, in a file the suite had been compiling as *verbatim* since it was
extracted. The discriminator is the **dot**, not the name.

## 5. The runtime `$table_model` sort gave up silently above 64 knots

E-390 taught the runtime array form to sort and de-duplicate so it would agree
with the compile-time forms, using an unrolled compare-and-swap network capped at
64 points. The compile-time path sorts at any size, so above the cap the two
diverged again with **no diagnostic**: with 65 reversed knots, the cubic form
gave 160.0 against 6.2566, 25× off. `compact_distinct_runtime` had no cap at all,
so the de-duplication still ran on unsorted data.

The network is now a **Batcher odd-even merge sort** — O(n log² n) comparators
instead of O(n²), so it reaches 256 points for less emitted code than the old one
used at 64. Both halves share the cap, and exceeding it is a compile error rather
than a silent divergence.

### The stability trap

The first Batcher implementation broke a case E-391 had fixed, and the shape of
the failure is worth recording. The de-duplication keeps the **first** of any
repeated abscissa **in original order** — which is what `pts.dedup_by` does on the
compile-time side, because Rust's `sort_by` is stable. The old odd-even
transposition network was stable for free, since it only ever exchanged
neighbours. Batcher's compares elements that are far apart, and two equal
abscissae can come out swapped.

That is invisible until the repeated points have *different* ordinates, and then
the two paths keep different points. Stability is restored by carrying the
original index alongside each point and breaking ties on it, which makes the sort
order total. The indices are compile-time constants, so the cost is one tracked
value per point.

**A faster algorithm is not a drop-in replacement for a slower one when a
downstream consumer depends on a property the slow one had by accident.**

## 6. A `localparam` was rejected as a generate bound

*"module parameters bind at simulation time under OSDI and cannot shape the
generated structure"* is right for `parameter` and wrong for `localparam`, which
is fixed at elaboration — and which the compiler already accepts as a constant in
every other position: array bounds, bus widths, parameter defaults, `repeat`
counts.

This composes with [E-92](Enhancement-92.md), which freezes any parameter that
shapes a declaration width *into* a localparam. Such a parameter is already a
compile-time constant, so it may now size a generate as well. A parameter that
shapes nothing is still rejected, as is a localparam derived from one.

Three files in `examples/lrm_examples/limitations/` moved on to a different
blocker as a result, and are re-pinned to it: `lrm_p168_1` to its decrementing
loop header, `lrm_p171_2` to recursive instantiation, and both `lrm_p169_*` to
`n[N]` as a bit-select index — a localparam sizes a bus but still cannot index
one, which is the same class of gap and is **not** closed here.

## 7. `INT_MIN` deviated from two's-complement wrapping when constant-folded

`-2147483648` is the smallest `integer`, but it parses as unary minus applied to
`2147483648`, whose magnitude does not fit `i32`. The operand became a **real**
literal and the whole expression acquired real semantics:

| expression | folded | integer semantics |
| --- | --- | --- |
| `(-2147483648)/3` | -715827883 (rounded) | -715827882 (truncates toward zero) |
| `(-2147483648)-1` | -2147483648 (saturated) | 2147483647 (wraps) |
| `(-2147483648)*2` | -2147483648 (saturated) | 0 |

The same value arriving at runtime from a `.model` card stayed an integer and was
right in every case, so one expression had two meanings depending on whether it
was folded. Powers of two and `/7` came out right by coincidence, which is what
made it look like a strength-reduction bug rather than a type bug.

The fix folds the sign into the literal at the point the prefix expression is
lowered — `Literal::new` cannot see the enclosing minus, which is why an earlier
attempt in the syntax-level constant evaluator changed nothing.

`(-2147483648)/(-1)` must still be **rejected**: it is the one integer operation
that genuinely traps the CPU, and [E-334](Enhancement-334.md) diagnoses it.
Making the literal work correctly is what first brings it within reach of that
guard. `examples/vafcodegen_examples/constfold.va` carried the real-division
version of that line, with a comment asserting the promotion was intended; it has
moved to `vafintub_examples` alongside the `(-2147483647 - 1)` spelling.

## Verification

`examples/vafinstcheck_examples` — **41/41 fixed, 16/41 against the E-391
binary**. The 16 that pass unchanged are the accept half.

The accept half is the substance of the risk here: a validation pass that rejects
too much is worse than one that rejects nothing, because it breaks working
models. The LRM sanctions several ways of leaving a port unconnected — a blank
positional slot, omitting the port from a by-name list, an empty `.port()` — and
every one of them still compiles, as do reordered by-name lists, valid named and
positional overrides, and `$mfactor`.

Beyond the suite:

- **corpus byte-differential against the E-391 build, same `-o` path**: 92/92
  industry compact models (BSIM4/6/BULK/CMG/IMG/SOI, PSP, HiCUM, MEXTRAM, VBIC,
  EKV, ASM-HEMT, …) **byte-identical**, and 400 of the repo's own example models
  byte-identical with **zero** newly-rejected files. The only two differences are
  `lrm_p263_2` and `lrm_p263_3` — the `$mfactor` files, which the old binary
  compiled to the wrong parameter binding.
- workspace tests 209 passed / 0 failed
- full regression **316/316**
