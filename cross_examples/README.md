# `cross()` / `above()` examples (version9)

Self-contained correctness examples for OpenVAF's new **`@(above(expr))`**
and **`@(cross(expr, dir))`** event-control support (Enhancement-8, Feature
A), covering **DC**, **AC**, and **transient** analysis. Uses the
**version9** toolchain:

- compiler : `../OpenVAF-master/target/release/openvaf-r` (built with `--features openvaf-driver/llvm18`)
- simulator: `../ngspice-46/build/src/ngspice` (locally built, OSDI-capable — not the system-wide `ngspice`)

See `../Enhancement-8.md` for the full implementation writeup.

## The models

`above_demo.va`: `@(above(V(in) - thresh)) count = count + 1.0;` — fires once
per `false->true` transition of `V(in) - thresh`, incrementing a persistent
counter exposed on `V(out)`.

`cross_demo.va`: `@(cross(V(in) - thresh, dir)) count = count + 1.0;` — fires
on any zero-crossing of `V(in) - thresh`, filtered by `dir` (1 = rising only,
-1 = falling only, 0 = either), incrementing the same kind of persistent
counter.

Both also report each firing via `$strobe` (observable in ngspice's console
output). Accumulating into a persistent `real` variable across firings is the
natural way to use these event functions, and used to crash the compiler —
see "Known limitations" below for the (now-fixed) root cause.

## Running

```sh
../OpenVAF-master/target/release/openvaf-r above_demo.va -o above_demo.osdi
../OpenVAF-master/target/release/openvaf-r cross_demo.va -o cross_demo.osdi
../ngspice-46/build/src/ngspice -b dc_sim_above.cir
../ngspice-46/build/src/ngspice -b ac_sim_above.cir
../ngspice-46/build/src/ngspice -b tran_above.cir
../ngspice-46/build/src/ngspice -b dc_sim_cross.cir
../ngspice-46/build/src/ngspice -b ac_sim_cross.cir
../ngspice-46/build/src/ngspice -b tran_cross.cir
python3 plot_above.py   # -> above_dc.png, above_ac.png, above_tran.png
python3 plot_cross.py   # -> cross_dc.png, cross_ac.png, cross_tran.png
```

## DC / AC: documented non-behavior

Both `.va` files drive `V(out) <+ count;`, where `count` only changes on an
`above()`/`cross()` firing. A DC sweep's operating-point solve and an AC
analysis's small-signal linearization both evaluate at a single fixed bias
— `above_dc.png`/`cross_dc.png` show `V(out)` as a **step function** of the
swept `V(in)`, stepping exactly at the sweep point where the swept value
first crosses `thresh` (persistent state carries across DC sweep points the
same way it carries across transient timesteps); `above_ac.png`/
`cross_ac.png` confirm the small-signal AC gain from `V(in)` to `V(out)` is
exactly zero at every frequency (a level-crossing event has no small-signal
counterpart). This is a "documented non-behavior" check, same convention as
`last_crossing_examples`/`variable_persistence_examples` in Enhancement-6/7.
`above()`/`cross()`'s actual (real, event-driven) behavior shows up fully in
the transient plots below.

## Transient: the real event-detection behavior

`above_tran.png`/`cross_tran.png` show `V(in)` alongside `V(out) = count` as
a staircase, stepping up by 1 exactly where the sine crosses `thresh`.

## Results (raw firing data)

`tran_above.cir` drives `V(in) = 2*sin(2*pi*1kHz*t)`, `thresh = 1.0`.
Expected: one `above` firing per 1kHz cycle (whenever the sine rises through
1.0), i.e. every ~1ms:

```
above fired at t=8.428e-05 in=1.01028 count=1
above fired at t=0.00108428 in=1.01028 count=2
above fired at t=0.00208428 in=1.01028 count=3
```

Matches exactly (spacing = 1ms, `in` ≈ `thresh` at each firing, `count`
incrementing by exactly 1 per firing — persistent state working correctly).

`tran_cross.cir` drives the same sine, `thresh = 0.0`, `dir = 0.0` (either
direction). Expected: two firings per cycle (rising and falling zero
crossings), i.e. every ~0.5ms, alternating sign of `in`:

```
cross fired at t=1e-08 in=0.000125664 count=1
cross fired at t=0.00050028 in=-0.00351858 count=2
cross fired at t=0.00100028 in=0.00351858 count=3
cross fired at t=0.00150028 in=-0.00351858 count=4
cross fired at t=0.00200028 in=0.00351858 count=5
cross fired at t=0.00250028 in=-0.00351858 count=6
```

Matches exactly (spacing = 0.5ms, alternating rising/falling as expected,
`count` incrementing by exactly 1 per firing).

## Compile-time verification (`--dump-unopt-mir`)

Both event kinds were compiled with `--dump-unopt-mir` and confirmed to
produce **genuine conditional branches** on the edge-detection condition
(`fle`/`fgt`/`flt`/`fge` comparisons combined via nested `br`/`phi`), not
dead code eliminated away — e.g. `above`'s detection compiles to:
```
v19 = phi [v16, block2], [v17, block3]   // gated "previous value" (seeded on IsInitialStep)
v20 = fle v19, v3                        // was_below = prev <= 0
v21 = fgt v16, v3                        // is_above  = current > 0
br v20, block5, block6                   // real branch, not dead code
```

## Known limitations

- ~~No persistent state inside the event body~~ — **fixed**. Writing to a
  `real`/`integer` variable inside `@(above(...))`/`@(cross(...))`'s body
  (e.g. `count = count + 1.0;`, the natural way to accumulate a crossing
  count) used to crash the compiler — a pre-existing bug, confirmed already
  present on version8's unmodified baseline with a plain `if (cond) count =
  1.0;` (no event-control involved at all). Three distinct compiler bugs
  were found and fixed chasing this (a dangling-reference bug in
  `mir_opt::simplify_cfg`'s unreachable-block removal, a multi-exit
  post-dominance bug in `mir::dominators`, and a block-merge bug in
  `mir_opt::simplify_cfg::merge_block_into_predecessor`/`mir::Layout` that
  could silently corrupt which block `mir::cursor::goto_exit()` — and
  therefore `sim_back::dae::builder::ensure_optbarriers()` — treated as the
  function's true exit) — see `../Enhancement-8.md` §2, limitation 1 for the
  full, precise root-cause writeup of all three. `above_demo.va`/
  `cross_demo.va` now demonstrate real persistent-counter accumulation (see
  above), and `verify_fix.va` in this directory is a minimal standalone
  regression test for the fix.
- **Detection is eval-granularity, not exact-time-forced.** `above`/`cross`
  detect a transition by comparing the current evaluation's value against
  the *previous evaluation's* value (the same persistence granularity
  Enhancement-7 established for ordinary variable persistence) — there is no
  breakpoint-forcing (`CKTsetBreak`) to land a timestep exactly on the
  true crossing time. In practice this means firing times land within one
  simulator timestep of the true crossing (see the `in` values at each
  firing above — close to but not exactly 0/`thresh`), not bit-exact.
- ~~An unrelated, pre-existing ngspice `.model`-card parsing quirk~~ —
  **fixed**. The *first* `param=value` pair in a multi-parameter `.model`
  override list used to be silently ignored (falling back to the `.va`'s
  declared default), while subsequent ones applied correctly. Root-caused
  and fixed in `ngspice-46/src/spicelib/parser/inpgtok.c`'s `INPgetNetTok()`
  — see `../Enhancement-8.md` §2, limitation 3. No workaround needed in
  these `.cir` files anymore.
