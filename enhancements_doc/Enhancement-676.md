# Enhancement-676: the string an unknown `$simparam$str` hands on after its `$fatal` is empty — it was the U+FFFD replacement character

**Scope:** F4 of the
[bug hunt of 2026-09-19](../docs/bug_hunts/2026-09-19_openvaf-r-operators-folding-and-delays.md).
openvaf: `osdi/stdlib.c` (`simparam_str`, the value returned after the
fatal). `examples/simparamstrdef_examples/` (one check added, 14 per solver).
Handbook [§2.11](../docs/handbook/02-verilog-a-language.md) row. **openvaf
only** — the stdlib is compiled into every model, so a model picks this up
when it is recompiled.

**Suites:** [`simparamstrdef_examples`](../examples/simparamstrdef_examples/)
14 of 14 per solver, both solvers (the new check fails on the E-670
binaries); full sweep 531 of 531.

## What was wrong

```verilog
string sinst;
analog begin
  sinst = $simparam$str("instance");
  @(initial_step) $strobe("instance=%s", sinst);
  ...
```

```
stdout:  OSDI n1: instance=�
stderr:  OSDI(fatal) n1: unknown $simparam$str "instance" (at the operating point)
         Error: a Verilog-A device raised $fatal during the operating point; aborting.
```

The compile-time L025 and the run-time `$fatal` are the LRM's (9.15: no
default, unknown name — an error). But an OSDI evaluation runs on to its end
after a fatal is raised: the simulator abandons the *results* (`E_PANIC`, the
operating-point variables left invalid) and not the code path, so whatever
the failed lookup returns reaches every later use in that evaluation — a
`$strobe`, a string compare, a `$fwrite`. The stdlib's `simparam_str`
returned the literal `"�"` after raising the flag: not a stray pointer or
uninitialised bytes, as the hunt guessed, but a deliberate sentinel — EF BF
BD, U+FFFD — which a reader cannot tell from a corrupt string.

## What changed

**The value is the empty string.** Well defined, prints as nothing, equal to
nothing meaningful — the string twin of the 0.0 the numeric `simparam`
returns on the same path. The strobe above prints `instance=`, and
`sinst == ""` is true. The warning, the fatal and the abort are as before.

## Verification

| check | result |
|---|---|
| `@(initial_step) $strobe("instance=[%s] empty=%d", s, (s == "") ? 1 : 0)` after the failed lookup | `instance=[] empty=1` (was `instance=[�] empty=0`) |
| the fatal and the abort | unchanged: `unknown $simparam$str "instance" (at the operating point)`, "aborting" |
| an unconditional `$strobe` in the same evaluation | not printed, on either binary: it belongs to the iteration that was never accepted and is dropped (LRM 9.4.6, 9.7.3) |
| `$simparam$str("instance", "d")` | the default, no fatal ([E-598](Enhancement-598.md), unchanged) |
| the E-670 binaries on the suite | the new check fails |
| full sweep | 531 of 531 |

## What this does not do

- The evaluation is not cut short at the `$fatal`: OSDI code cannot unwind
  out of a model, so the statements after it still run, now with a
  well-defined value. An initial-step `$strobe` after it prints at once, as
  every initial-step output does; an iteration-deferred one does not.
- The numeric `$simparam("nosuch")` without a default returns 0.0 after its
  fatal, as before.
