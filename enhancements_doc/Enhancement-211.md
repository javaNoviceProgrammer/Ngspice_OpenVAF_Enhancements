# Enhancement-211 — code-analysis bug fixes (XSPICE DC-op else + LTSPICE table free)

A static-analysis pass over the ngspice tree (clang's analyzer on every
project-modified file, each finding then confirmed by reading the code) surfaced two
real defects. Both are fixed here.

## Bug 1 — mixed-signal DC operating point runs the analog solve twice

`DCop()` (`src/spicelib/analysis/dcop.c`) chooses between the event-driven XSPICE
solver and the analog solver with a **braceless** `else`:

```c
    if (ckt->evt->counts.num_insts != 0) {      /* event-driven instances present */
        converged = EVTop(...);  ...
    } else
        converged = CKTop(...);                 /* ORIGINAL: analog solve, else-only */
```

[Enhancement-188](Enhancement-188.md) (DC warm-start) inserted its preload code
**between** the `else` and `CKTop`. Because the `else` had no braces, it then
covered only its first statement (`wsize = SMPmatSize(...)`), and everything after —
including `converged = CKTop(...)` — ran **unconditionally**. Consequences, with
`XSPICE` compiled (it is):

- For any deck with **event-driven code-model instances** (A-devices), both `EVTop`
  *and* `CKTop` ran; `CKTop` re-solved the analog part and overwrote the
  event-driven DC result. The original ran exactly one of the two.
- `wsize` was **read uninitialised** at two later points (the warm-start guard and
  snapshot) on the EVTop path, where the `else` body that assigns it was skipped —
  undefined behaviour, masked today only because DC warm-start is off by default.

**Fix:** hoist `wsize = SMPmatSize(...)` above the branch (always initialised, and
the warm-start snapshot below needs it on both paths), and add braces so the `else`
covers the warm-start preload and `CKTop` — restoring the original "exactly one
solve" semantics. The `#ifdef XSPICE` braces vanish together when XSPICE is off, so
the non-XSPICE build is unchanged.

## Bug 2 — free of an uninitialised pointer on LTSPICE single-pair table import

`inp_compat()` (`src/frontend/inpcom.c`) converts an LTSPICE `E ... table=(...)`
controlled source using `char *ckt_array[100]` — an **uninitialised** stack array.
The LTSPICE branch sets only `ckt_array[1]`; a **single-pair** table
(`table=(x0, y0)`, `ipairs == 1`) then does `tfree(ckt_array[2])` — a free of a
garbage stack pointer (`ckt_array[2]` is set only on the *other*, non-LTSPICE,
branch). Undefined behaviour; a likely crash on malformed/degenerate input.

**Fix:** zero-initialise the array (`char *ckt_array[100] = { NULL };`). ngspice's
`tfree(NULL)` is a safe no-op (`txfree` guards `if (ptr)`), so a `tfree` of any slot
not written on a given branch does nothing instead of freeing garbage.

## Verification

New suite [`examples/codeanalysis_examples/verify_codeanalysis.py`](../examples/codeanalysis_examples/verify_codeanalysis.py)
(5 checks × both solvers) exercises the fixed paths: a mixed-signal DC op (an
analog divider + an `adc_bridge`, an event-driven instance) solves the analog node
to the correct 0.5 V without error; a single-pair LTSPICE `E ... table=(0.5, 3)`
imports and yields the constant 3 V; and a plain analog DC op is unchanged. A
would-fail before/after test is impractical for either bug (the redundant `CKTop`
leaves a simple circuit's DC point unchanged, and freeing a garbage pointer is UB
that may or may not crash), so these are behavior guards. Full regression: 171/171.

## Scope

ngspice-only, two files (`dcop.c`, `inpcom.c`). No functional change to correct
analog decks; the fixes remove undefined behaviour and a double analog solve on the
XSPICE and LTSPICE-import paths respectively.
