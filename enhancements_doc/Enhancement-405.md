# Enhancement-405 — the z-domain filters had every pole and zero upside down

A one-hour hunt over openvaf-r's less-travelled corners. Six defects fixed, one
finding withdrawn on evidence, one root-caused and deliberately left alone.

## The headline: `zi_np`/`zi_zp`/`zi_zd` reciprocated every root

The four z-domain filter forms exist to express the same filter four ways. They
did not agree. One pole at z = 0.5, written four ways, steady-state gain:

| form | denominator written as | DC gain |
| --- | --- | --- |
| `zi_nd` | coefficients `'{1, -0.5}` | **2.0** |
| `zi_zd` | coefficients `'{1, -0.5}` | **2.0** |
| `zi_np` | root `'{0.5}` | **−1.0** |
| `zi_zp` | root `'{0.5}` | **−1.0** |

−1.0 is exactly `1/(1 − 1/0.5)`: the root was **dividing** `z⁻¹` instead of
multiplying it, so a pole written 0.5 landed at z = 2. Passing `'{2.0}`
reproduced the pole at 0.5, and the same reciprocation applied to zeros
(`zi_zd` with zero 0.5 gave −1.0; with 2.0 it gave 0.5, matching `zi_nd`'s
`'{1,-0.5}` numerator). Complex conjugate pairs matched the reciprocal
prediction exactly — 1.0 and 2.5 — so this was systematic, not an edge case.

`lower_zi` called `laplace_roots_to_poly`, which builds `Π(1 − s/r)`. That is
right for the s-domain and wrong for `z⁻¹`, where the LRM's factor is
`(1 − ρ·z⁻¹)`. A new `zi_roots_to_poly` builds that product, with no zero-root
special case: the LRM's `(1 − s/r)` exception exists because that form divides
by the root, and `(1 − ρw)` does not — at `ρ = 0` it is simply 1.

**The comment in that very function said so.** Enhancement-395, which fixed the
Laplace normalisation, ended with *"The `zi_*` family is separate and already
correct: the z-domain form is `1 - z^-1*rho`, where the root MULTIPLIES rather
than divides."* It was not separate — `lower_zi` called straight into the
function that comment lives in. The claim is now corrected rather than repeated,
and the function's own header, which still described the pre-E-395 `Π(s − r)`
behaviour, is corrected too. `laplace_*` was and remains right: DC gain 1.0 for
a lone real pole, for a conjugate pair, and for the zero-at-origin exception.

## A compiler hang that reached 38 GB

```verilog
y = zi_nd(V(a,c), '{1.0}, '{}, 1e-6, 0.0);   // empty denominator
```

never terminated. RSS oscillated between **8 GB and 38 GB** over the minute it
was allowed to run; the same model with a non-empty denominator compiles in
0.18 s.

```rust
let n = (den.len() - 1).max(num.len().saturating_sub(1));
```

`num` was guarded, `den` was not. `den.len() == 0` underflows to `usize::MAX`
and the bilinear expansion below then loops `0..=usize::MAX`. Predicted from the
source and then confirmed by measurement, `zi_np`/`zi_zp` are **safe** — their
roots go through the root-to-polynomial expansion, which always returns at least
`[1.0]`. Both subtractions now saturate, in `lower_zi` and in
`laplace_state_space` beside it, and `hir_ty` rejects an empty coefficient
denominator with a real diagnostic instead.

## An improper numerator was silently truncated

| written | measured \|H\| at 1 MHz | analytic |
| --- | --- | --- |
| `laplace_nd(x, '{1, τ}, '{1})` | 1.0 | 6.362 |
| `laplace_nd(x, '{1, τ, τ²}, '{1, τ})` | 0.157 — *identical to `1/(1+sτ)`* | 6.128 |
| `laplace_nd(x, '{0, τ}, '{1})` — a differentiator | **0.0** | 6.283 |

The controllable-canonical realization carries at most a direct feedthrough
term, so anything above the denominator's order was dropped without a word. An
improper transfer function has unbounded gain as frequency grows and has no
state-space realization, so it is now rejected rather than approximated — `ddt`
is the spelling for a genuine derivative.

**Only the s-domain.** In `z⁻¹` a numerator of higher order than the denominator
is an ordinary FIR filter — more delay taps, causal and realizable — and
`lower_zi` already pads both polynomials to `max(num, den)`. The first draft
rejected those too and would have broken working filters; the narrowing came
from measuring `zi_nd('{1, 0.5, 0.25}, '{1})`, which is correct at DC gain 1.75.

## Parameter arrays could not be indexed at run time

```verilog
parameter real ap[0:2] = '{1.5, 2.5, 3.5};
integer k;
for (k = 0; k < 3; k = k + 1) y = y + ap[k];   // rejected
```

*"error: bus bit-select index must be a constant"* — for something that is
neither a bus nor a bit-select, while the identical loop over a `real arr[0:2]`
variable had worked since Enhancement-14. A parameter array's elements are
ordinary MIR values, so the same runtime select chain applies; they now take a
dynamic index in 1-D and 2-D, as `parameter` and as `localparam`, real and
integer. Writes to a parameter array stay rejected — the read path is kept in a
separate type from the dynamic-index *write* path precisely so that `p[i] = v`
cannot start looking expressible — and a vectored **net** still needs constant
indices, because its bits map to distinct simulator unknowns.

## Array bounds took literals, not constant expressions

Accepted: `[0:2]`, `[-1:1]`, `[0:P]` for a named parameter, and a macro
expanding to a whole range. Rejected: `[0:3-1]`, `` [0:`N-1] `` — the ordinary
way to size an array from a `define` — and even `[(0):(2)]`, a parenthesised
literal. The LRM asks for a constant *expression* here.

A small syntactic folder now handles parentheses, unary sign and integer
`+ - * / % << >>`. It is deliberately **not** `const_int_expr`: it runs in the
item tree, before name resolution, so it cannot and must not resolve names — a
name still folds to nothing and takes the existing path that already handled it.
Every step is checked, so an overflowing bound is reported as non-constant rather
than wrapping, and division by zero folds to nothing rather than panicking.

## A declared `genvar` was reported as undeclared

`genvar g;` followed by `for (g = 0; ...)` inside an `analog` block produced
*"'g' was not found in the current scope"* — byte-identical to the message for a
name that was never declared, in front of a user looking straight at the
declaration. Generate elaboration erases genvar declarations textually, so by
the time name resolution ran the declaration genuinely was not there. The
elaborator now says what it actually is, and points at the two spellings that
work.

**Worth knowing:** the LRM's own page-91 ADC example does exactly this, as do
its pages 117 and 134. Those three are pinned in `lrm_examples/` as known
limitations — *"analog-block genvar unrolling is unsupported"* — and are re-pinned
here to the new message. Supporting the construct is a feature worth having, and
is not attempted here.

## Withdrawn: `ddx` of an unnamed branch flow

The hunt reported that `ddx(f, I(br))` compiles for a declared branch while the
identical `ddx(f, I(a,c))` and `ddx(f, I(<a>))` do not. Both were made valid —
and `openvaf/test_data/ui/ddx.va` failed, because it lists both under **"these
must be rejected"**. The restriction is deliberate and asserted, so the change
was reverted rather than overriding a design decision.

What *was* wrong is the message. Its help offered

```
branch current access: I(branch), I(a,b)
```

advertising `I(a,b)` as an accepted form inside the very error that rejects it,
which is what made a deliberate restriction read as a bug. Both copies now name
the declared-branch form and say `I(a,b)` is not it.

## Root-caused and left alone: compile time in the parameter count

A module with N parameters compiles in time growing ~×2.5–2.9 per doubling of N
(4000 parameters, 7.0 s; 20000, 208 s). The hunt attributed this to parameter
*arrays*; that was wrong — plain scalar parameters scale identically, so it is
the parameter count. It is not LLVM's optimiser either: `-O0` shows the same
shape. Profiling at `-O0` puts **12299 of ~14358 samples** in
`mir_opt::simplify_cfg::iteratively_simplify_cfg`, which rescans *every* block on
every round until a round changes nothing — O(blocks) × O(rounds), both growing
with N.

The fix is a worklist, but that rewrites a fixed-point optimiser where
simplification order can change the result, and the only real guard is
byte-identical output. That is not a clean, local change, so it is recorded here
rather than attempted. No real model is affected: bsim4, with about a thousand
parameters, compiles in 1.5 s.

## Also found, not fixed

Probing `I(br)` on a **named branch that also carries a contribution** inserts an
ammeter that shorts the branch, and the DC solve fails. Identical on the shipped
binary, so it predates this release; it is recorded for its own investigation.

## Verification

* **Full regression 322/322.**
* **`cargo test --workspace --features llvm18` 210/0**, including the `ddx.va`
  UI snapshot, whose only diff is the corrected help text.
* **Corpus differential** over `VA_TEST` at the same `-o` path: 107 compiled by
  both, **0 return-code differences, 0 byte differences** — no corpus model uses
  a z-domain filter, so the fixes above move nothing that was already working.
* Targeted: the four `zi_*` forms agree to 0.000e+00 spread; FIR filters exact at
  1.75 / 0.5 / −1.0 / 0.5; `laplace` DC gains exact for real, conjugate-pair and
  zero-at-origin roots; parameter-array indexing correct in 1-D and 2-D;
  `vaflaplace_examples` 15/15; `lrm_examples` 7/7 on both solvers.

## The example

`examples/filterforms_examples/` writes all three filters in all eight forms —
24 modules — and checks each in **dc, ac and tran** against closed form, plus the
convention-free cross-form agreement. 85 checks, about two seconds.

It is **not** part of the routine regression sweep (`_setup.REGRESSION_EXCLUDE`),
and deliberately so rather than for speed; the reason is recorded next to the
entry. Run it directly, or with `run_regression.py --all`.

Against the shipped binary from before this release it gives **58 pass / 27
fail**, exit 1, and the failures are exactly the root-taking z-forms — with zero
`laplace_*` failures, the same conclusion the corpus differential reached from
the other direction.

**The regression earned its keep twice.** It caught a first draft rejecting an
empty numerator, which is a documented `H = 0` case the example suite asserts —
and then caught the order helper computing `0 - 1` on a `usize`, which is the
exact underflow this release fixes in `lower_zi`.
