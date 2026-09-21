# Enhancement-686: `$mfactor` in a flow contribution is warned (L037) — the LRM's `badres` compiled in silence

**Scope:** F4 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_ngspice-osdi-analyses-sens-and-events.md).
openvaf: `basedb/src/lints.rs` (lint L037 `mfactor_double_scaling`, warn), `hir_ty/src/validation/body.rs`
(the taint pass over the body), `hir_ty/src/validation.rs` (the report), `test_data/ui/const_sysfun.log`
(the snapshot gains the warning). `examples/inputport_examples/` (two checks, 8);
`examples/lrmhier_examples/` (the two fixtures that compose `$mfactor` on purpose carry the allow
attribute). **openvaf only.**

**Suites:** [`inputport_examples`](../examples/inputport_examples/) 8 of 8 per solver, both
solvers (both new checks fail on the E-680 binaries: no L037, and `-A mfactor_double_scaling` is
an unknown lint there); `lrmhier` unchanged; the compiler workspace tests green apart from the
three pre-existing sourcegen drift failures; every bundled Verilog-A file compiled: 782 files, one
hit outside the two fixtures — `lrm_examples/va/lrm_p155_1.va`, which *is* the LRM's `badres`;
full sweep 531 of 531.

## What was wrong

LRM 6.3.6: when an instance has a non-unity `$mfactor`, "all contributions to a branch flow
quantity in the analog block shall be multiplied by $mfactor" and "the value returned by any
branch flow probe … shall be divided by $mfactor", automatically. Then: "Verilog-AMS does not
provide a method to disable the automatic $mfactor scaling. The simulator shall issue a warning
if it detects a misuse of the $mfactor in a manner that would result in double-scaling", and of
its own example

```verilog
module badres(a, b);
  ...
  I(a,b) <+ V(a,b) / r * $mfactor; // ERROR
```

"the simulator will generate an error for this module". openvaf-r compiled it, and the hunt's
variable-routed form (`mf = $mfactor; I(p,n) <+ mf * V(p,n) / r;`), with `Finished building`
and nothing else; under `m=2` the current was scaled four times, under `m=3` nine. The scaling
itself is what the standard prescribes; the silence was the defect.

## What changed

**Lint L037 `mfactor_double_scaling` (warn).** After the body walk, a pass taints every
variable assigned from an expression that reads `$mfactor` — directly or through another tainted
variable, to a fixed point over the whole body, by name — and reports each contribution to a
branch *flow* whose value carries a tainted read, at the read:

```
warning[L037]: `$mfactor` scales this flow contribution a second time
  --> badres.va:6:28
  |
6 |     I(a,b) <+ V(a,b) / r * $mfactor; // ERROR per LRM
  |                            ^^^^^^^^ the contribution's value depends on $mfactor
  |
  = LRM 6.3.6: the simulator multiplies every contribution to a branch flow by $mfactor itself
    (and divides a flow probe by it), so a value that already carries $mfactor is scaled twice
    -- the LRM's `badres`, for which 'the simulator will generate an error'
  = help: use $mfactor only where nothing is scaled for you -- in a condition (`if (r / $mfactor
    < 1e-3) V(a,b) <+ 0;`, the LRM's `parares`), a display, an operating-point variable -- or
    silence this with (* openvaf_allow="mfactor_double_scaling" *) on the statement
```

What is not a value of a flow contribution stays silent: an `if` condition (the LRM's `parares`)
and a `?:` condition, a potential contribution, a display, an operating-point variable. A noise
contribution to a flow branch is a flow contribution (LRM 6.3.6's third rule scales its power)
and is reported. A bare `$mfactor` is lowered as a zero-argument call of the system function,
which is where the pass reads it. Warn, as the LRM's sentence has it; `-E` makes it the error
the LRM's example announces; `-A` and the statement attribute silence a deliberate case, as
they do for every lint. The pass is not flow-sensitive: an assignment anywhere taints the name
everywhere, which errs toward the warning.

**Two fixtures carry the attribute.** `lrmhier_examples/mnest.va` and `mxform.va` compose a
`$mfactor` read with the automatic scaling on purpose — that is what they test ("read composes:
4·1e-3, scaled ×4 = 16 mA"); they say so beside the statement. The `hir` UI snapshot
`const_sysfun.log` gains the warning for its `(t + m) * 0.0` contribution, where `t` was
assigned from `$mfactor`: the rule is by data flow, and that fixture is about constants.

## Verification

| check | result |
|---|---|
| `badres`; `mf = $mfactor; g = mf / r; I <+ g*V`; `I <+ white_noise(k * $mfactor)` | one L037 each, at the read, naming LRM 6.3.6 and `badres` |
| `parares`; `I <+ (r/$mfactor < 1e-3) ? 0 : V/r`; `V(a,b) <+ I*r*$mfactor*0`; `$strobe($mfactor)` and an opvar | silent |
| the attribute; `-A`; `-E`; `--lints` | silent; silent; an error that stops the build; `mfactor_double_scaling L037` |
| the 782 bundled Verilog-A files | one hit, the LRM's own `badres` excerpt (`lrm_p155_1.va`) |
| the E-680 binaries on the suite | both new checks fail |
| workspace tests; full sweep | green apart from the sourcegen drift; 531 of 531 |

## What this does not do

- It does not judge a potential contribution: the simulator does not scale potentials, so a
  `$mfactor` there is not double scaling; whether it is right physics is the model's own.
- It does not look into analog functions: a function that reads `$mfactor` and returns it into a
  flow contribution is not traced (the function body is its own scope); its *arguments* are.
- It does not change the scaling (LRM 6.3.6 forbids disabling it); `badres` still runs at 4×.
