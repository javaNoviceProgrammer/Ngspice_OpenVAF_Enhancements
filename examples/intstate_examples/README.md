# intstate_examples — integer persistent/event-state variables (Enhancement-32)

Demonstrates **integer** persistent/event-state variables — and their exposure as
operating-point variables — using **the committed** `openvaf-r` and `ngspice-46`.

## What was broken

Any integer variable holding persistent state (read-before-write, or updated inside
`@(cross)`/`@(initial_step)`/... event blocks) **crashed the compiler**:

```
LLVM ERROR: Cannot select: f64 = add ...
```

The OSDI persistent-state slot type was hardcoded to `f64`, so the start-of-eval
state load returned a double that fed integer MIR ops. Real-typed persistent
variables (Enhancement-7) were unaffected. Additionally, ngspice could not record
integer opvars per-timepoint (`save @n1[n]` printed `OUTpData: unsupported data
type`): `getSpecial()` masked `IF_INTEGER` out of the vector type.

## The fix

- **OpenVAF**: hidden-state slots take the variable's own LLVM type
  (`lltype(var.ty)`), like the opvar path; the two dead
  `todo!("hidden state/event state")` stubs are replaced with real slot resolution.
- **ngspice**: `outitf.c` keeps `IF_INTEGER` in the special-vector type mask and
  records integer values into plot/rawfile vectors as reals.

See `../Enhancement-32.md`.

## The demo

`intstate_demo.va` — a 2 V / 1 kHz sine drives:

- `n` — **integer** `@(cross)` upward-edge counter, exposed as an opvar;
- `started` — **integer** `@(initial_step)` flag, exposed as an opvar;
- `vpeak` — **real** running peak (E-7 regression control).

## Run

```
python3 verify_intstate.py
```

Checks (ALL PASS): compiles (used to abort); no `unsupported data type`; final
`n == 5` (= upward crossings in 5 cycles); the per-timepoint waveform of `n` is a
clean `0..5` staircase stepping at the analytic crossing times; `started == 1`;
`vpeak` = sine amplitude.
