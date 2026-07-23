# vafdeadop_examples — Enhancement-307

**A `ddt` with no contributions crashed the openvaf-r compiler.**

`sim_back/topology/lineralize.rs` asserted that any analog operator reaching the
linearizer with an empty contribution list had to be a noise source:

```rust
if contributes.is_empty() {
    assert!(noise, "ddt should have been deadcode eliminated");
    return Evaluation::Dead;
}
```

That assumption is false. A `ddt` whose result never reaches a contribution can survive
dead-code elimination, and — because this was a plain `assert!`, not `debug_assert!` — it
fired in the **shipped release** build:

```
OpenVAF encountered a problem and has crashed!
```

## How it was found

Grammar-based fuzzing aimed at the compiler's **middle and back end**. Earlier campaigns
(E-147/148/213/219/220/230/263/264/265) hardened the lexer, preprocessor and parser, so
byte-level mutation mostly re-finds parser paths. This generator emits *well-typed*
Verilog-A that compiles, so it reaches MIR construction, the optimizer, autodiff and
codegen. Run against an assertions-enabled build — openvaf-r's MIR and LLVM verifiers are
`debug_assert!` only — **5 independent seeds out of 3000** hit this exact assert.

Delta-debugging plus ablation pinned the trigger to: the **`ddt`**, a **current probe on a
declared branch** (`I(br1)`, a probe-only branch), an **if/else**, and a **case** — in a
module with **no contributions at all**. Remove any one and the crash stops.

## The fix

Take the `Evaluation::Dead` path the function already returns for the noise case. No
contributions means the operator's value reaches no device equation, so replacing its
result with zero and retargeting pending uses — which is exactly what the noise branch does
— is correct for a plain `ddt` too.

## Verify

```bash
python3 verify_vafdeadop.py
```

Four checks under both solvers: the reproducer compiles (it crashed the compiler before)
and the produced `.osdi` loads; and a **contributing** `ddt` is confirmed numerically
unchanged (`I = C·ddt(V)` still gives `|Z| = 1/(2πfC)` exactly), since the fix touches the
Dead path. The suite fails on the pre-fix compiler.

## A second bug this campaign surfaced (not fixed here)

Extending the fuzz to 5000 seeds found a **different, pre-existing** ICE at
`mir_llvm/src/builder.rs:143` — *"attempted to read undefined value"*. Minimal trigger: a
variable **read before a loop that is its only writer**

```verilog
real ra, rc; integer ib;
ra = (rc > 1.0 ? 2.0 : 3.0);            // rc read here...
for (ib = 0; ib < 1; ib = ib + 1) rc = ra;   // ...written only inside the loop
```

The loop back-edge leaves `rc` undefined on entry, so a `BuilderVal::Undef` reaches
codegen. The old shipped compiler crashes on it too. Fixed in Enhancement-308.
