# Init cache-slot typing (Enhancement-326)

A `mir::Value` is a bare `u32` index. `sim_back`'s `build_init_itern` inserts
**init-function** values into `collapse_implicit` (it stores `val_map[&val]`), but
`build_init_cache` tested **main-function** values against that same set. Comparing
indices across two independent namespaces does not fail loudly — it silently
succeeds whenever the two counters happen to **collide**.

On a collision the slot's recorded `hir::Type` was wrong: an `f64` cache slot was
stamped `Type::Bool`, which lowers to `i8`. The store side then emitted
`trunc double .. to i8`, and the noise loader read the slot back as a **raw i8**
straight into `fmul i8 %x, double %y`. The assertions build's LLVM verifier
rejected that IR; the **shipped** release carried it into LLVM and died with
`EXC_BAD_ACCESS` inside `DoubleAPFloat::multiply` — a SIGSEGV, no diagnostic.

Because the trigger is a numeric coincidence between two value counters, the
original 917-byte fuzz reproducer resisted line-by-line minimization: deleting even
a dead statement shifted an index and made the crash vanish. That is why
`initcache.va` keeps two apparently pointless filler statements.

## Ingredients (each verified essential by ablation)

1. a noise source whose **power** is an op-independent, **non-parameter** expression
   — it must land in a *cache slot* (`EvalOutput::Cache`); a bare parameter takes
   `EvalOutput::Param` and a literal takes `EvalOutput::Const`, both of which dodge
   the bug;
2. an analog operator that creates an **implicit equation** (`idt`, `idtmod`, or a
   variable-assigned `ddt`) — this produces the `Bool`-typed collapse flag;
3. that operator under a **parameter-only, non-constant** condition, so the flag is
   a runtime `phi[FALSE,TRUE]` rather than a folded constant;
4. the noise **live in a contribution**.

`casex`, `hypot`, `cosh`, nested loops and `$temperature` — all present in the
original fuzz output — were ablated away as irrelevant.

## Files

- `initcache.va` — the minimized crash reproducer (250 bytes). Compiling it with
  the pre-fix binary is a SIGSEGV.
- `initcache_noise.va` — the same ingredients with the noise left observable, so
  the value that flowed through the mis-typed slot can be checked numerically.
- `verify_vafinitcache.py` — 4 checks: it compiles, the module is valid IR, it
  simulates to a finite operating point, and the cache-slot noise **power** reads
  back as a real (`onoise_total` matches the closed form `sqrt(P·R²·BW)` to 0.02 %,
  which it cannot if the power is read as an `i8`).

## Run

```
python3 verify_vafinitcache.py
```
