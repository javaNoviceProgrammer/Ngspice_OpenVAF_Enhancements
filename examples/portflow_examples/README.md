# portflow_examples — port-branch flow access `I(<port>)` (Enhancement-29)

Demonstrates the **port-branch flow probe `I(<port>)`** working, using
**version11's own** `openvaf-r` and `ngspice-46`.

## What was broken

`I(<p>)` is the current flowing **into** the module through terminal `p` — used to
build current-controlled sources (CCCS/CCVS) and to monitor terminal currents.
Models using it *compiled*, but the value was **always 0 at run time**: it was an
unfinished stub (`CurrentKind::Port => { // TODO? }` in `sim_back`, and a hard-coded
`const_real(0.0)` in the OSDI eval). So `I(out) <+ 10*I(<in>)` produced `i(out) = 0`.

## The fix

Port flow is given a real DAE unknown whose defining equation mirrors node `p`'s
Kirchhoff residual (resistive **and** reactive):

```
I(<p>) = residual[KCL(p)]   =   net device current flowing out of node p
```

Because the reactive part is mirrored too, `I(<p>)` includes displacement
(capacitive) current. Pure `sim_back` + `osdi` change; see `../Enhancement-29.md`.

## The demo

`portflow_demo.va` is a CCCS `I(out,com) = k*I(<in>)` whose input terminal is an
`rin || cin` load, so `I(<in>) = V(in,com)/rin + cin*d/dt V(in,com)`.

## Run

```
python3 verify_portflow.py
```

Checks (ALL PASS), end-to-end:

1. **resistive (DC)** — `i(vout) = -k*vin/rin` (−20 mA for k=10, vin=2, rin=1k);
   this was **0** before the fix;
2. **gain scaling** — `i(vout)/i(vin) == k` for k ∈ {1, 5, 25, 100};
3. **reactive (AC)** — with `cin`, the port flow carries both the in-phase (`1/rin`)
   and quadrature (`w*cin`) parts, and `|i(vout)| = k*|i(<in>)|` — displacement
   current flows through the probe.

## Gotcha

Do **not** name a module `cccs`, `vccs`, or `vcvs` — those collide with ngspice's
built-in controlled-source device types and crash ngspice's `.model` setup
(unrelated to port flow). The demo module is named `portflow_cccs`.
