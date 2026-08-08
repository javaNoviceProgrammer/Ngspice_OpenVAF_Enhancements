# Enhancement-418 — three things nobody checked

Three defects that share a shape: something was accepted, or counted, or
concluded, and never verified.

## 1. An operator whose value was structurally zero

`absdelay()` and `last_crossing()` read **0.0** whenever their result was only
*observed* rather than contributed to a branch. Enhancement-415 found this,
looked for it in the compiler, and reverted its attempt when the emitted
descriptor came out byte-identical. It was right to revert: nothing was ever
wrong in the descriptor.

These two are the only analog operators whose **output row the compiler
deliberately leaves empty**. OpenVAF emits no residual for it because *ngspice*
fills that row, from its own history buffer, in `absdelay_stamp_tran()` /
`last_crossing_stamp()` — through matrix elements `OSDIsetup` allocates later.
So the output node appears in no descriptor Jacobian entry, and
Enhancement-116's decoupled-node scan — which can only see coupling the
*compiler* declared — concluded it was structurally decoupled and tied it to
ground. `eval()` then read `CKTrhsOld[0]`: exactly 0.0, forever.

That explains every observation exactly:

| how the value is used | before | after |
| --- | --- | --- |
| never used again | **0.0** | 0.9 ✓ |
| live only in an `if` condition | **0.0** | 0.9 ✓ |
| live only via another opvar | **0.0** | 0.9 ✓ |
| contributed (even at weight 1e-30) | 0.9 | 0.9 unchanged |

A contribution is what puts the node into a Jacobian entry, which is why it —
and only it — rescued the value. It also explains the one operator that looks
like a counter-example: `transition()` shares the very same lowering and works
observed-only, because its output feeds the slew tracking residual. `ddt`, `idt`
and `laplace_nd` never have a simulator-stamped row at all.

The fix marks those nodes used before the scan decides. Five lines, and for a
model that contributes the value the flags are already true, so it is idempotent.
**No OpenVAF change and no ABI change were needed** — the descriptor already
carries `OSDI_ABSDELAY_INFOS` / `OSDI_LAST_CROSSING_INFOS`, and `osdiregistry.c`
already parses them. The mechanism is confirmed rather than inferred: before the
fix `n1#implicit_equation_1` does not exist as a circuit node at all; after it,
it does.

The rule is now written at the site, because the next simulator-stamped row will
hit the same trap: *a node coupled only by ngspice-side stamping has to be marked
here, or Enhancement-116 will ground it.*

## 2. `.save` never validated a device name

Nothing between `settrace` and the **per-point** read ever looked one up.
`addSpecialDesc` only interns the string, and the caller of `getSpecial`
discards `INPaName`'s `E_NODEV`/`E_BADPARM`. So:

| `.save` argument | before | after |
| --- | --- | --- |
| `@nosuchdev[i]` | 0-long vector, silent | 0-long vector **+ "no such device"** |
| `@r1[nosuchparam]` | 0-long vector, silent | 0-long vector **+ "device has no parameter"** |
| `@*[i_p]` (wildcard) | 0-long vector, silent | 0-long vector **+ "a wildcard … is not expanded here"** |
| `@x1.n1[i_p]` (hierarchical) | **0-long vector** | **full waveform** |
| `@n1[i_p]` (valid) | full waveform | unchanged, silent |

The check calls `INPaName` — the very routine the per-point read uses — so the
name is validated by exactly the rule that will apply later, rather than by a
weaker duplicate. A hierarchical spelling is then *rewritten* rather than
rejected: `@x1.r1[i]` is the form Enhancement-410 made work for `print`, `alter`
and `show`, but a save needs ngspice's flattened `r.x1.r1`, so the display name
stays the user's and only the lookup name changes.

Unresolvable entries are **warned about and then added anyway**. Dropping them
would change what the plot contains, and a bracket-less `@name` is a simulator
statistic served by a different path entirely.

Wildcards are diagnosed, not expanded. Every wildcard mechanism in the tree
(Enhancements 268/269/284/409) is setter-side: `if_setparam_wildcard_instance`
walks the device lists and *sets*, `if_hasparam_wildcard` *counts*. Nothing
returns the list of matching instance **names**, which is what a save expansion
would need, and its selection predicate uses `inout=set` — the wrong test for a
read-only quantity. Telling the user is the honest fix; inventing an enumerator
is a feature, not a bug fix.

### A correction to Enhancement-417's hunt notes

Round 25 recorded that "`.save v(nosuchnode)` errors properly, so the node path
diagnoses and the device path does not". That is wrong. A bad **node** name is
silently *dropped* — no vector and no message — because it fails `parseSpecial`
and a plain `.save` has no `db_analysis`, which gates the only diagnostic there.
The message seen at the time came from the plot ending up empty. So `.save`
validated *nothing*; the asymmetry was with `print`/`meas`/`wrdata`, which all
report the same name loudly.

## 3. `meas … when` invented a time

A threshold crossing located in the **first** interval produced `-inf`,
`1.15292e+05` seconds in a 3 µs run, or a negative time — silently, while the
identical measure was correct for a crossing anywhere later.

The arithmetic is a single line interpolating `prevScaleValue + (m_val −
prevValue)·Δt/(value − prevValue)`. The initialisation block counted a crossing
in the first interval but the *evaluation* deliberately starts one sample in, so
the leftover count was applied to a **later, crossing-free interval**, dividing
by a difference that was exactly zero (→ `−inf`) or a single ULP (→ `2^60·1e-13`
= 1.15292e+05). That is why every bad value was a power of two times a power of
ten.

### The first interval is an operating-point artifact, and that decided the fix

My first attempt evaluated the first interval properly instead of discarding it.
It produced an in-window time — and broke `defaulttransition`, which expects
`5.0e-07` and got `1.0002e-10`. That failure is the real lesson: **the first
interval runs from the operating-point solution to the first timepoint**, so it
routinely straddles a threshold for reasons that have nothing to do with the
waveform's dynamics. Starting the evaluation one sample in was never the bug; it
is deliberate. The bug was counting a crossing there and leaving the count
behind.

So the fix removes the count instead of consuming it, and adds the guard that
makes the class impossible:

* the initialisation block classifies the section and **counts nothing**;
* every interpolation is gated on the interval actually **bracketing** the
  target — `(prev − target)·(cur − target) ≤ 0` — mirroring `measure_at`, which
  has always refused to interpolate outside a bracketing pair;
* a `.dc` sweep restart resets to sample **0**, not sample 1, because
  `prevValue` there still holds the last point of the *previous* sweep, which is
  a bogus bracketing endpoint by construction.

Clamping the result to `[tstart, tstop]` was considered and rejected: it would
turn 1.15292e+05 into `tstop`, replacing a screaming failure with a plausible
wrong answer in a delay measurement.

Measured against the pre-418 binary:

| measure | before | after |
| --- | --- | --- |
| `when @c1[i]=0.5m rise=1` | 1.15292e+05 s | **reports failure** |
| `when @n1[i_p]=0.5m rise=1` (OSDI) | −5.0e-07 | **reports failure** |
| `trig/targ` on the same signal | −9.22337e+04 | **reports failure** |
| `when @c1[i]=0.5m cross=1` | 1.15292e+05 s | **1.00025e-06** — the real later crossing |
| mid-run jump, smooth crossing | correct | **bit-identical** |

Reporting failure is the same answer the neighbouring case already gives for an
unreachable target, and `cross=1` improves outright: instead of garbage it now
finds the genuine crossing further along.

## Verification

* **`examples/saveguard_examples` 26/26**, and **12/26 on the pre-418 binaries** —
  fourteen checks flip. Both solvers.
* The absdelay mechanism is asserted directly, not just its symptom: the suite
  checks that `n1#implicit_equation_*` exists as a circuit node.
* The contributed path is pinned as a negative control, since it is the one that
  already worked.
* The save fix is pinned against spurious warnings on the cases that generate
  `@dev[i]` wholesale: `.options savecurrents` over a mixed OSDI + R/C/L/diode
  deck, the same inside a subcircuit, a bracket-less `@totiter`, and plain node
  and branch saves — zero warnings in all four.
* The `meas` fix is pinned on a mid-run jump and a smooth crossing, both
  bit-identical, plus the eight measure-bearing example suites the change could
  reach (`opvar`, `stdaudit`, `defaulttransition`, `idtassert`, `acmargin`,
  `measovf`, and `crashfix3`/`castguard`, which assert *failure*).
* **Full regression 334/334.**

## Found by

A one-hour hunt over ngspice + OSDI. Two of the three were found by asking what a
reported number *was* rather than whether it was right — a vector that was 0 long
instead of absent, and a time whose mantissa was an exact power of two. The
absdelay item had been open since Enhancement-415; what closed it was the
observation that an `if` condition and a `$strobe` are both genuinely live uses
and neither rescued the value, which ruled out liveness and pointed at the
residual.
