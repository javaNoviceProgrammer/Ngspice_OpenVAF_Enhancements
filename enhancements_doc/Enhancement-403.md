# Enhancement-403 — the nominal temperature that was added to a difference

Writing `temp=27` on a resistor — the ambient itself — inflated its thermal
noise power by **9%**. The instance is electrically identical to one with no
`temp=` at all, and both are at 27 °C, yet:

| instance line | output noise |
| --- | --- |
| `rd x 0 1k` | 4.069337e-09 |
| `rd x 0 1k dtemp=0` | 4.069337e-09 |
| **`rd x 0 1k temp=27`** | **4.248250e-09** |

Same circuit, same temperature, 4.4% more noise voltage. No diagnostic.

## The arithmetic

`NevalSrcInstanceTemp` computes thermal noise as `4·k·(CKTtemp + param2)·G`, so
its `param2` is a **delta** from the circuit temperature and nothing else. Five
devices computed that delta as

```c
dtemp = inst->REStemp - ckt->CKTtemp + (model->REStnom - CONSTCtoK);
```

The first two terms are right. The third adds the **nominal** temperature
expressed in **Celsius** — 27 by default — to a temperature *difference*. The
instance temperature is stored in Kelvin (`value->rValue + CONSTCtoK`), so for an
instance sitting at ambient the delta should be 0 and instead came out
`0 + (300.15 − 273.15)` = **exactly 27 K**.

The same line is copy-pasted into five device noise routines, all with the same
error:

| device | file |
| --- | --- |
| resistor | `res/resnoise.c` |
| BJT | `bjt/bjtnoise.c` |
| diode | `dio/dionoise.c` |
| VBIC | `vbic/vbicnoise.c` |
| HICUM/L2 | `hicum2/hicum2noise.c` |

The fix drops the third term. Verified in both directions: `temp=27` now agrees
exactly with no-`temp=`, while a genuine instance temperature still acts —
`temp=100` and `dtemp=73` (the same temperature written two ways) agree to the
digit at 4.536844e-09, a ratio of 1.11489 against the analytic
`sqrt(373.15/300.15) = 1.11499`.

## How it surfaced: `sens` poisoning `noise`

A bug hunt found that running `sens` made every later `noise` in the session
return a different answer — 2.878894e-09 alone against 3.005592e-09 after
`sens`, sticky, with no intervening analysis clearing it and no diagnostic. The
route to the cause is worth recording, because the symptom pointed away from it:

* the shift was **exactly constant at 1.08996 in power** across resistor values
  and circuit topologies, so it was a global scale, not a device perturbation;
* `onoise` and `inoise` scaled **equally**, so the transfer function was intact
  and the noise *sources* had changed;
* 1.089955 = 327.15/300.15, i.e. **+27 K**, and repeating the measurement at
  100 °C and −50 °C gave **+27.00 K every time** — a constant, not a scaling;
* an OSDI device's own `white_noise` was **unaffected** (ratio 1.00000) while the
  built-in resistor in the same circuit shifted, which located the fault in the
  built-in device's temperature handling rather than in `ckt->CKTtemp`.

`sens` perturbs every settable parameter of every device and restores the
*values*, but the restore leaves the `…tempGiven` flag set. That flips the noise
routine into the branch above, and the latent arithmetic error becomes visible.
**Fixing the arithmetic fixes both**: with the corrected delta, an instance whose
temperature equals ambient contributes 0 whether or not the flag is set.

Two other things were found while diagnosing this and deliberately **not**
shipped here:

* `cktsens.c` overwrites `ckt->CKTnumStates` — the circuit-wide state-vector size
  — with one device's state offset and never restores it. A save/restore was
  written and then reverted: it changed no measured result, and a fix must be no
  wider than its evidence. Recorded as a latent defect awaiting a symptom.
* `sens` leaving `…tempGiven` set is a real state leak in its own right. With the
  arithmetic corrected it has no observable consequence for these five devices,
  so it is left alone rather than fixed speculatively.

# Enhancement-403b — a type error that said the same thing three times

```
error: type mismatch: expected string literal, string literal or string literal
       but found real parameter ref
```

`ac_stim`'s first argument is the analysis name, and passing a real there is a
genuine error — but the message listed the expected type three times.

`hir_ty`'s signature checker collects the requirement at the failing argument
position from **every surviving candidate signature** and hands the list to a
renderer that joins it verbatim. `AC_STIM` has four signatures and three of them
take `Literal(String)` at argument 0, so the user was told the same thing three
times. The list is now deduplicated, first-seen order preserved:

```
error: type mismatch: expected string literal but found real parameter ref
```

Genuinely distinct alternatives are untouched — `$limit` still reports
*"expected string literal or function"*.

## Verification

* **Full regression 322/322.**
* **`cargo test --workspace --features llvm18` 210/0.**
* **Corpus differential** — 124 `VA_TEST` models at the same `-o` path: 107
  compiled by both, **0 return-code differences, 0 byte differences**. The
  compiler change touches only a diagnostic string, and the bytes confirm it.

The noise fix changes numbers, by design, for any circuit that puts `temp=` on a
resistor, BJT, diode, VBIC or HICUM/L2 instance and runs `noise`. Nothing in the
example suite does, which is why the regression is unchanged at 322/322.
