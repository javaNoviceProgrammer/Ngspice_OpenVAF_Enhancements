# Enhancement-545: a system function or random draw in a parameter default or range is refused, not crashed on

**Scope:** finding F1 of the compiler hunt
([`docs/bug_hunts/2026-09-04_openvaf-r-compiler.md`](../docs/bug_hunts/2026-09-04_openvaf-r-compiler.md)).
**Compiler only; ngspice is unchanged.**

**Suites:** [`constguard_examples`](../examples/constguard_examples/) 57 → 75;
UI test `openvaf/test_data/ui/const_sysfun.va` pins ten forms.

## What was wrong

```verilog
parameter real t0 = $temperature;
```

panicked the compiler (`mir_llvm` builder: *attempted to read undefined
value*). A parameter's default and range are validated in the *constant*
context, where `analysis()`, a variable reference and an analog operator were
already refused — but the simulation-state functions were not, so they
reached code generation of the setup functions with nothing to read.
`$mfactor` and its hierarchical family — a `ResolvedFun::Param`, not a
`BuiltIn` — folded to a placeholder 1 instead, and `$random` in a default
produced one fixed number for every instance.

## What changed

* `BuiltIn::is_sim_state_fun` names `$temperature`, `$vt`, `$abstime`,
  `$realtime` and `$port_connected`; the constant-context validator refuses
  those, every random draw (`is_rng`) and the `$mfactor` family with one
  diagnostic:

  ```
  error: system function '$temperature' is not allowed in constants
  ```

  with notes citing LRM 3.4, the way out (compute it in the analog block or in
  `analog initial`), and for a draw the model-declared statistics
  (`(* std *)` with `.option osdimc`).
* `$param_given` and `$simparam` keep their behaviour (`$simparam` keeps its
  evaluated-before-the-simulation warning, L015); the analog block is
  untouched.

## Verification

| check | result |
|---|---|
| `parameter real t0 = $temperature;` | refused with the diagnostic (was a crash) |
| `$vt`, `$abstime`, `$realtime`, `$port_connected(a)`, `$mfactor`, `$random`, `$rdist_normal` in a default or range | refused, ten forms in the UI test |
| `$param_given(r) ? 2.0 : 1.0` and `$simparam("gmin", 1e-12)` in a default | accepted |
| the same functions in the analog block | unchanged, run correctly |
| compiler test suite | 210 passing (`verilogae` excluded, pre-existing) |
| bundled model corpus | compiles as before |
| `constguard_examples` | 75 / 75, both solvers |
| full sweep | 453 of 453 |

This fix first carried the label E-544 in the constguard suite and the
compiler internals; it was relabelled E-545 when E-546 landed, since the
alter journal already held E-544.
