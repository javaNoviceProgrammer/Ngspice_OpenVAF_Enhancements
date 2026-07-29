# Enhancement-360 — a second Verilog-A model no longer silences the first in `.disto`

A circuit containing **two or more different Verilog-A models** reported distortion
for only the last one. Every other model contributed **zero**, with no warning.

```
                          cubic branch          diode branch
cubic alone            -6.24999997503e-03            --
cubic + diode           0.000000000000e+00    -5.56159009239e-01
                        ^^^^^^^^^^^^^^^^^^ silently wrong
```

Introduced by [Enhancement-359](Enhancement-359.md) and shipped with it.

---

## Why

`DEVdisto` is dispatched **once per device type** — `cktdisto.c` walks `DEVices[]`
and calls each type's handler in turn — and every distinct `.osdi` registers as
its own device type. So a circuit using two Verilog-A models calls `OSDIdisto`
**twice for every mode**, `D_SETUP` included.

E-359 cached the numerical tensors in a single global array and cleared it at
`D_SETUP`:

```c
static OsdiNumCacheEnt *numcache;      /* one array for ALL models */
...
if (mode == D_SETUP) {
    numcache_clear();                  /* <-- wipes the PREVIOUS model */
    ...build this model's instances...
}
```

Model B's setup destroyed model A's tensors. In the mode passes, A's instance
pointers then failed the consistency check and every one of them was skipped —
so A contributed nothing at all.

The instance-pointer check is what kept this from being *wrong numbers* rather
than *no numbers*: without it, model A would have contracted model B's tensors
against A's kernels and produced confident garbage.

## The fix

The cache is keyed by descriptor, so each model only ever clears its own entries:

```c
typedef struct {
    const OsdiDescriptor *descr;
    OsdiNumCacheEnt *ent;
    uint32_t n, cap;
} OsdiNumModelCache;
```

`numcache_for(descr, create)` finds or adds the per-model cache; `numcache_reset`
drops only that model's entries. Lookup is linear in the number of *model types*,
which is a handful, not in the number of instances.

## Why the tests missed it

Every distortion test — the six E-352 checks, the seven E-353 `$limit` shapes,
and every model in the corpus campaign — used **exactly one** `.osdi`. The bug
needs two, and no test had two. Single-model coverage was thorough enough to hide
a whole-feature failure.

`examples/osdidisto_examples` gains check [7] for exactly this. It is a proven
trigger: against the pre-fix binary it reports

```
FAIL  a second OSDI model type does not silence the first
      [0.00000000e+00 alongside a diode vs 6.24999998e-03 alone]
```

The check compares the cubic branch's value **with a diode present** against the
same branch **alone**, so it fails on the silent zero rather than merely
asserting non-zero.

## Also stress-tested

- **50 instances** — exercises the cache growing past its initial capacity of 32;
  first and last instance both give the single-instance reference value.
- **Three model types, `.disto` run twice in one session** — every branch correct
  on both runs, so the per-model reset is idempotent.

## Verification

Regression 285/285. `examples/osdidisto_examples` 7/7,
`examples/limitdisto_examples` 7/7.
