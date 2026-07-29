# Enhancement-370 — `.pz` re-expanded the URC subcircuit, overflowing the RHS

Found by running an **existing regression fixture** under a sanitizer. A sweep of
every shipped deck with each solver forced in turn produced exactly one real
finding, and it was in `examples/ngcrashanalysis_examples/pz_urc.cir` — the
[Enhancement-315](Enhancement-315.md) fixture, which has been passing ever since
E-315 stopped it SIGSEGVing.

Nothing had ever run that deck under a sanitizer. The crash was gone; the memory
corruption underneath was not.

---

## What the sanitizer saw

```
ERROR: AddressSanitizer: heap-buffer-overflow
READ of size 8 in RESload resload.c
  CKTload -> NIiter -> CKTop -> PZan
  buffer allocated by NIreinit nireinit.c
```

`RESload` indexes the RHS by node number:

```c
here->REScurrent = (*(ckt->CKTrhsOld + here->RESposNode) -
                    *(ckt->CKTrhsOld + here->RESnegNode)) * here->RESconduct;
```

so a read past the end means a resistor's node number exceeded the RHS the solver
had allocated.

## The cause: an expander wired into the pz path

The URC device declared

```c
.DEVsetup   = URCsetup,
.DEVpzSetup = URCsetup,      /* <-- the same function */
```

but `URCsetup` is not a matrix-entry allocator like its neighbours — it is a
**subcircuit expander**. It calls `CKTmkVolt` per lump and `CKTcrtElt` per
element, and it has **no idempotency guard**.

`CKTpzSetup` calls `DEVpzSetup` for every device on **every** pz job. So each
`.pz` expanded the URC again, creating fresh internal nodes *after* `NIinit` had
already sized the RHS for the previous node count. The resistors of the newly
created lump then indexed past `CKTrhsOld`.

This is exactly why `RESsetup` and `CAPsetup` are safe in the same slot and
`URCsetup` is not: they only allocate matrix entries, which is idempotent. URC
was the only expander wired up this way.

The duplicate expansion had a visible symptom too, which is what confirms the
mechanism on an ordinary build:

```
doAnalyses: device already exists, existing one being used
run simulation(s) aborted
```

Even a **single** `.pz` triggered it — `CKTsetup` expands once and `CKTpzSetup`
expanded again — the overflow just took a second pass to cross the allocation
boundary.

## The fix

The URC needs no pz setup at all. Its `DEVload`, `DEVacLoad` and `DEVpzLoad` are
**all NULL**: it stamps nothing itself. The RES/CAP instances it creates are
ordinary circuit elements registered under their own device types, and
`CKTpzSetup` calls `RESsetup`/`CAPsetup` for them — which is what actually
re-binds the matrix after the pz matrix is rebuilt.

```c
.DEVpzSetup = NULL,
```

## Not a solver bug

It was found during a KLU/Sparse hunt and reproduces **identically under both
solvers**, so it belongs to neither. Worth stating, because the fixture lives in
a directory of solver-adjacent crashes and the obvious inference would be wrong.

## Verification

`examples/urcpz_examples` needs no sanitizer: it checks that the
duplicate-expansion warning is gone for 1–3 repeated `.pz` runs and for 1/4/8
lumps, that the analysis now **reaches the solver** instead of aborting during
setup, and that a properly terminated URC still solves normally under `op`, `ac`
and `tran` on both solvers.

```
   fixed:        10/10
   pre-fix:       5/10   1/2/3 x .pz          'device already exists'
                         n=1/4/8 lumps        'device already exists'
                         reaches the solver   aborted in setup
```

One behavioural change is worth noting rather than hiding. On the E-315 fixture
the fixed build now gets *further*: instead of aborting on a spurious duplicate
device, it runs the analysis and reports

```
Warning: singular matrix:  check node 3
```

which is **correct** — that fixture's node 3 is genuinely floating (the URC's far
end is unterminated). The duplicate expansion had been masking a real topology
diagnostic behind a spurious one. `verify_ngcrashanalysis.py` still passes 4/4,
because what it checks is that the deck does not crash.

Regression 294/294.
