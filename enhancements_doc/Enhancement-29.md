# Enhancement-29 — port-branch flow access `I(<port>)` (version11)

This document describes the change made to **OpenVAF-r** in the `version11/`
directory to make the **port-branch flow probe `I(<port>)`** functional. The
front-end already parsed, type-checked and lowered `I(<p>)`, so models *compiled*,
but the value was **always 0 at run time** — it was an unfinished (`// TODO?`) stub.

## What `I(<port>)` is

`I(<p>)` — the *port branch* — is the current flowing **into** the module through
terminal `p`. It is most commonly used to build current-controlled sources (CCCS /
CCVS) and to monitor terminal currents:

```verilog
I(out, com) <+ k * I(<in>);   // CCCS: output current = k * (current into port in)
```

By Kirchhoff's current law the current entering the module at port `p` equals the
net device current flowing out of node `p`, i.e. the sum of every branch
contribution at that node.

## The bug

`I(<p>)` lowers to `ParamKind::Current(CurrentKind::Port(node))`. That parameter
was never wired into the DAE system, so it read as 0:

- **`sim_back/src/dae/builder.rs`** — in `build_input_unknown_pairs` the port case
  was literally:
  ```rust
  CurrentKind::Port(_) => {
      // TODO?
  }
  ```
  so a port flow was never registered as a model input / DAE unknown.
- **`osdi/src/eval.rs`** — the eval reader hard-coded it to zero:
  ```rust
  ParamKind::Current(CurrentKind::Port(_)) => cx.const_real(0.0),
  ```

A model like `I(out) <+ 10*I(<in>)` therefore produced `i(out) = 0` regardless of
the current actually flowing into `in`.

## The fix

Port flow is given a **real DAE unknown with a defining equation**, reusing the
exact machinery that already backs named/unnamed branch-current probes. Three small
changes, all confined to `sim_back` + `osdi`:

1. **`sim_back/src/dae/builder.rs` — new `build_port_flow_equations()`**, called at
   the top of `finish()` (before derivatives/Jacobian are computed). For every
   probed port flow `I(<p>)` it synthesises the equation

   ```
   residual[Current(Port(p))] = residual[KCL(p)] - I(<p>)      =>   I(<p>) = residual[KCL(p)]
   ```

   by mirroring node `p`'s **resistive and reactive** Kirchhoff residual into the
   port-current row and subtracting the unknown. Because the reactive part is
   mirrored too, the solved value includes **displacement (capacitive) current** for
   free. The mirrored `I(<p>)` value is the very same parameter the model reads, so
   any source built on `I(<p>)` sees the correct current. A port branch has no
   `branch(...)` object, so it never passes through `build_branch` /
   `add_source_equation`; this is why the equation has to be synthesised here.

2. **`sim_back/src/dae/builder.rs` — `build_input_unknown_pairs()`**: the
   `CurrentKind::Port` special case is removed, so port currents are registered as
   ordinary model inputs like any other branch current.

3. **`osdi/src/eval.rs`**: the hard-coded `const_real(0.0)` arm is removed, so
   `ParamKind::Current(CurrentKind::Port)` falls through to the generic
   `get_prev_solve(SimUnknownKind::Current(kind))` path and reads its solved value.

The OSDI descriptor side needed nothing new — `osdi/src/metadata.rs` already named
the unknown `flow(<node>)`.

## Verification — `portflow_examples/`

`portflow_demo.va` is a CCCS `I(out,com) = k*I(<in>)` whose input terminal is an
`rin || cin` load, so `I(<in>) = V(in,com)/rin + cin*d/dt V(in,com)`.
`verify_portflow.py` (ALL PASS) checks, end-to-end through version11's own
`openvaf-r` + `ngspice`:

1. **resistive (DC)** — `i(vout) = -k*vin/rin` (e.g. -20 mA for k=10, vin=2, rin=1k);
   this was **0** before the fix;
2. **gain scaling** — `i(vout)/i(vin) == k` for k ∈ {1, 5, 25, 100};
3. **reactive (AC)** — with `cin`, the port flow carries the in-phase (`1/rin`) and
   quadrature (`w*cin`) parts, and `|i(vout)| = k*|i(<in>)|` — proving displacement
   current flows through the probe.

The implementation is completely general: resistive, reactive, and mixed
resistive+reactive port loads all work.

## Gotcha (ngspice, not OpenVAF)

Do **not** name a Verilog-A module `cccs`, `vccs`, or `vcvs`. Those names collide
with ngspice's built-in controlled-source device types; ngspice then null-derefs in
`create_model` when the `.model` card is parsed. This is unrelated to port flow (any
OSDI module so named crashes) — just choose a different module name (the demo uses
`portflow_cccs`).

## Scope

- Pure `sim_back` + `osdi` change; the parser / type system / HIR lowering of
  `I(<p>)` were already in place.
- Vector (whole-bus) branches remain out of scope: `branch(bus, gnd)` is diagnosed
  (`requires a bit-select`); explicit per-bit `branch(bus[i], gnd)` works (E-3/E-4).
