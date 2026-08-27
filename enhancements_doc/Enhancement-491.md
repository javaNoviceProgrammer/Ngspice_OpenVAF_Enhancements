# Enhancement-491 — an unbounded number used as a length, and four wrong ones

**Files:** `src/misc/printnum.c`, `src/misc/printnum.h`,
`src/include/ngspice/cpstd.h`, `src/xspice/evt/evtprint.c`,
`src/spicelib/parser/ptfuncs.c`, `src/spicelib/parser/inpptree.c`,
`src/spicelib/analysis/cktsens.c`, `src/frontend/measure.c`,
`src/frontend/device.c`, `src/frontend/inpcom.c`,
`src/xspice/icm/analog/s_xfer/cfunc.mod`, plus the 18 `printnum()` call sites in
`frontend/{diff,dotcards,postcoms}.c`.

**Suite:** `examples/numguard_examples/` — 68 checks.

## Why

Round 51 found ten defects sharing one shape: **a number the deck supplies was
used without being measured against what it was about to control.**

## The crashes

`set numdgt=<n>` is the user's print precision, and nothing bounded it.
`printnum()` formatted with `sprintf(buf, "%.*e", cp_numdgt, num)` into caller
buffers of `BSIZE_SP` (512); `evtprint.c` formatted into a `char[100]`. Both
thresholds land exactly where the arithmetic says they must — `%.*e` needs
`n + 9` bytes:

| command | buffer | crashes at | signal |
|---|---|---|---|
| `print`, `.print` card | 512 | **510** | SIGABRT |
| `eprint` | 100 | **94** | SIGTRAP |

Both are reachable from a plain batch deck with no interactivity. `numdgt=94` is
an entirely ordinary "give me lots of digits" value.

`printnum()`'s **own comment had recorded the hazard** —

> *"This funtion writes num to buf. It can cause buffer overruns. The size of buf
> is unknown, so cp_numdgt can be large enough to cause sprintf() to write past
> the end of the array."*

— without bounding it. The safe sibling `printnum_ds()` sits directly below it
and cannot overflow, which is exactly why `fourier`, `wrdata`, `write`,
`display` and `diff` were unaffected while only the `print` family crashed.

`printnum()` now takes the buffer's size, and the precision is **clamped to what
fits** rather than truncated: `snprintf` alone would stop mid-number and hand the
reader a value that is not the one computed. Beyond ~17 significant digits the
extra places are zero padding anyway, so a clamped column is the same number,
just narrower — and it says so once. `evtprint` uses the same clamp, so the two
printing paths cannot disagree about how wide a number may be.

Both sites trace by `git -S` to `4f29ffad`, the vanilla upstream import.

## The wrong numbers

**A divisor was perturbed whether or not it needed to be.** `PTdivide` added
`PTfudge_factor` to *every* divisor. That factor is `gmin * 1e-20`, so it was not
even a fixed perturbation — it scaled with an unrelated convergence option:

| | default | `gmin=1e-6` | `gmin=1e-3` | `gmin=1e-2` |
|---|---|---|---|---|
| `1/boltz` error | 7e-10 | 0.07% | **42%** | **88%** |

`.option gmin=1e-3` is a routine convergence aid and 1.38e-23 is Boltzmann's
constant. `1/0` likewise returned 1e26, 1e32 or 1e50 depending on gmin alone.
The nudge now applies **only to an exact zero**, and uses a fixed epsilon rather
than a gmin-derived one, so a non-zero divisor is used as written and `1/0` is
the same number in every deck. The value keeps the default gmin's `1e-32`, so no
deck that was already correct changes.

**The trig range reduction was undefined and less accurate than the libm it fed.**
`MODULUS(x, 2π) = x − (int)(x/2π)·2π` overflows a signed int above 2³¹·2π
(≈1.35e10):

| x | B-source | numparam | Verilog-A | libm |
|---|---|---|---|---|
| 1e15 | 0.86395 | 0.858273 | 0.858273 | 0.858273 |
| 1e20 | **+0.99932** | −0.645251 | −0.645251 | −0.645251 |

Both other evaluators in this simulator were already right, so the B-source was
the **sole outlier** — precisely the divergence Enhancement-399 forbids, quoted
in `ptfuncs.c`'s own comment. libm reduces correctly for every finite double, so
the macro is gone.

## The silent refusals

* **A `sens` filter that matched nothing** produced no plot and said nothing,
  returning `OK` and leaving the previous analysis current for a following
  `print`. The trailing words on a `sens` line are filter patterns — `sens v(b)
  r8` is a legitimate restriction and works — so a mistyped filter was
  indistinguishable from one that did its job. It now names the patterns that
  missed and how a parameter name is spelled.
* **`meas` enforced its analysis keyword for interval measurements and ignored
  it for point ones.** Enhancement-468 restored the interval half; the point half
  never reached that check, so `meas tran m FIND v(n) AT=0.5` read a DC sweep as
  a transient. One keyword, enforced for `avg`/`rms`/`max`/`min`/`integ` and
  ignored for `find`/`when`. The check now runs once for every measurement type,
  in the command only — the `.meas` card already gated correctly.
* **`s_xfer` blamed the solver for a model error.** An all-zero denominator went
  NaN and was reported as *"Dynamic gmin stepping failed"*; a numerator longer
  than the denominator was detected, announced **once per evaluation** (1238
  times over 300 steps), and then the run returned rc=0 with the device
  contributing nothing. Both are knowable from the parameters before any solve.
* **`printf("oops ")`** reached users on **stdout** from two `default:` arms in
  `inpptree.c` — one of them the very printer the *"internal check of parse tree
  … failed"* diagnostic uses to show the offending expression, so that message
  rendered as the word `oops`. Reachable from `.param p={ln(0)}`.
* **`show <dev> : <bogus>`** printed `?????????` where `print`, `alter`,
  `altermod`, `wrdata` and `sweep` all name the parameter.
* **A duplicate user `.func`** was silently last-wins while shadowing a *builtin*
  warned (Enhancement-467). Two includes each defining a helper displaced one
  another unannounced.

## One comment corrected rather than obeyed

Enhancement-440's comment claimed the singular-value routes "clamp to HUGE" and
that clamping "keeps the Jacobian finite, which is what lets NIiter reach for
gmin or source stepping". Neither is what the code does: `PTeval` in `ifeval.c`
treats a result equal to `HUGE` as an **error flag**, returning `E_PARMVAL` and
aborting — the opposite of continuing. And the routes were never uniform:
`sqrt(-1)` and `pwr(0,-1)` abort, `log(0)` returns `-1e99` and runs on, and
`PTdivide` no longer reaches `HUGE` at all.

Recorded rather than unified: making `log(0)` abort, or `pow(0,-1)` not abort,
would each change the answer a working deck gets today. What was wrong was the
description, and a reader trusting it would have drawn exactly the wrong
conclusion about which of these keeps a simulation alive.

## What this deliberately does not change

* **Ordinary precisions.** `numdgt` of 6, 12 or 17 formats exactly as before;
  only a value that cannot fit its field is narrowed, and only then is anything
  said.
* **`1/0` still returns a large finite number** and the solve continues — the
  same 1e32 the default gmin produced.
* **Interval measurements** keep E-468's behaviour untouched.
* **A `sens` run with no filter, or a filter that matches**, is unchanged.
* **`.func` resolution** still takes the last definition; only the silence is
  gone.

## Verification

```
python3 examples/numguard_examples/verify_numguard.py    # 68/68
python3 examples/mathguard_examples/verify_mathguard.py  # 57/57
python3 examples/run_regression.py                       # 405/405
```

**18/68** against the pre-fix binary, so **50 of 68 checks discriminate**; the
other eighteen are controls that must not move, and do not.

## The fix's own trap

The first version of the `meas` gate refused **before** the standard failure
path. That skipped two things at once: the ` meas ... failed!` line a script
tests on, and Enhancement-475's `vec_remove(outvar)`, which exists so a failed
measurement leaves no stale value for the next read. So a refusal would have
reintroduced exactly the defect E-475 was written to prevent.

`mathguard_examples` caught it — check [4], *"`meas dc` refuses a TRAN plot again
(E-467 let it measure one)"*, asserts `num(o,"d1") is None and "failed" in o`.
The suite was right and the fix was wrong: refusing is correct, but refusing
*differently* broke a contract two earlier enhancements had established. The gate
now refuses the way every other refused measurement does.
