# vafuninitloop_examples — Enhancement-308

**An uninitialized read feeding a loop-carried phi crashed openvaf-r's code generator.**

A variable read **before** a loop that is its only writer leaves the loop-carried phi node
with an incoming value that no reachable block defines:

```verilog
real ra, rc; integer ib;
ra = (rc > 1.0 ? 2.0 : 3.0);            // rc read here, before it is ever written
for (ib = 0; ib < 1; ib = ib + 1) begin
   rc = ra;                             // ...written only inside the loop
end
```

An optimizer pass drops that value's defining instruction on the dead path but keeps the
phi edge, so code generation reached `BuilderVal::get()` on a value still in the `Undef`
state and hit

```
unreachable!("attempted to read undefined value")   (mir_llvm/src/builder.rs:143)
```

It is a plain `unreachable!`, so the **shipped** build crashed — *"OpenVAF encountered a
problem and has crashed!"* — on valid Verilog-A.

## How it was found

The same grammar-based middle/back-end fuzzer that produced [E-307](../../enhancements_doc/Enhancement-307.md).
Seed 3230 of an 8000-seed run; delta-debugged to the form above. The trigger needs the
module to contribute nothing that would keep the value live — adding `I(p,n) <+ ra;` makes
the value live and the phi input a real value, and the crash disappears.

## The fix, and why it is provably correct

`build_func` builds **every reachable block first**, then completes the phi nodes. So any
value defined by a reachable instruction is already materialised (`Eager`) by the time the
phi-completion pass runs. A phi input still `Undef` at that point therefore names a value
that **no reachable block defines** — a dead path. Lowering it to an LLVM `undef` of the
phi's type is the correct meaning of a value that is undefined on that path, and because the
path is dead it never reaches a device equation.

## Verify

```bash
python3 verify_vafuninitloop.py
```

Two checks under both solvers: the reproducer compiles (it crashed the compiler before);
and a **live** loop-carried accumulator is numerically **unchanged** — a conductance summed
over N loop iterations reads back exactly `N·g` — which is what proves the `undef`
substitution touches only dead-path inputs and never a real value. The suite fails on the
pre-fix compiler.

## A third bug this campaign surfaced (fixed in Enhancement-309)

Extending the re-fuzz to 8000 seeds turned up a **different, pre-existing** ICE at
`lib/stdx/src/packed_option.rs:60` — a `PackedOption::unwrap()` on a `None` (the old shipped
compiler crashes on it too), at roughly 1 in 8000. Fixed in Enhancement-309.
