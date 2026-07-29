# Enhancement-366 — two more sites of the E-365 stale-binding class

[Enhancement-365](Enhancement-365.md) fixed `pz` followed by `hb`. Continuing the
**same** sequence-fuzzing campaign against the **fixed** build found two more
places the same root cause reaches, one of them a NULL check that did not guard
anything.

---

## Continuing the campaign is what found them

E-365's campaign ran 500 iterations with a modest command pool. Widening it —
the RF/steady-state commands (`stb`, `rfstab`, `envelope`, `qpss`), the workflow
commands (`sweep`, `wcd`), and **solver switching** (`option klu` /
`option sparse`) between analyses — took the yield from **500 iterations / 1
signature** to **700 / 3**.

Solver switching was added deliberately: KLU and SPARSE keep *separate*
per-instance matrix-pointer sets, so flipping between them across analyses is
the same shape of hazard as E-365 — state established for one backend, used by
the other.

## 1. `pz` then `qpss` — the site E-365 missed

`com_qpss.c` carried the identical guard `com_hb.c` had:

```c
if (ckt->CKTmatrix == NULL || SMPmatSize(ckt->CKTmatrix) <= 0)   /* → CKTsetup */
```

which asks *"is there a matrix?"* when the question is *"do the device bindings
point into it"*. After a `pz` there **is** a good matrix, so `CKTsetup` was
skipped and `CKTload` read freed memory.

Same fix as E-365: honour `CKTbindStale` with a **balanced**
`CKTunsetup()`/`CKTsetup()` pair. Verified — sanitizer reports 1 → 0, and `qpss`
after a `pz` now returns the same answer as `qpss` alone (before, it produced no
result at all).

`com_checkpoint.c` also matches a grep for `SMPmatSize(ckt->CKTmatrix)` but only
uses it to size a buffer, so it is not affected.

## 2. A NULL check that reported the NULL and then dereferenced it

`CREATE_KLU_BINDING_TABLE` in `klu-binding.h`:

```c
matched = bsearch (&i, BindStruct, nz, sizeof (BindElement), BindCompare);
if (matched == NULL) {
    printf ("Ptr %p not found in BindStruct Table\n", here->ptr);   /* reports it ... */
}
here->binding = matched;
here->ptr = matched->CSC;        /* ... and then dereferences it */
```

Every lookup miss was undefined behaviour — and silent on an ordinary build.
UBSan: *member access within null pointer of type 'BindElement'*.

It is reachable from an ordinary sequence: `option klu` + `pz` + any AC-family
analysis (`ac`, `sp`, `stb`) misses, because `pz` rebuilds `ckt->CKTmatrix` and
the device's COO pointer is no longer in the new matrix's bind table. SPARSE is
unaffected — the binding tables are a KLU construct.

The companion `CONVERT_KLU_BINDING_TABLE_TO_COMPLEX` / `_TO_REAL` macros then
dereferenced the same unresolved binding. Both are now guarded, and a miss sets
`binding` to NULL rather than leaving the previous (freed) value — leaving it
stale would have turned a NULL dereference into a use-after-free, which is
strictly worse.

The macro is in a shared header, so this fixes every device that uses it, not
just `vsrc`.

## Still open, and deliberately not papered over

Under KLU, the pole-zero block at the end of `VSRCbindCSCComplex` reads

```c
if (here->VSRCibrIbrBinding)
    here->VSRCibrIbrPtr = here->VSRCibrIbrBinding->CSC_Complex;
```

through a binding that is **not NULL but stale**: `CREATE_KLU_BINDING_TABLE` is
skipped for that entry (its `branch > 0` precondition), so the pre-`pz` value
survives and the NULL test passes. ASan still reports a use-after-free for
`option klu ; pz ; ac`.

This one needs the bindings **torn down** when `pz` rebuilds the matrix. It
cannot be fixed with another guard, because a guard cannot distinguish a stale
pointer from a live one — which is exactly why it is left open rather than
patched. A central rebind in `CKTdoJob` was tried and **reverted**: tracing
showed `CKTbindStale` is already clear by the time the following analysis is
dispatched, so the check fixed nothing, and a guard that fixes nothing is worse
than no guard.

The campaign went from **3 distinct findings to 1** with the two fixes above.

## Verification

`examples/pzklu_examples` needs no sanitizer — it checks what an ordinary build
can see: each analysis must still produce its normal answer, and `qpss` after a
`pz` must equal `qpss` alone.

```
   fixed:        4/4
   pre-fix bin:  1/4    qpss after pz          no spectrum (alone=16 after=0)
                        KLU: ac after pz       alone=7 after=0
                        KLU: sp after pz       alone=3 after=0
                        SPARSE: ac after pz    PASSES on both -- never affected
```

The SPARSE row is the control: it passes before and after, which is what shows
the KLU fixes did not change the unaffected path.

The widened sequence fuzzer is in `examples/pzklu_examples/fuzz/`, committed for
repeatability and excluded from the regression by name.

Regression 290/290.
