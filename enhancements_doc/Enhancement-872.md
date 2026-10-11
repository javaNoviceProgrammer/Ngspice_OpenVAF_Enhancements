# Enhancement-872: the coupled-inductor check no longer writes into freed memory when it runs twice — every point of a `dc temp` sweep did

**Scope:** found while folding F4 of the
[Sparse and KLU correctness campaign of 2026-10-11](../docs/bug_hunts/2026-10-11_sparse-klu-correctness-campaign.md).

ngspice:
- `spicelib/devices/ind/muttemp.c`, `MUTtemp`: the links are cleared before the systems are
  freed, and a system's report is given once.
- `spicelib/devices/ind/inddefs.h`: `MUTsysWarned`.

`examples/mutsystem_examples/` (new). **ngspice only.**

**Suites:**
- [`mutsystem_examples`](../examples/mutsystem_examples/): 4 of 4 per solver. On the E-869
  binaries [1] fails and [4] dies with SIGSEGV; [3] is a control.
- The full sweep: 576 of 576.

## What was wrong

`MUTtemp` groups coupled inductors into systems (with `indverbosity`, on by default), to check
that each system's inductance matrix is positive definite. It set each inductor's `system` and
each link (`system_next_ind`, `system_next_mut`), checked, and freed the systems. The pointers
were left pointing at them, and only `INDsetup` cleared them.

A second `MUTtemp` with no setup between found `MUTind1->system` non-NULL. It took the pair to be
in a system already and wrote the coupling into it, into freed memory. That happens at every
point of a `dc temp` sweep, which re-runs the temperature step without a setup. Under Guard Malloc
a two-inductor transformer through `dc temp 0 100 10` died with SIGSEGV in `MUTtemp`. Without it
the run went on, and no system was ever built again. A coupling that went wrong at a later
temperature was never reported: an L1 with `tc1=-0.02` passes through zero on the way to 100 °C
in silence.

## The change

Before each system is freed, its inductors' `system` and `system_next_ind`, and its couplings'
`system_next_mut`, are cleared. Every `MUTtemp` then builds and checks its systems afresh. The
negative L1 at 100 °C is reported as `l1 < 0`.

A system's report, "The Inductive System consisting of … is not positive definite", would then
repeat at every sweep point. It used to appear once, but only because the systems were never
rebuilt. Each coupling now carries a bit, `MUTsysWarned`, set when its system is reported, and a
system whose couplings have all been reported is checked in silence. A k of 1.5 through an
11-point sweep is reported once.

## The checks

`mutsystem_examples`:
- **[1]** L1 with `tc1=-0.02` turns negative at 100 °C in a `dc temp` sweep: the report names it.
- **[2]** k = 1.5 through an 11-point temperature sweep: "not positive definite" is reported once.
- **[3]** (control) k = 0.9 through the sweep: no report, 11 points.
- **[4]** The sweep under Guard Malloc runs to the end. This runs on macOS and is skipped where
  `/usr/lib/libgmalloc.dylib` is absent.
