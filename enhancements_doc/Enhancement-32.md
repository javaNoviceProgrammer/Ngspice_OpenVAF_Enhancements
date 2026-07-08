# Enhancement-32 — integer persistent/event-state variables

This document describes the changes made to **OpenVAF-r** and **ngspice** in the
`version11/` directory to fix a **compiler crash on integer persistent state** and to
let **integer operating-point variables be recorded** in ngspice output vectors.

## The bug

A Verilog-A variable holds *persistent state* when its value must survive from one
evaluation to the next — either because it is read before it is written (a running
peak, an accumulator) or because it is only updated inside an event block
(`@(cross)`, `@(above)`, `@(timer)`, `@(initial_step)`). Enhancement-7/8 implemented
this via per-variable *persistent eval-output slots* in the OSDI instance data,
read at the start of `eval()` (`ParamKind::HiddenState`/`EventState`) and stored
back at the end.

Real-typed persistent variables worked. But any **integer** persistent variable
**crashed the compiler**:

```verilog
integer m;
if (V(a,c) > 1.0) m = m + 1;    // read-before-write -> persistent
```

```
LLVM ERROR: Cannot select: 0x...: f64 = add ...
    ... f64,ch = load<(load (s64) from %ir.18)> ...
```

(or a segfault, depending on surrounding code). Found during a deep-dive TODO sweep:
the two `todo!("hidden state/event state")` stubs in `osdi/src/inst_data.rs` sit on
exactly this hole.

### Root cause

`OsdiInstanceData::new` created every hidden-state slot with a **hardcoded `f64`
type**:

```rust
Some((var, eval_outputs.insert_full(val, ty_f64).0))     // hidden_state
```

The slot's recorded type drives *both* the end-of-eval store and the start-of-eval
`read_hidden_state` load. For an integer variable the state was therefore loaded
back as a **double** and fed straight into integer MIR ops — malformed LLVM IR
(`f64 = add`), which aborts instruction selection. Worse, `eval_outputs` is keyed by
MIR value and `insert_full` **overwrites on duplicate keys**, so the hardcoded `f64`
could also clobber the correctly-typed slot entry that the opvar path had already
inserted for the same value.

## The fix

### OpenVAF (`osdi/src/inst_data.rs`)

1. **Type the hidden-state slot from the variable** — exactly like the opvar path
   does:

   ```rust
   let ty = lltype(&var.ty(db), cx);
   Some((var, eval_outputs.insert_full(val, ty).0))
   ```

   Event-state slots keep `f64` (their values are always the crossing expression /
   next-fire time — genuinely real).

2. **Retire the two `todo!("hidden state/event state")` stubs** in
   `load_eval_output` / `nth_opvar_ptr`. They are unreachable today
   (`EvalOutput::new` only produces `EvalOutput::Param` for
   `Param`/`ParamSysFun`/`Temperature` kinds), but they now resolve the parameter to
   its persistent eval-output slot instead of panicking — a real implementation
   rather than a stub, in case a future path produces state-typed
   `EvalOutput::Param`s.

### ngspice (`src/frontend/outitf.c`)

With the compiler fixed, exposing the counter as an operating-point variable
(`(*desc="..."*) integer n;`) compiled and read correctly at end of run, but
**per-timepoint recording** (`save @n1[n]` + `tran`) printed
`OUTpData: unsupported data type` once per timestep and produced no vector:

- `getSpecial()` masked the vector type with `IF_REAL | IF_COMPLEX`, turning an
  integer instance-param's `IF_INTEGER` into **0** so no branch matched. The mask now
  preserves `IF_INTEGER`.
- Both per-point writers (the in-memory plot path and the rawfile path) now record
  `IF_INTEGER` values via `plotAddRealValue`/`fileAddRealValue((double) val.iValue)`
  — integer opvars land in output vectors as reals, like every other plot vector.

## Verification — `intstate_examples/`

`intstate_demo.va` packs the three cases that used to crash plus a real-typed
regression control: an integer `@(cross)` edge counter `n` (opvar), an integer
`@(initial_step)` flag `started` (opvar), and the real running-peak `vpeak` (E-7
behaviour). `verify_intstate.py` (ALL PASS), driving a 2 V / 1 kHz sine for 5
cycles:

1. it **compiles** (integer persistent state used to abort the compiler), and the
   run emits no `unsupported data type`;
2. final `n == 5` — exactly the number of upward 1 V crossings;
3. the recorded per-timepoint waveform of `n` is a clean staircase `0,1,2,3,4,5`,
   stepping at the analytic crossing times `asin(vth/A)/2πf + k/f` (max error
   < 10 µs = one timestep);
4. `started` reads 1;
5. `vpeak` reads the sine amplitude (real persistent state unchanged).

Regressions: the E-7 (`variable_persistence_examples`) and E-8
(`cross_examples`/`timer_examples`) transient decks re-run cleanly with the new
toolchain, and the full pre-fix crash matrix (9 models: integer/real ×
persistent/event/plain × exposed/hidden) now compiles.
