# lrmevents — analog events vs. the LRM (Enhancement-522)

An LRM-2023 conformance audit of clause **5.10** found five bugs spanning
both halves of the toolchain. This suite pins the fixes end-to-end:

- **Table 5-1 exact per analysis**: the whole five-analysis matrix
  (`op`/`dc`/`tran`/`ac`/`noise`) checked — the OP of an `.ac`/`.noise`
  job no longer answers to `"dc"`, and `.noise` no longer answers to
  `"ac"` (LRM Table 4-22 defines `analysis("dc")`/`analysis("ac")` as 0
  at those points too, so one flag fix serves both channels).
- **`cross` obeys 5.10.3.2**: silent in `.dc` sweeps and at t = 0 (it
  fired in both, off Newton iterates), while a genuine transient crossing
  still fires exactly once; **`above`** fires in DC — including the
  mandated initialization event — pinned side by side.
- **Placement rules enforced**: nested `@(…)`, `cross` under a runtime
  `if` or inside a loop, and analog filters inside the event *expression*
  are targeted errors.
- **Invalid events are errors**: `@(absdelta(…))`, `@(named_event)`, and
  typos used to silently drop the event control and run the body on
  *every* evaluation.
- **Comma OR-lists** (5.10.1): `@(initial_step, timer(2.5u))` — the
  first cut of this very fix parsed the comma but dropped the second
  member in the unit splitter; check [8] exists because it caught that.
- **Tolerance honesty**: a nonzero `cross`/`above` tolerance warns that
  it is accepted but not honored; `0.0` stays silent.

Run `python3 verify_lrmevents.py` — 22 checks, both solvers.
