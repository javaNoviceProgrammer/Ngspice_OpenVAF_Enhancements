# Enhancement-412 — the operating point that changed with frequency

```
op                  ->  @nd1[vbias] = 0.493973289     (correct)
ac lin 1 1k   1k    ->  @nd1[vbias] = 0.482341031
ac lin 1 10k  10k   ->  @nd1[vbias] = 0.481902836
ac lin 1 1meg 1meg  ->  @nd1[vbias] = 0.047358714
```

`vbias` is an operating-point variable that does nothing but `vbias = V(a,c)`.
The true bias is **0.493973289**, from solving the circuit's KCL cubic by hand.
Read after an `.ac`, an OSDI opvar returned something else — and something
different at every frequency.

**An operating point cannot depend on frequency.** That is what makes this a
defect rather than a tolerance argument: the value is identical at `reltol`
1e-3, 1e-6 and 1e-10, and with a multi-point sweep it holds the *last* point's.

## Where it came from

Enhancement-53 fires `@(final_step)` by issuing one dedicated evaluation per
instance once an analysis completes, at `CKTrhsOld`. After a frequency sweep
that vector holds the **small-signal solution at the last swept frequency**, not
a bias point. The evaluation therefore recomputed the whole model from a complex
response and left the results in the instance.

The model really is re-evaluated, not merely mis-read — confirmed with opvars
chosen to tell those apart:

| opvar | after `op` | after `ac` at 100 kHz | recomputed at the ac solution would be |
| --- | --- | --- | --- |
| `vplain = V` | 0.500000000 | 0.455084919 | 0.455084919 |
| `vaffine = 3V+1` | 2.500000000 | 2.365254757 | 2.365254756 |
| `vsq = V²` | 0.250000000 | 0.207102283 | 0.207102283 |
| `kconst = 42` | 42 | 42 | 42 |

Built-in devices are unaffected — a diode's `vd`/`id`/`gd` are byte-identical
before and after an `.ac` — because they have no such post-analysis evaluation.
This is the project's recurring *"works for a built-in, silently not for OSDI"*
vein.

## What was **not** wrong

Established before touching anything: **the analyses themselves.** A
bias-dependent `white_noise(kf*V²)` source on a reactive device integrated to

```
onoise_spectrum = 1.342573180366e-01
```

which matches the prediction from the **dc bias** (1.342573e-01) exactly, and
not the one from the ac solution (7.21e-02). So the noise, the AC response and
everything else were always computed at the correct operating point. This is a
**readback** defect. It is also not sticky — any following `op`, `dc` or `tran`
restored the correct value.

Reporting that boundary matters: the headline "operating point is wrong after
AC" would have implied wrong analysis results, and that is not what happens.

## The fix, and why it is a snapshot

The obvious repair — skip the evaluation for AC and noise — is wrong: that
evaluation is the *only* thing that fires `@(final_step)`, and
`@(final_step("ac"))` and the noise variant are supported and tested by
`finalstep_examples`.

So `OSDIfinalStep` now snapshots the instance data around the call and restores
it afterwards, for `MODEAC` and `MODEACNOISE` only. The event bodies still run
and their `$strobe`/`$fdisplay` side effects stand; everything the evaluation
wrote into the instance is discarded. Discarding is exactly right here, because
those results are by design never loaded into the matrix or RHS — E-53's own
comment says so.

DC, DC-sweep and transient are deliberately **not** snapshotted: there the final
solution *is* a real operating point, so the values that evaluation leaves
behind are the ones a reader should see. Measured unchanged.

## Why it survived this long

With a purely resistive device the dc and ac solutions coincide, and the defect
is invisible. It needs a **reactive** device to show at all — so the natural
small test case cannot see it. The example is reactive on purpose, and says so.

## Verification

* **`examples/opvarac_examples` 19/19**, and **12/19 on the pre-412 binary**.
* Twelve analyses now report one identical operating point; four frequencies
  decades apart give the same reading.
* `@(final_step("ac"))` fires, exactly once, and the noise variant fires —
  `finalstep_examples` and `simctrl_examples` pass unchanged.
* The AC response itself is still right, checked against the closed-form
  |Z/(1k+Z)| = 0.499753442.
* **Full regression 329/329.** The compiler is untouched.

## Found by

A one-hour bug hunt over OSDI, probing opvars across every analysis. The first
sign was a 0.1% discrepancy that looked like a tolerance artifact; it survived
three decades of tolerance tightening, and then the frequency sweep made it
unambiguous.
