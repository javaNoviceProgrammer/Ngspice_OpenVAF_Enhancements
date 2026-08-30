# Enhancement-509 — a domain the compiler refuses in source but not from the deck

Round 65 found the vein [Enhancement-506](Enhancement-506.md) opened, one layer
deeper — and this time the list is closed by construction rather than by sampling.

## What was wrong

Eight math builtins and `$vt` carry a compile-time domain guard that fires for a
literal **and** a `localparam`, with a message that names the builtin, the value
and the domain:

```
error: sqrt: the argument is -4, which is outside the domain of sqrt (values >= 0)
```

The identical value written on a **model card** is a `parameter`, deliberately not
folded ([Enhancement-426](Enhancement-426.md): the deck may replace it), so it
reached libm untouched:

| written in the model | from the deck |
|---|---|
| `sqrt(-4.0)` — refused, named | `sqrt(q)`, `q=-4` → **nan** |
| `ln(0.0)` — refused, named | `ln(q)`, `q=0` → **-inf** |
| `asin(2.0)` — refused, named | `asin(q)`, `q=2` → **nan** |
| `acos(-3)`, `acosh(0.5)`, `atanh(1)`, `log(-1)` | **nan** / **inf** |
| `pow(-4, 0.5)` and `-4 ** 0.5` | **nan** |

In an operating-point variable that is silent with exit code 0. In a residual it
surfaces as *"Timestep too small; cause unrecorded"* — naming neither the model
nor the call, which is exactly the complaint
[Enhancement-504](Enhancement-504.md)'s own comment records about a different
value reaching the same dead end.

### `$vt` is the one with teeth

A diode `Is*(limexp(V/$vt(tabs)) - 1)` with the absolute temperature on the model
card:

| `tabs` | i(v1) |
|---|---|
| 300 | −1.207e−04 A — conducting |
| **−300** | **−6.0e−07 A** — the 1 MΩ shunt alone |

A negative absolute temperature gives a negative thermal voltage, which inverts
every exponential built on it. The device stops being a diode, and nothing says
so. `$vt`'s literal form has been refused since the guard was written.

### And on the simulator side, an integer that does not fit

`(int) round(tmp)` is undefined behaviour once the rounded value leaves the
integer range; on this target it saturates. A model card saying `n=1e300` applied
**2147483647** — 291 orders of magnitude from what was written.

The saturation is what made it dangerous rather than merely surprising, because
it happens **before** the parameter's own range check. A parameter declared
`from [0:2147483647]` — the idiomatic way to say *any non-negative integer* —
accepted `1e300`, because the clamped value landed exactly on its upper bound and
passed. `sp=200` against `[0:100]` was refused correctly the whole time; only the
values that overflowed slipped through, and those are the absurd ones. This is
[Enhancement-507](Enhancement-507.md)'s shape: a value mangled before the check
that would have caught it.

## The half that must not be guarded

This is the part that decides whether the fix is correct.

`sqrt(V(p,n))` goes briefly negative during Newton iteration in working models.
Refusing every out-of-domain argument would abort them, trading a silent wrong
answer for a loud wrong refusal — the mistake [Enhancement-508](Enhancement-508.md)
made with `$discontinuity` and had to take back.

So the guard is emitted **only for a parameter-derived argument**: one built from
literals, `localparam`s and `parameter`s, and nothing else. Such a value is fixed
once the model card has been read, so the check cannot fire spuriously — it tests
the same number at every evaluation. `param_derived_in_body` is deliberately the
same shape as `const_real_in_body`, one step weaker: that folds what is known when
the model is **compiled** (never a `parameter`), this accepts anything constant
once the card is **read**.

Checks [10]–[13] of the suite hold that line: `sqrt(V*V)` and `ln(1+V*V)` run
untouched, and `sqrt(V)` with `V<0` is **not** refused.

## Two things the fix itself turned up

**A latent compiler crash.** The first version guarded literals too. That folded
the whole condition to constants — and `mir_opt`'s constant evaluator has no case
for `iand`/`ior`/`ixor` on two constant **booleans**, so it hit its own
`unreachable!` and OpenVAF crashed with exit code 101 on input as ordinary as
`pow(2.0, 3.0)`. Seven suites went red at once. Nothing had generated that shape
before, because nothing had built a condition out of constant booleans. The
connectives are added to the evaluator here; the guard also no longer creates the
shape, since a literal is already refused at compile time with a better message.
Both halves are worth having — that `unreachable!` was reachable.

**An interaction with Enhancement-506's own test.** `flknoise.va` built its NaN
exponent with `sqrt(p)`, `p = -1`, to check that `flicker_noise` survives a NaN
exponent. This enhancement refuses that `sqrt` at its source, so the NaN no longer
reaches the contribution. The *assertion* is still valid and still runs — a NaN
exponent must leave the spectrum finite and the source inert — so the vehicle was
changed to an unguarded route (`p/q`, both zero at run time) and the expected
value is untouched. Refusing a value earlier is an improvement; silently dropping
the test that covers what happens afterwards would not be.

## Withdrawn at fix time

Round 65 also reported `idtmod` with a deck-supplied modulus ≤ 0 degenerating to
plain `idt` — measured as a bit-identical match (1.199980361267e-08 for modulus 0,
modulus −1n and plain `idt`, against 9.998036126724e-10 for a valid modulus).

Reading the site, that is [Enhancement-504](Enhancement-504.md)'s deliberate
choice:

> Fall back to the UNWRAPPED integral, which is exactly what `idtmod` means with
> no modulus supplied, so the model keeps running and the value stays finite.

The identity is the decision working, not a defect. Withdrawn.

## Files

| file | change |
|---|---|
| `openvaf/hir_lower/src/expr.rs` | `param_derived_in_body`, `guard_arg_domain`, `guard_pow_base`; applied to `sqrt` `ln` `log`/`log10` `asin` `acos` `acosh` `atanh` `pow` `**` and `$vt` |
| `openvaf/mir_opt/src/const_eval.rs` | `iand`/`ior`/`ixor` on two constant booleans no longer reach `unreachable!` |
| `examples/deckdomain_examples/flknoise.va` | Enhancement-506's NaN exponent is built by a route this enhancement does not refuse; its assertion is unchanged |
| `ngspice-46/src/spicelib/parser/inpgval.c` | an integer conversion that does not fit sets a range-error flag instead of saturating |
| `ngspice-46/src/spicelib/parser/inpgmod.c` | the model-card path reports it and keeps the default |
| `ngspice-46/src/include/ngspice/inpdefs.h` | `INPlastRangeError` |
| `examples/domainrt_examples/` | new suite |

`pow` and `**` are guarded separately because they lower through different paths —
[Enhancement-489](Enhancement-489.md)'s lesson that a builtin with an operator
spelling needs both.

## Verification

`domainrt_examples` — **28 checks, both linear solvers**, of which **14 fail on
the shipped binaries** (measured: 14/28 pass before the fix, 28/28 after). Full
regression **423/423**.

The over-broad first attempt was caught by the suite, not by inspection: seven
suites failed at once (`powguard`, `valguard`, `lrmfuncs`, `deckdomain`,
`commaexpr`, `genvarloop`, `vafdegen`), which is what pointed at the constant
evaluator.

The compile-time half is unchanged: a literal and a `localparam` are still refused
where the compiler can see them, each one still named.
