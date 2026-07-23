# Enhancement-307 — openvaf-r: a `ddt` with no contributions crashed the compiler

`sim_back/src/topology/lineralize.rs` assumed that any analog operator reaching the
linearizer with an empty contribution list could only be a noise source:

```rust
if contributes.is_empty() {
    assert!(noise, "ddt should have been deadcode eliminated");
    return Evaluation::Dead;
}
```

That does not hold. A `ddt` whose result never reaches a contribution can survive dead-code
elimination. And because this was a plain `assert!` rather than `debug_assert!`, it fired in
the **shipped release** build — the compiler died with *"OpenVAF encountered a problem and
has crashed!"* on valid, if unusual, Verilog-A.

## How it was found

A grammar-based fuzzer aimed at the compiler's **middle and back end**. The parser,
preprocessor and lexer were already hardened by earlier campaigns, so the remaining yield is
in MIR construction, the optimizer, autodiff and codegen — and reaching those requires input
that actually compiles. The generator therefore emits well-typed Verilog-A (analog operators
suppressed only where the LRM forbids them, so the compile rate is ~100%).

Run against an **assertions-enabled** build — openvaf-r's MIR verifier (`func.validate()`)
and LLVM module verifier are `debug_assert!` only, so a release build ships malformed IR
silently. **5 independent seeds out of 3000** hit this identical assert. Delta-debugging and
then element-by-element ablation isolated the trigger: the `ddt`, a current probe on a
declared (probe-only) branch, an `if/else`, and a `case`, in a module contributing nothing.
Removing any single one stops the crash.

## The fix

Return `Evaluation::Dead` unconditionally when the contribution list is empty, dropping the
`assert!`. That is the branch the function *already* takes for the noise case, and its
consumer replaces the operator's result with zero and retargets pending uses
(`retarget_pending!` + `replace_uses`). With no contributions the operator's value reaches no
device equation, so contributing zero is exactly right — a `ddt` that feeds nothing has no
effect on the system.

## Verification

`examples/vafdeadop_examples/verify_vafdeadop.py` — four checks under both solvers:

* the delta-debugged reproducer **compiles** (it crashed the compiler before);
* the produced `.osdi` **loads** into ngspice via `pre_osdi`;
* a **contributing** `ddt` is numerically **unchanged** — `I = C·ddt(V)` still yields
  `|Z| = 1/(2πfC)` to machine precision — which matters because the fix touches the shared
  `Dead` path.

The suite fails on the pre-fix compiler. The full 326-model corpus replays with an identical
pass/fail split on the old and new compilers (no regression), and a 5000-seed re-fuzz shows
zero occurrences of this assert (was 5 in 3000).

## A second, pre-existing bug this surfaced — documented, not fixed

The 5000-seed re-fuzz found a **different** ICE at `mir_llvm/src/builder.rs:143`,
*"attempted to read undefined value"*, which the **old** shipped compiler also crashes on.
Minimal trigger: a variable read before a loop that is its only writer —

```verilog
real ra, rc; integer ib;
ra = (rc > 1.0 ? 2.0 : 3.0);                  // rc read...
for (ib = 0; ib < 1; ib = ib + 1) rc = ra;    // ...written only in the loop
```

The loop back-edge leaves `rc` undefined on entry, so a `BuilderVal::Undef` reaches codegen.
Fixed in [Enhancement-308](Enhancement-308.md).

## Scope of change

`OpenVAF-master-20260610/openvaf/sim_back/src/topology/lineralize.rs`, one `assert!` removed.
