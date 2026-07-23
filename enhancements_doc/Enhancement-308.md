# Enhancement-308 — openvaf-r: an uninitialized read feeding a loop-carried phi crashed codegen

A variable read **before** a loop that is its only writer leaves the loop-carried phi node
with an incoming value that no reachable block defines:

```verilog
real ra, rc; integer ib;
ra = (rc > 1.0 ? 2.0 : 3.0);            // rc read here, before it is ever written
for (ib = 0; ib < 1; ib = ib + 1) rc = ra;   // ...written only inside the loop
```

An optimizer pass removes that value's defining instruction on the dead path but keeps the
phi edge that referenced it. Code generation then reached `BuilderVal::get()` on a value
still in the `Undef` state and hit

```
unreachable!("attempted to read undefined value")   (mir_llvm/src/builder.rs:143)
```

Because it is a plain `unreachable!`, the **shipped** compiler crashed — *"OpenVAF
encountered a problem and has crashed!"* — on valid Verilog-A. This is the second bug from
the grammar-based middle/back-end fuzzing campaign that produced
[Enhancement-307](Enhancement-307.md) (E-307 fixed the `ddt`-with-no-contributions crash and
documented this one as open).

## Diagnosis

The MIR shows it exactly. Unoptimized, the ternary is a phi and the loop-carried variable
references it:

```
v18 = phi [v11, block3], [v14, block4]   ; ra = (rc > 1.0 ? 2.0 : 3.0)
v29 = phi [v35, block5], [v18, block7]   ; rc, loop-carried; back-edge value is v18
```

Optimized, **v18's defining phi is gone but the v29 edge still names it**:

```
v29 = phi [v18, block7], [v35, block12]  ; v18 is defined nowhere
```

The whole `ra`→`rc` chain is dead (nothing is contributed), so a pass removed `v18`; `v29`
survives only because an `optbarrier` keeps it nominally live, and its stale edge to `v18`
was never updated. The MIR verifier does not catch it: its phi check only verifies dominance
`if let Some(bb) = inst_block(def)`, which is `None` for an instruction detached from the
layout, so the dangling edge passes silently — and being `debug_assert!`, the verifier does
not run in release anyway.

## The fix, and why it is provably correct

`build_func` builds every **reachable** block first (reverse postorder), then completes the
phi nodes. So any value defined by a reachable instruction is already `Eager` by the time
phi completion runs. A phi input still `Undef` at that point necessarily names a value that
**no reachable block defines** — a dead path. Lowering it to an LLVM `undef` of the phi's
type (via the already-present `cx.const_undef`) is the correct representation of a value that
is undefined on that path; and because the path is dead it never reaches a device equation.

This is a whole-class fix: it resolves any future instance of an optimizer leaving a value
that flows only into dead phi edges, rather than chasing which pass dropped this particular
one. The alternative — hunting the exact pass — would repair one reproducer while leaving the
`unreachable!` a latent shipped-crash for the next.

## Verification

`examples/vafuninitloop_examples/verify_vafuninitloop.py` — two checks under both solvers.
The reproducer compiles (it crashed before); and a **live** loop-carried accumulator is
numerically **unchanged** — a conductance summed over N loop iterations reads back exactly
`N·g` to machine precision. That second check is the load-bearing one: if the `undef`
substitution leaked into a live phi, the accumulator would compute garbage. It does not.

The suite fails on the pre-fix compiler. The full corpus (328 models) replays with an
identical pass/fail split on the old and new compilers (no regression). An 8000-seed re-fuzz
shows **zero** occurrences of either this crash or the E-307 one.

## A third bug this surfaced — documented, not fixed

The 8000-seed re-fuzz found a **different, pre-existing** ICE at
`lib/stdx/src/packed_option.rs:60` (a `PackedOption::unwrap()` on `None`), which the old
shipped compiler also crashes on, at roughly 1 in 8000. Left for a separate change.

## Scope of change

`OpenVAF-master-20260610/openvaf/mir_llvm/src/builder.rs`, the phi-completion loop in
`build_func`.
