# Enhancement-380 — a `.dc` sweep inherited integration coefficients

A DC sweep run after `pss` returned a **45% wrong answer, silently**. After `tran`
it was 1.7% off, after `envelope` 8.8%. No warning, no error, no convergence
failure — just a different number.

## The defect

`dioload.c` gates its charge branch on

```c
if ((ckt->CKTmode & (MODEDCTRANCURVE | MODETRAN | MODEAC | MODEINITSMSIG)) || …)
```

`MODEDCTRANCURVE` is the **DC sweep**, so a charge-storing device does take that
path during a `.dc`, and it ends in `NIintegrate()`, which returns
`geq = CKTag[0] * cap`.

In a fresh session `CKTag[]` — the integration coefficients — has never been
computed. It is zero, so `geq` is zero and charge contributes nothing to a DC
sweep, which is the correct behaviour. But `CKTag[]` is plain circuit state, and
`dctrcurv.c` never initialised it. After any analysis that drives the transient
machinery — `pss` (a shooting method, so many transient cycles), `tran`,
`envelope` — it still held *that* analysis' coefficients, where `ag[0] ≈ 1/delta`
is large. The sweep then added a spurious `geq = ag[0]·cap` to every
charge-storing device.

The fix is to zero `CKTag[]` at the head of the sweep, which restores exactly the
fresh-session state.

## The measurement

A 1 kΩ/1 kΩ divider with a diode across it, where `v(mid) = V1/3` is exact:

| | v(mid) @ V1=0.5 | v(mid) @ V1=1.0 |
| --- | --- | --- |
| `dc` alone | 0.166666667 | 0.333332016 |
| after `pss` (before fix) | **0.093917448** | **0.185725364** |
| exact | 0.166666667 | 0.333333333 |

The diode's own operating point came back self-inconsistent: `gd = 2.51e-3`
against `id/(n·Vt) = 1.71e-2`, and an `id` some 3.4e7× too large for its own `vd`.

Across preceding analyses:

| preceding | before | after |
| --- | --- | --- |
| `op`, `ac`, `sp`, `hb` | 0% | 0% |
| `tran` | 1.7% | **0%** |
| `envelope` | 8.8% | **0%** |
| `pss` | 45.0% | **0%** |

## How it was found

Cross-analysis **state** fuzzing with a **numeric** oracle: for every ordered pair
of analyses, `result(B after A)` must equal `result(B alone)` — B is its own
reference, so no reference implementation is needed. Earlier rounds of that
campaign ([E-365](Enhancement-365.md), [E-366](Enhancement-366.md)) used ASan and
so could only see memory damage; this asserts the answer, and a 45% error leaves
no sanitizer trace.

The oracle needed two corrections before it was trustworthy, both worth recording:

* **First pass reported 150/196 "mismatches", all spurious.** ngspice announces the
  solver once per session ([E-266](Enhancement-266.md)), so that line appears for
  the first analysis and not the second; and console output from A and B
  interleaves across stdout/stderr, so an echoed marker does not partition the
  text. Self-consistency did not catch either, because both reference runs carried
  the *same* contamination — only the paired runs differed. Fixed by dumping each
  analysis' plot to a **file**, which cannot be interleaved.
* **Second pass: 30 mismatches**, of which 28 were `rfstab`/`qpss` not creating
  their own plot, so the probe captured the *previous* analysis' data.

That left 6 real candidates, of which 3 survived quantification.

## Two dead ends, recorded so they are not re-tried

* **`CKTmode` leaking `MODEINITSMSIG` out of PSS.** Real — PSS sets `CKTmode` in
  ~20 places and never restores it — but not the channel, because `dctrcurv.c`
  fully reassigns `CKTmode` at the head of the sweep.
* **The state-ring rotation** pulling stale `CKTstates[]` into `CKTstate0`. This
  one was *implemented and instrumented to prove it ran* — and the answer was
  unchanged. The stale value is the coefficient, not the stored charge.

A third guess, that `dcpss.c` leaves the matrix complex (it calls `spSetComplex`
five times and `spSetReal` zero times), was ruled out because `SMPluFac` and
`SMPreorder` both call `spSetReal` first. That asymmetry is still worth a look
someday, but it is not this bug.

## Verification

`examples/dcstate_examples` — 11 checks.

```
   fixed:     11/11
   pre-fix:    7/11
```

The four that fail pre-fix are the defect checks. **All seven accept checks pass
on both binaries**, which is the point of including them: this touches the DC
sweep's convergence path, so a fix that zeroed too much would break continuation.
They cover a 21-point nonlinear sweep that genuinely relies on point-to-point
continuation, a single-point sweep, a repeated sweep in one session, a nested
two-source sweep, a circuit with 100× the junction capacitance, and a plain `.op`.

Regression 303/303 → 304/304.
