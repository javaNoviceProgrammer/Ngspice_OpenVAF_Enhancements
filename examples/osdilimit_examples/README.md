# osdilimit_examples — Newton step limiting for OSDI MOSFETs and BJTs

Pins F1 of [`docs/bug_hunts/2026-09-04_large-circuits-speed-and-correctness.md`](../../docs/bug_hunts/2026-09-04_large-circuits-speed-and-correctness.md).

ngspice's built-in MOSFETs, BJTs and diodes limit every junction and channel
voltage step inside their load routines (`DEVfetlim` / `DEVlimvds` /
`DEVpnjlim`) and start a cold operating point from a weakly-on guess. A
Verilog-A model gets that only through `$limit`, and BSIM4 and PSP103 ship
without one — so a chain of 100 OSDI inverters needed dynamic gmin stepping
and 333 iterations for its operating point where the built-in twin converged
in 9, and a 40×40 grid of them took 167 iterations.

The simulator now recognizes a 3/4-terminal MOSFET (`d,g,s[,b]`) or BJT
(`c,b,e[,s]`) by its terminal names, reads the model's polarity (`type`) and
threshold (`vth0` / `vto`), and applies the built-ins' limiting and cold-start
guess in the type-normalized frame — across the model's own internal
drain/source/gate/bulk nodes (`DI`, `SI`, `GP`, `BI`) when its series
resistances leave them live. A model that limits itself, has a further
terminal (a thermal node), or keeps another live internal node (MEXTRAM's
`b1`/`e1`) is left alone. The operating point reached is the same to 1e-16:
the limiting changes only the path.

```
.option noosdilim        switch the simulator-side limiting off
set osdilim_verbose      say, once per model, what was decided and why
```

```bash
python3 verify_osdilimit.py    # 12 checks, both solvers
```

The models are compiled from the VA-Models corpus on each run (BSIM4, PSP103,
HiCUM L2, MEXTRAM; about five seconds).

Since [E-717](../../enhancements_doc/Enhancement-717.md) the second check of [2] — the
un-limited path reaching the limited operating point — is asserted only when the legacy
path converges. On the 100-stage chain under KLU that path sits on a knife edge: a
nanovolt at the input, or the last bit of a conductance (E-717 changed BSIM4's Jacobian
by one unit in the last place), decides between convergence in 139 iterations and a
7e54 V blow-up, on either compiler. A divergence is printed as the legacy path's own
failure mode; the limited path converges in 8 iterations throughout.
