# Enhancement-369 — closing the E-365/366 stale-binding class

[Enhancement-366](Enhancement-366.md) fixed two sites of this class and left a
third **open on purpose**, with the reason recorded: it could not be closed with
another guard, because the binding was *not NULL but stale* and no NULL test can
tell those apart. This closes it, by fixing the thing that made it stale.

---

## The asymmetry is the bug

`VSRCbindCSC` assigns the pole-zero binding only **inside** a gate:

```c
/* Pole-Zero Analysis */
if (here->VSRCibrIbrPtr)
{
    ...
    here->VSRCibrIbrBinding = matched ;
    if (matched != NULL)
        here->VSRCibrIbrPtr = matched->CSC ;
}
```

and `VSRCibrIbrPtr` is allocated **only by a pole-zero analysis**. So on any
later analysis that test is false, the assignment never happens, and the binding
keeps its previous value — pointing into the `BindStruct` that `SMPdestroy()`
freed when the pz matrix went away.

Both consumers then dereference it:

```c
/* VSRCbindCSCComplex and VSRCbindCSCComplexToReal */
if ((here->VSRCbranch != 0) && (here->VSRCbranch != 0))   /* note the duplicate */
    if (here->VSRCibrIbrBinding)
        here->VSRCibrIbrPtr = here->VSRCibrIbrBinding->CSC_Complex ;
```

because **their** guard is `VSRCbranch != 0` — a property of the device — rather
than *"was this binding re-established for **this** matrix"*. Two different
questions, and only the second one is the right one.

Reproduced with `option klu ; pz ; ac`:

```
ERROR: AddressSanitizer: heap-use-after-free
READ of size 8 in VSRCbindCSCComplex vsrcbindCSC.c
  freed by       SMPdestroy klusmp.c
  reallocated by SMPconvertCOOtoCSC klusmp.c
```

## The fix

Clear the binding **before** the gate, so a stale value can never survive a
matrix rebuild:

```c
here->VSRCibrIbrBinding = NULL ;
if (here->VSRCibrIbrPtr)
{
    ...
}
```

One line, and it fixes both consumers at once because both test the binding for
NULL. The duplicated `(x != 0) && (x != 0)` condition — a copy-paste slip — is
collapsed to a single test in the same pass.

### Why no other device needs this

`vsrc` is the only device that hand-writes a pole-zero binding block; a grep for
`"Pole-Zero Analysis"` across every `*bindCSC.c` returns exactly one file. Every
other binding goes through the shared macros in `klu-binding.h`, and those are
**self-consistent**: `CREATE_KLU_BINDING_TABLE` and
`CONVERT_KLU_BINDING_TABLE_TO_COMPLEX` are gated on the *same* condition
(`here->a > 0 && here->b > 0`), so if the create is skipped the convert is
skipped too. It is precisely the hand-written block, with its two mismatched
guards, that could go stale.

## Verification, and an honest limit

`examples/klubind_examples` checks that after a `pz`, every AC-family analysis
under KLU produces the same answer it produces without the `pz`, and the same
answer Sparse produces — with the Sparse rows as controls that the default solver
did not move.

**The pre-fix binary passes all of those.** The freed `BindStruct` entry still
held the right `CSC_Complex` pointer, so the use-after-free read plausible values
and the numbers came out correct. That was tested deliberately rather than
assumed: a 40-node ladder with a `tran` between the `pz` and the `ac` to churn
the heap still produced Sparse-identical results.

So this is a **memory-safety** fix, not a wrong-answer fix, and the behavioural
checks are a regression guard rather than a reproducer. The check that actually
discriminates runs the deck under a sanitizer:

```
   fixed:        8/8   (ASan: no sanitizer report)
   pre-fix:      7/7 behavioural + ASan: heap-use-after-free
```

The example runs that last check when `NGSPICE_ASAN` points at an ASan build and
**skips it loudly** otherwise, so nobody mistakes a 7/7 for proof of the fix.

Undefined behaviour that happens to produce the right answer today is still
undefined behaviour: the same read against recycled memory is a wrong answer or a
crash, which is exactly how E-365 presented (2.5 % wrong, silently).

Regression 294/294.
