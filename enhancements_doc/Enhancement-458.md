# Enhancement-458 — every LRM function, in every argument form

The Verilog-AMS LRM defines each built-in function with a specific set of
argument forms, and for the mathematical functions it defines **two spellings of
every one of them**. This change is the result of checking openvaf-r against all
of it: 117 builtins, every documented form, compiled *and run* against a numeric
or textual oracle — 223 checks, of which 206 passed and 17 did not.

Seven defects are fixed here. One reported defect turned out to be the audit's
own misreading and is pinned so it is not "fixed" later by mistake, and one form
remains unimplemented and is pinned as refused.

The oracles are LRM 2023: Tables 4-14/4-15 and A.8.2
`analog_built_in_function_name`, Syntax 4-3 (analog operators), 4-4 (noise),
4.6.3 (`ac_stim`), 4.7.1 (`analysis`), 9-7 (severity), 9-10 (environment), 9-12
(`$limit`), 9-16 (`$table_model`), 9.13 (RNG), 9.5/9.9–9.12 (file I/O).

## 1. `ln1p` and `expm1` did not exist

A.8.2 lists them beside `ln` and `exp`:

```
analog_built_in_function_name ::=
      ln | ln1p | log | exp | expm1 | sqrt | min | max | abs | pow | floor | ceil
```

Neither spelling resolved — `'ln1p' was not found in the current scope`.

They are implemented as their own MIR opcodes lowered to libm's `log1p`/`expm1`,
**not** as `ln(1+x)` and `exp(x)-1`. That is the whole reason the LRM lists them
separately, and it is measurable:

| x = 1e-15 | value | exact |
|---|---|---|
| `ln1p(1e-15)` | 9.999999999999995e-16 | 9.9999999999999949e-16 |
| `ln(1.0 + 1e-15)` | 1.110223024625156e-15 | — |

The naive spelling is wrong in the **first significant digit**. The same holds
for `expm1(1e-15)` (1.000000000000001e-15) against `exp(1e-15)-1.0`
(1.110223024625157e-15).

A new opcode has to be taught to five places, and the compiler tells you about
only four of them. `mir_opt::simplify::simplify_unary_op` ends in
`_ => unreachable!("")`, so the fifth — a missing arm there — is not a compile
error but a **panic the first time a model uses the function**. `ln1p`/`expm1`
are exact mutual inverses, but they must not be folded away for the same reason
`ln(exp x)` is not: `expm1` overflows to infinity for large x, so
`ln1p(expm1(x))` is infinity, not x.

Derivatives are the other silent half: `d/dx ln1p(x) = 1/(1+x)` joins the
divide-group with `1+x` cached as the denominator, and `d/dx expm1(x) = exp(x)`
joins the multiply-group. Both were verified through the OSDI Jacobian, not just
by value.

### The trap: adding a keyword broke eight shipping models

`ln1p`/`expm1` were first added to the `keywords!` list in `syntax::name` — which
is exactly what `is_reserved` answers with. The corpus differential immediately
reported **eight models that had compiled for years and now did not**:

```
error: reserved keyword 'expm1' was used as an identifier
  --> HSMSOI_TOP_module.inc:459:22
459 | analog function real expm1 ;
```

HiSIM-SOI and HiSIM-SOTB each declare their **own** `analog function real
expm1`. Reserving the name is defensible on paper and unacceptable in practice.
The two names are therefore declared as ordinary builtin names outside the
keyword list: they resolve to the builtins in the base scope, and a module that
defines a function of the same name shadows them — pinned in the suite, where a
user-defined `expm1(0.5)` returning `50.0` proves the shadowing works while the
builtin still returns 0.4054651081081644 elsewhere.

## 2. `$abs`, `$min` and `$max` were the only `$`-spellings missing

Table 4-14 gives every math function a `$name` form and a bare `name` form, and
the LRM *encourages* the first: *"Users are encouraged to adopt the IEEE Std 1364
Verilog system function style"*. Twenty-three of the twenty-six worked. These
three were never registered in the builtin scope, so `$abs(-2.5)` failed to
resolve while `$ln`, `$sqrt`, `$pow`, `$atan2` and the rest were fine. The names
already existed in `sysfun`; only the three `dst.insert` lines were missing.

## 3. An array *parameter* — the form the LRM lists first — was rejected

Syntax 4-3:

```
analog_filter_function_arg ::=
      parameter_identifier
    | parameter_identifier [ msb_constant_expression : lsb_constant_expression ]
    | constant_assignment_pattern_or_null
```

Only the third form worked. A parameter identifier gave `'cf' requires a
bit-select [i]` from every Laplace and Z-transform filter. Array *variables*
worked for `laplace_*` but not for `zi_*` — the supported and unsupported cases
were inverted relative to the specification.

Parameter arrays now resolve to their element `ParamId`s (the same way
`infere_dynamic_param_bit_select` already did for `p[i]`) and lower to parameter
reads, so the values are genuinely read at run time. Proved rather than asserted:
for `H(s) = 1/(1 + 1e-6·s)`, a literal, a parameter array and a variable array
all give **4.00674**, and overriding `de[1]` from the `.model` card to `1e-5`
moves it to **1.06531** — the parameter is not a folded default.

`zi_*` needed its own path: it has no dedicated inference arm, and its trailing
`T`/`t0`/`tol` arguments are not the tolerance `infere_laplace` expects at that
position, so its array arguments are pre-resolved and the ordinary signature
match then succeeds.

One further consequence: `infere_expr`'s early return for a pre-resolved whole
array checked the *variable* map only, so a resolved parameter array was
re-inferred and rejected anyway. That is why the fix only took effect once both
maps were consulted.

## 4. A trailing null filter argument

`laplace_zd(x, , d)` worked; `laplace_np(x, n, )` and `laplace_zp(x, , )` were
syntax errors. Syntax 4-3 writes the filters as
`laplace_filter_name ( expr , [ arg ] , [ arg ] [ , constant ] )`, so the second
argument may be null with nothing after it.

Enhancement-423 deliberately raised an error on that position for `max(1, 2,)`.
The parser sees token *kinds*, never text, so it cannot tell the two apart; the
trailing slot is now the same empty `ARRAY_EXPR` node the interior slot already
produced, and legality is decided in inference, where the builtin is known. The
typo is still refused — as an empty array where a real is expected — and
E-423's pins still pass.

## 5. `$simparam` demanded a string literal

LRM 9-10: *"The argument param_name is a string value, either a string literal,
string parameter, or a string variable."* The signature said `Literal(String)`,
so only the first worked. The name is passed to the `SimParam` callback as an
ordinary lowered value, so `Val(String)` was the entire fix; all three kinds now
work, including a string variable assigned at run time.

## 6. `$fatal;` was rejected

Syntax 9-7 makes the whole parenthesised group optional:

```
fatal_message_task ::= $fatal [ ( finish_number [ , message_argument ... ] ) ] ;
```

`$error;`, `$warning;` and `$info;` already accepted the bare form; only `$fatal`
required an argument, so the spelling the LRM writes first was the one refused.

## 7. A string parameter file name PANICKED the compiler

Not on the audit's list — found while fixing the others, and the worst of them:

```verilog
parameter string fn = "noise.tbl";
... I(p,n) <+ noise_table(fn);
```

exited **101 with no diagnostic at all**. `noise_table`'s file-name argument was
typed `Val(String)`, which a string parameter satisfies, and the lowering then
did `as_literal(args[0]).unwrap()`. The table is read when the model is
*compiled*, so the name has to be a literal; `$table_model`, whose file name is
read the same way, already required one and rejected the identical model with a
clean type error. That sibling's rule is now applied here, and the `unwrap` is
defensive.

## Withdrawn: `$limit` with a user function is correct as it stands

The audit reported `$limit(probe, user_function, args)` as off by one, on the
evidence that `$limit(V, f1)` with a one-argument `f1` was rejected and that the
accepted shape appeared to pass a phantom `0`. Both readings were wrong.

LRM 9.17 says the simulator passes the user-defined function *the value of the
access function for the current iteration*, then *the internal state*, then
`$limit`'s third and subsequent arguments. Its arity is therefore always
`2 + extra`, and openvaf's rule — the function's arity equals `$limit`'s
argument count — is exactly that. The `1.0` that looked like a phantom argument
is the simulator declining to limit at all, which 9.17 explicitly permits:
*"the simulator may simply choose to have `$limit()` return the value of its
first argument"*.

The suite now pins the LRM-correct shapes: `f2(v,state)`, `f3(v,state,x)` and
`f4(v,state,x,y)` with the matching `$limit` calls.

## Refused with the reason: an array identifier as a `noise_table`

LRM 4.5.1 does allow an `array_identifier` here. It is still refused, because
this table is materialised when the model is **compiled** and a parameter or
variable array only has values at run time. Accepting one would hand the builtin
an empty table — the silent no-noise-at-all failure Enhancement-399 fixed for
`{...}`. What changed is the message: instead of `'tb' requires a bit-select
[i]`, which describes neither the rule nor the constraint, it now says the table
is an array parameter or variable whose values are only known at run time and
that a literal or a data file is required.

Making that message reachable took one non-obvious step: body validation only
runs on a body that type-checked, so inference has to *accept* the call and
record its signature for the validator's arm to fire at all.

## Known remaining gap

`parameter_identifier[msb:lsb]`, the second filter-argument form, is still
refused (`wrong number of array indices`). A range select is not distinguishable
from multi-dimensional indexing in the current syntax tree, so it needs syntax
support rather than an inference change — a separate piece of work. It is pinned
as refused so the suite records the state rather than ignoring it.

## Verification

`examples/lrmfuncs_examples/verify_lrmfuncs.py` — **228/228**, both solvers — is
the audit turned into a permanent suite: every math function in both spellings
checked to 1e-12; every optional-argument form of `ddt`, `idt`, `idtmod`,
`absdelay`, `transition`, `slew`, `last_crossing`, `limexp`, `ddx` and the
Laplace/Z filters checked against analytic values; all twelve noise forms against
a 1 kΩ resistor's 4kT/R; `ac_stim`; 26 RNG forms; 14 file-I/O forms verified by
reading back what was written; `$table_model` in 1-D, 2-D and 3-D.

**Corpus: 107 compiled by both, 17 rejected by both, 0 rc differences, 1 byte
difference.** The one difference is `bjt504.va` (MEXTRAM 504), which loses an
internal unknown — `implicit_equation_1` is gone from the new `.osdi`. A DC sweep
of Vb from 0.4 V to 0.95 V over 56 points gives a worst relative difference of
**0.000e+00** in both terminal currents, so the device is electrically identical
and simply solves one fewer equation.

`cargo test` passes across 44 test binaries. Full regression **372/372**, both
solvers.
