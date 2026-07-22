# Enhancement-290 — openvaf-r: `$temperature` as an operator argument used the wrong struct-GEP type

```verilog
analog I(out) <+ ac_stim("ac", $temperature, 0.0);
```

crashed the shipped compiler outright — **SIGSEGV, exit 139** — while optimizing the
model. The malformed IR behind it:

```
Invalid indices for GEP pointer type!
  %4 = getelementptr inbounds double, ptr %0, i32 0, i32 5
```

## Root cause

`osdi/src/inst_data.rs` reads instance-data fields with `LLVMBuildStructGEP2`, whose
first argument is the **aggregate being indexed** — the instance-data struct. The
`ParamKind::Temperature` arm passed the **field** type instead:

```rust
NonNull::from(cx.ty_double()).as_ptr(),      // should be inst_data.ty
```

A two-index GEP is only meaningful on an aggregate, so `gep double, ptr, 0, 5` is
invalid IR — and the offset it describes is a flat `5 * sizeof(double)` = 40 bytes,
not `offsetof(instance, temperature)`. `TEMPERATURE` is field 5, and fields 0..4 are
the param-given bitfield, the two Jacobian pointer arrays, the node mapping and the
collapse flags — variable-length arrays whose combined size is essentially never 40
bytes. So even where LLVM did not crash, the load landed on unrelated bytes.

Every sibling gets this right: `eval_output_slot_ptr` and `temperature_loc` both pass
`self.ty`. The bug was in **two** places — `load_eval_output` (the noise / `ac_stim`
argument path) and `nth_opvar_ptr` (the operating-point-variable read path).

Only `$temperature` read **directly as an operator argument** takes this path. A
computed variable (`tk = $temperature;`) is lowered to an eval-output slot instead and
was always correct — which is why ordinary models never tripped it.

As with Enhancement-288/-289, the module verifier that reports invalid IR is a
`debug_assert!`, so a release build had nothing to stop it before LLVM's optimizer hit
the malformed GEP.

## Fix

Pass `inst_data.ty` — the instance-data struct — at both sites.

## Verification

`examples/vafcodegen_examples/verify_vafcodegen.py` — `tempacstim.va` compiles (the
pre-fix compiler exits 139) and, driven through a 1 Ω load, reads back the nominal
**300.15 K**:

```
mag(v(out)) = 3.001500e+02      expected 300.15
```

## Scope

One source file (`openvaf/osdi/src/inst_data.rs`), two call sites. No public interface
or OSDI ABI change.
