# Enhancement-365 — `pz` left the device matrix bindings dangling, so a following `hb` was wrong

Running `pz` and then `hb` in one session produced a **silently wrong**
harmonic-balance result — and, underneath it, a heap use-after-free.

```
V1 in 0 dc 0.5 ac 1 portnum 1 z0 50
R1 in mid 1k
R2 mid 0 1k
C1 mid 0 1n
D1 mid 0 dm
.model dm d(is=1e-14 n=1 cjo=1p)
.control
  pz in 0 mid 0 vol pz
  hb 1meg 3
.endc
```

| | DC term of `v(mid)` |
|---|---|
| `hb` alone (correct) | 2.4390237511e-01 |
| `pz` then `hb` — fixed | 2.4390237511e-01 ✓ |
| `pz` then `hb` — before | 2.4999992105e-01 ✗ **2.5 % wrong** |

---

## How it was found: fuzzing the SEQUENCE, not the input

Every previous campaign in this project fuzzed the **input** — netlists
([E-222](Enhancement-222.md)), XSPICE model cards
([E-223](Enhancement-223.md)), commands and expressions
([E-225](Enhancement-225.md)), rawfiles ([E-226](Enhancement-226.md)), `.snp`
([E-227](Enhancement-227.md)), the OSDI loader
([E-228](Enhancement-228.md)), analysis-card parameters
([E-362](Enhancement-362.md)). Each input runs in a fresh process, so **none of
them can reach a bug that lives in what one analysis leaves behind for the
next**.

This campaign held the netlist fixed and valid and fuzzed the *order* of
analyses and state mutators inside one session. 500 iterations against an
ASan build produced 4 sanitizer reports — all four the same root cause, every
sequence containing `pz` immediately followed by `hb`.

The precedent for the class is [E-360](Enhancement-360.md): a second Verilog-A
model silenced the first in `.disto`, because the tensor cache was global while
`DEVdisto` dispatches per device *type*. Nothing was wrong with either deck
alone.

## The bug

`CKTpzSetup` (`cktpzset.c`) opens with

```c
NIdestroy(ckt);        /* frees ckt->CKTmatrix ...        */
error = NIinit(ckt);   /* ... and builds a DIFFERENT one  */
```

while leaving `CKTisSetup` asserted. Every device's cached matrix-element
pointer — bound by `CKTsetup` into the *old* matrix — is now dangling.

`com_hb` then guarded its own setup with

```c
if (ckt->CKTmatrix == NULL || SMPmatSize(ckt->CKTmatrix) <= 0)   /* → CKTsetup */
```

which asks **"is there a matrix?"** — and after a `pz` there is a perfectly
good, non-empty one. So `CKTsetup` was skipped and `CKTload` read every device's
stale pointer:

```
READ of size 8 at ... vsrcload.c:60 in VSRCload
   #1 CKTload cktload.c:75   #2 HBanalyze dcpss.c:1718   #3 com_hb com_hb.c:146
freed by:
   #1 spDestroy spalloc.c:687   #2 NIdestroy nidest.c:20
   #3 CKTpzSetup cktpzset.c:27  #4 PZan pzan.c:68
```

On an ordinary build there is no crash — just the wrong number above. This is
the class only a sanitizer surfaces, and it had survived every prior campaign.

## Scope — measured, not assumed

Only this pair is affected:

- `pz` followed by `op`, `dc`, `ac`, `tran`, `noise`, `disto`, `tf`, `sp` or
  `pss` — **clean**.
- `hb` after `op`, `ac`, `tran`, `sp`, `disto`, `sens`, `tf`, or nothing —
  **clean**.

`portnum` on the source matters only because it lets `hb` get far enough to load
the circuit; it is not part of the cause. Two intermediate readings during
triage were wrong and are worth recording: the bug is **not** confined to a
*failing* `pz` (the success path corrupts identically — an early negative came
from a test circuit that had lost its `portnum`), and the first "pz then X"
sweep looked clean for the same reason.

## The fix

`pz` now records that it invalidated the bindings, and `com_hb` honours it:

- `cktdefs.h` — a new `CKTbindStale` flag: *an analysis has replaced
  `ckt->CKTmatrix` while leaving `CKTisSetup` asserted.*
- `cktpzset.c` — sets it next to the `NIdestroy`/`NIinit` pair.
- `cktsetup.c` — clears it on a successful setup, which is exactly what makes
  the bindings valid again.
- `com_hb.c` — when the flag is set, rebinds with a **balanced**
  `CKTunsetup()`/`CKTsetup()` pair.

The balanced pair matters. A bare `CKTsetup()` returns `E_NOCHANGE` because
`CKTisSetup` is still 1, so it would fix nothing; and calling it *without* the
unsetup would re-run `DEVsetup` on already-setup devices and double-allocate
their internal nodes — which is what `CKTunsetup`'s `prev_CKTlastNode`
consistency check exists to catch.

Nothing changes for any circuit that never runs `pz`: the flag starts clear and
only `CKTpzSetup` sets it.

## Verification

`examples/pzhb_examples` is a **proven trigger** and needs no sanitizer, because
the consequence is a number: `hb` after `pz` must equal `hb` alone, since `pz`
does not change the circuit.

```
   fixed:  4/4      hb after pz equals hb alone   max dev 0.00e+00
   before: 2/4      hb after pz equals hb alone   max dev 4.55e-02
                    pz then hb twice              dc 2.549974e-01 vs 2.439024e-01
```

It also pins that `pz`'s own pole is unchanged and that `op`/`ac`/`tran` after a
`pz` stay identical, so the fix cannot have moved anything that was already
right.

The sequence fuzzer lives in `examples/pzhb_examples/fuzz/`, committed so the
search is repeatable but excluded from the regression by name (it wants a
sanitizer build to be worth running).

Regression 289/289.
