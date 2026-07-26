# Enhancement-326 — a cross-namespace `Value` comparison mis-typed init cache slots (shipped SIGSEGV)

The highest-severity finding of the seven-strategy fuzz campaign. The **shipped**
compiler died with `EXC_BAD_ACCESS` inside LLVM — no diagnostic, no backtrace,
just a SIGSEGV — while compiling a legal Verilog-A model.

## Symptom

```
ASSERTIONS: LLVM verifier rejects the module
              %9  = fmul reassoc nnan ninf nsz arcp i8 %8, double %6
              %53 = trunc double %45 to i8
RELEASE:    SIGSEGV (signal 11) in llvm::detail::DoubleAPFloat::multiply
-O0:        LLVM ERROR: Do not know how to promote this operator!
```

A boolean-typed (`i8`) value was being fed straight into floating-point
arithmetic.

## Root cause — index collision across two `Value` namespaces

Not a missing cast, not autodiff, not `casex`. A `mir::Value` is a bare `u32`
index, and two independent functions (the *main* function and the *init* function)
each number their values from zero.

`sim_back/src/init.rs`, producer — inserts **init-function** values, correctly, for
its other consumer `optimize()` which runs DCE over `self.init.func`:

```rust
if let Some(&val) = self.val_map.get(&val) {   // main -> init
    collapse_implicit.insert(val);
```

Consumer — `build_init_cache` iterates `self.init_cache`, whose keys are
**main-function** values, and tested them against that init-namespace set:

```rust
} else if collapse_implicit.contains(&val) {   // main index vs init-namespace set
    Type::Bool
} else {
    Type::Real
};
```

Comparing indices across namespaces cannot fail loudly — it silently succeeds
whenever the two counters **coincide**. Verified under lldb on the minimized
reproducer: the producer inserted init `Value(25)` (the `idt` collapse flag, a
genuine `Bool`), while the consumer tested main `Value(25)` — which is
`abs(p)`, the *noise power*, a `Real`. Same number, unrelated values.

## How the wrong type becomes a SIGSEGV

`Type::Bool` lowers to `ty_c_bool()` = **i8**:

- **store side** — `store_cache_slot` int-casts a slot it believes is boolean,
  emitting `trunc double .. to i8`;
- **read side** — the noise loader reads `EvalOutput::Cache` **raw**, with the
  slot type and (unlike `load_cache_slot`) no bool normalization, so an `i8`
  becomes `base_pwr` and lands in `fmul i8 %x, double %y`.

LLVM then constant-folds that malformed `fmul` and reads the `i8` as an
`APFloat` — the `EXC_BAD_ACCESS`.

## The fix

Map through `val_map` before the lookup, so both sides speak the same namespace:

```rust
let is_collapse_flag =
    self.val_map.get(&val).map_or(false, |v| collapse_implicit.contains(v));
```

used at both sites (the type selection, and the dead-value filter above it).

## Why it resisted minimization

The trigger is a *numeric coincidence*, so the reproducer is fragile in a way that
looks arbitrary: deleting even a dead `r2 = 0.0;` shifts one counter and the crash
disappears. The original fuzz output was 917 bytes; ablation reduced it to 250
bytes and showed the flashy ingredients (`casex` with an `x` pattern, `hypot`,
`cosh`, nested `while`/`for`, `$temperature`) were all irrelevant. What is actually
required:

1. a noise source whose **power** is an op-independent **non-parameter** expression
   — only then does it occupy a *cache slot* (a bare parameter takes
   `EvalOutput::Param`, a literal `EvalOutput::Const`, both of which dodge the bug);
2. an analog operator creating an **implicit equation** (`idt`/`idtmod`/assigned
   `ddt`) — the source of the `Bool` collapse flag;
3. under a **parameter-only, non-constant** condition, so the flag is a runtime
   `phi[FALSE,TRUE]` rather than a folded constant;
4. the noise **live in a contribution**;
5. plus the index coincidence itself.

## Output preservation

Where the old and new lookups differ, the old behaviour always produced **invalid
IR** — an `f64` slot typed `Bool` yields `trunc double → i8` on store and a raw
`i8` into float ops on load, which fails the LLVM verifier in debug and
crashes/miscompiles in release at every `-O` level. There is therefore no input
for which the previous behaviour was a working `.osdi`, so the fix cannot regress
a working model.

Confirmed empirically with the deterministic `--dump-mir` oracle over the
466-model corpus: **byte-identical everywhere**. (The single reported diff,
`lrm_examples/va/lrm_p150_1.va`, was independently proven to be run-to-run
nondeterminism of the multi-module dump order — the same binary produces both
hashes on the same input.)

## Files

- `OpenVAF-master-20260610/openvaf/sim_back/src/init.rs` — the mapped lookup at
  both sites.
- `examples/vafinitcache_examples/` — the 250-byte crash reproducer plus a
  noise-observable variant whose `onoise_total` is checked against the closed form
  `sqrt(P·R²·BW)`, which only holds if the cache slot is read as a real
  (`verify_vafinitcache.py`, 4 checks).
