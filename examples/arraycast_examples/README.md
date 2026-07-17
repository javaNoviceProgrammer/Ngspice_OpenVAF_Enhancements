# arraycast_examples — Enhancement-214: whole-array type coercion

Guards a compiler-crash class that was found and patched **four separate times**
before being fixed at its cause. See [Enhancement-214.md](../../enhancements_doc/Enhancement-214.md).

## The class

An **integer** Value reaches a **float** MIR op (`feq`/`fmul`/`fsub`/`fdiv`).
`mir_opt::const_eval::eval_binary` has no `(Int, Float)` case, so the compiler panics:

```
invalid operation fdiv Int(1) Float(Ieee64(1.0))
OpenVAF encountered a problem and has crashed!
```

If constant propagation happens not to fold the expression, the same defect instead
reaches LLVM as `i32 = fadd .., ConstantFP:f64` → **`LLVM ERROR: Cannot select`**. One
bug, two faces.

The trigger is writing `{1}` where a real is expected — which is just how a unity
coefficient or a small selector is naturally written:

```verilog
integer num[0:0];
real    sel[0:0];
analog begin
    num[0] = 1;                                        // integer array variable ...
    sel[0] = mode;
    case (sel)                                         // ... real discriminant ...
        {1}: gain = 1.0;                               // ... integer item
    endcase
    V(out) <+ gain * laplace_nd(V(in), num, '{1.0, tau});
end
```

Both spellings used to crash. The root cause was a **dead cast**: inference records a
whole-array coercion on the array *expression*, but `lower_array_elems_impl` decomposes
the array and lowers each element itself, so `lower_expr`'s `needs_cast()` never saw
it. Every new array-consuming context re-inherited the trap. It is now honoured at that
one chokepoint.

## Files

| File | What it is |
|---|---|
| `arraycast_demo.va` | A unity-numerator first-order low-pass with a mode-selected gain — an integer array variable as the coefficient vector, and integer `case` items against a real discriminant. |
| `verify_arraycast.py` | 23 checks, run under both solvers (~5 s). |

## What is verified

1. **The class** — all five historical spellings compile instead of panicking:
   integer literal coefficients, integer array-variable coefficients, the same for
   `zi_nd`, an integer `case` item vs a real discriminant, and E-33's integer
   discriminant.
2. **No miscompile** — coercion must not quietly change a value. The integer spelling
   of the filter is **bit-identical** to the `'{1.0}` spelling across 13 AC points
   (worst deviation exactly 0 dB) and matches the analytic `1/(1+jωτ)` to 3.4e-08 dB.
3. **The item still matches** — the integer `case` arm is taken (`g = 7`, not the
   default), identical to the `'{1.0}` spelling.
4. **Valid code is unchanged** — real coefficients, real array variables,
   real/integer/string scalar cases, E-33's element-wise real array case.
5. **The demo** — modes 1/2/3 select gains 1.0/2.0/0.5 (mode 3 falls to `default`).

The guard is **mutation-tested**: with the fixes reverted, every repro crashes again
with exit 101.

## Run

```sh
python3 verify_arraycast.py
```
