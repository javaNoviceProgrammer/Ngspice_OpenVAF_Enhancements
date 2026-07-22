# Enhancement-293 — openvaf-r: one analog operator nested directly inside another

```verilog
analog I(a, b) <+ ddt(ddt(V(a, b)));      // internal error, no output
```

Any *directly* nested pair crashed the compile — `ddt(ddt(x))`, three deep, or split
across a variable (`x = ddt(V); I <+ ddt(x);`). Put anything at all in between and it
compiled fine:

```verilog
analog I(a, b) <+ ddt(2.0 * ddt(V(a, b)));   // always worked
```

## Root cause

`sim_back/topology/lineralize.rs`, `builid_analog_operators` walks the analog operators
and materializes each according to how it was classified:

* `Evaluation::Equation` allocates an implicit unknown, calls
  `replace_uses(res, eq_val)`, and then **deletes the operator's instruction**;
* `Evaluation::Linear` adds a stored `dimension` value into the contribution's reactive
  part.

Those `dimension` values live in the `Evaluation::Linear { contributes }` triples —
that is, **outside the data-flow graph**. `replace_uses` rewrites operands held inside
the DFG; it cannot reach them.

With direct nesting the stored dimension *is* the inner operator's result, so once the
inner operator is processed the outer one holds a value whose defining instruction has
been removed:

```
classify inst0 res=v17                eval=Equation
classify inst1 arg0=v17               eval=Linear { contributes: [(v20, v17, v3)] }
EQUATION inst0 res=v17 -> eq_val=v21  (inst0 REMOVED)
LINEAR   inst1 uses dimension=v17     (def = Result(inst0, 0))   <-- removed
```

With an `fmul` in between, the replay yields a fresh value (`Result(inst2)`, the
multiply) rather than the operator's own result — which is why `ddt(2*ddt(x))` never
tripped it. Everything derived from the dangling value surfaced later as
`invalid argument vN` when the instance-init function was validated.

## Fix

Iterate the operator list by index so an operator can fix up the entries still pending
behind it, and retarget any pending `dimension` that names this operator's result:

```rust
retarget_pending!(res, eq_val);
self.func.dfg.replace_uses(res, eq_val);
```

`eq_val` — the implicit unknown the inner operator became — is exactly the value the
outer operator's reactive contribution should use, so this states the correct
second-derivative formulation rather than merely removing a dangling reference. The
`Evaluation::Dead` arm carries the same hazard and gets the same treatment (retargeted
to `F_ZERO`).

The reverse order is already safe: a `Linear` processed *first* inserts a genuine DFG
use, which a later `Equation`'s `replace_uses` does reach.

## Verification

`examples/vafcodegen_examples/verify_vafcodegen.py` — in AC a `ddt` is `j*omega`, so a
second derivative is `(j*omega)^2 = -omega^2`. `|I|` tracks `omega^2` across four
decades:

| f (Hz) | measured \|I\| | analytic omega^2 |
|---|---|---|
| 1 | 3.947842e+01 | 3.94784e+01 |
| 10 | 3.947842e+03 | 3.94784e+03 |
| 100 | 3.947842e+05 | 3.94784e+05 |
| 1000 | 3.947842e+07 | 3.94784e+07 |

purely real, and `ddt(2*ddt(V))` — the formulation that already compiled — comes out at
exactly **2x**, an independent cross-check of the new path against the old one.

## A pre-existing limitation this surfaced — and how to avoid it

Chained `ddt` in **transient** is unusable under ngspice's default trapezoidal
integration, and perfectly usable under Gear. **Set `.options method=gear` and the
problem goes away.**

| step | TRAP error | Gear error |
|---|---|---|
| 1 ms | −23.71 | +0.00101 |
| 500 µs | +23.75 | +0.00025 |
| 100 µs | +23.79 | +0.00005 |
| 10 µs | +79.25 | +0.00005 |

(against an analytic `d²V/dt² / V` of 39.478 for `V = sin(2πt)`.)

### What trapezoidal actually does here

It is **not** a divergence, and not an error that grows as the step shrinks. Dumping
consecutive timesteps shows the answer alternating on **every single step**:

```
t=0.6102  i/v = +76.802        t=0.6112  i/v = +2.374
t=0.6122  i/v = +76.369        t=0.6132  i/v = +2.799
t=0.6142  i/v = +75.953        t=0.6152  i/v = +3.205
```

The mean of each adjacent pair is the correct answer. The solution carries a persistent
±oscillation at the Nyquist rate (period `2h`) that never decays, so a single sample
lands wherever the parity puts it. Averaging pairs converges properly:

| step | mean of adjacent pair | ring amplitude |
|---|---|---|
| 1 ms | 39.578 | 36.392 |
| 500 µs | 39.529 | 36.424 |
| 100 µs | 39.488 | 36.468 |

The amplitude is roughly **constant** in `h` — it does not grow as the step shrinks —
and it is strongly drive-dependent (a cosine drive rings at ~456 rather than ~36).

This is the signature of **trapezoidal ringing**: trapezoidal is A-stable but not
L-stable, so its amplification factor tends to −1 as `hλ → −∞` and the highest-frequency
mode is reflected rather than damped. Gear/BDF is L-stable and annihilates it. (The
signature is measured here; the amplitude is not derived.)

Two controls worth recording:

* a **single** `ddt` — an ideal capacitor — does not ring at all: trapezoidal and Gear
  agree to four-plus digits. Only the chained form excites the mode;
* it is **not** simply an inconsistent starting derivative. Driving with a cosine (zero
  initial slope) instead of a sine was tested precisely to check that, and it rings
  *worse*, so that explanation is refuted rather than assumed.

### Relation to this enhancement

None, beyond having surfaced it. Both formulations agree with each other to six figures,
and the one that already compiled is **bit-identical between the pre-fix and post-fix
compilers** at every timestep — Enhancement-293 neither causes nor cures this.

Stated plainly: Enhancement-293 makes nested `ddt` compile and be exactly correct in
AC / small-signal. For transient, use `.options method=gear`.

## Scope

One source file (`openvaf/sim_back/src/topology/lineralize.rs`). No public interface or
OSDI ABI change.
