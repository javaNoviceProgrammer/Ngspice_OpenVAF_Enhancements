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
