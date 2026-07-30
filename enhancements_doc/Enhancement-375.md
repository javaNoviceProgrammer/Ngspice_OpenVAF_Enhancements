# Enhancement-375 — a loop that cannot finish is now a compile error

A Verilog-A module body must complete one evaluation. A loop that cannot exit
makes that impossible, and openvaf-r had no diagnostic for it.

## What it used to do, and why the current state was the worst one

Three different behaviours, in order:

| | behaviour |
| --- | --- |
| originally | the compiler **panicked** — an `unwrap()` on a loop-exit block that was never created |
| after [Enhancement-363](Enhancement-363.md) repaired the CFG | the compiler **emitted a model** |
| now | a compile-time **error** |

The middle state is the one that prompted this. `while (1)` produced a
well-formed 36,920-byte `.osdi`; ngspice loaded it without complaint and then
**hung forever** on the first device evaluation, with no diagnostic at all.

That is strictly worse than the original crash. A compile-time panic is immediate
and loud. A simulator that never returns just looks slow, and the model is the
last place anyone looks. The fuzz-campaign note that recorded the original defect
warned about exactly this outcome and named the fix — a diagnostic in
`hir_ty/src/validation/body.rs` — which is what this is.

There is no third option. There is no correct object code for a model that cannot
finish an evaluation: emitting the loop hangs the simulator, and substituting a
value for the unreachable code invents a device that was never described.

## The check

A loop is rejected when its controlling condition **provably cannot change**:

```
error: loop condition is always true
  --> nt.va:6:12
  |
6 |   while (1) begin s = s + 1.0; end
  |          ^ this is never false
  |
  = a module body must complete one evaluation; a loop that cannot exit would
    hang the simulator on the first evaluation with no further diagnostic
  = help: write what the condition reads inside the loop body, or in the `for`
    increment
```

A second message, `loop condition can never change`, covers the case where the
condition is not a literal but nothing in the loop writes what it reads. The two
are kept distinct deliberately: a non-zero literal is *certainly* infinite, while
an invariant non-literal condition is either never entered or never left, and the
report must not claim more than it knows.

The analysis is **sound in the reject direction** — every bail-out means "say
nothing", so it can miss a hang but must not reject a model that terminates:

* `repeat (n)` is counted and always terminates.
* a literal-zero condition is a zero-trip loop, not an infinite one.
* `$finish`, `$stop` and `$fatal` leave the loop.
* a user function may write through an **output argument**, so every name passed
  to one counts as written; a user call in the *condition* abandons the check.
* `$random`/`$dist_*`/`$rdist_*` return a fresh value per call.

Names are matched syntactically rather than resolved to `VarId`s, which also errs
the safe way: a shadowing declaration in a nested block makes an unrelated name
look written, suppressing the diagnostic rather than inventing one.

**Not detected, and undecidable in general:** a loop whose condition variables are
written but never toward the exit. Nested loops sharing an index are the classic
case — `for(i=0;i<10;i=i+1) for(i=0;i<3;i=i+1)` runs forever, while the same shape
with the bounds swapped terminates.

## `disable` — three compiler crashes closed on the way

`disable <block>` is Verilog-AMS's loop break (LRM 5.4) and would be the obvious
escape hatch. It is deliberately **not** counted as one here, because of what it
does today.

It works, and keeps working, for a loop that can also finish normally — such a
loop's condition changes, so this check never looks at it. But as the *sole* exit
from a loop whose condition cannot change, the code after the loop is reachable
only through the `disable` edge, and OSDI codegen aborts:

```
Panic occurred in file 'openvaf/mir_llvm/src/builder.rs' at line 143
unreachable!("attempted to read undefined value")
```

Verified on the pre-fix binary for a literal `while (1)`, a constant-folding
`while (1 > 0)` and a non-constant `while (i < 10)` whose `i` is never written —
**3/3 crashed**, with and without the loop result being used. Reporting them here
therefore cannot regress a working program, because there is no such program: it
replaces a compiler crash with an actionable error. The diagnostic says so rather
than sending the user toward the crash:

```
= note: `disable <block>` is not accepted as the only way out of such a loop;
  it works for a loop that can also finish normally
```

`$finish`/`$stop`/`$fatal` are treated differently because they genuinely compile
today; breaking them would be a real regression.

## Verification

`examples/vafloop_examples` — nine reject cases, ten accept cases, two message
checks. The **accept** half is the more important one: it is what proves the check
has not broken working code.

```
   fixed:     21/21
   pre-fix:   10/21    6 x "compiled silently"   3 x "CRASHED" (rc=101)
```

The example refuses to score a crash or a compiler hang as a pass — replacing
those is the entire point.

Beyond the example, a **differential run over all 726 `.va` files in the repo**,
new binary against the shipped one: **0 files rejected by the new check, 0
regressions**. openvaf's own `hir_ty`/`hir_lower`/`hir_def`/`basedb` suites are
green at 28/28. (`verilogae`, the Python-binding crate, does not build for
unrelated pre-existing reasons and was not touched.)

Regression 299/299 → 300/300.

## Consequence for an earlier note

This supersedes the "still OPEN on purpose" status the 2026-07-29 fuzz campaign
recorded for its defect #1. The crash it described no longer reproduces — the
Enhancement-363 CFG repair closed it — but the emission it turned into was worse,
and that is what this fixes.
