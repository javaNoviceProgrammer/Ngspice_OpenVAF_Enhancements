# Enhancement-685: `sens` leaves every instance as it found it — the instance struct is snapshotted around each perturbation and put back, as E-440 does for the model

**Scope:** F1 of the
[bug hunt of 2026-09-21](../docs/bug_hunts/2026-09-21_ngspice-osdi-analyses-sens-and-events.md).
ngspice: `src/spicelib/analysis/cktsens.c` (the perturbation loop: a byte snapshot of the
instance being perturbed beside E-440's model snapshot, put back at both write-back sites).
`examples/sensrestore_examples/` (two OSDI modules and eight checks, 29). **ngspice only.**

**Suites:** [`sensrestore_examples`](../examples/sensrestore_examples/) 29 of 29 per
solver, both solvers (7 of the 8 new checks fail on the E-680 binaries, beside E-682's
three; the one that passes there is the absence of the "Instance temperature specified"
message in a deck without `dtemp`); `sensstate`, `senscplx`, `osdisens`, `analyses`,
`finalstep` unchanged; full sweep 531 of 531.

## What was wrong

A sensitivity analysis perturbs each instance parameter through the device's own setter,
solves, and writes the original value back through the same setter. The setter marks the
parameter *given*, and nothing un-marks it. [E-440](Enhancement-440.md) found the model-side
form of this (a BJT whose `ibe`/`ibc` became given at 0 conducted nothing for the rest of
the session) and restores every model struct byte for byte. The instance side was left as
it was, and for an instance a given flag changes the circuit:

| after one `sens` | measured | fresh deck |
|---|---|---|
| built-in resistor, `tc1=0.01`, `.option temp=60` | 1.00 V (`tce=0` given: the exponential temperature form, coefficient 0) — even after `alter r2 temp=60` | 1.33 V |
| OSDI resistor, `tc1=0.01`, then `set temp=60` / `dc temp` / `alter n1 dtemp=10` | 1.00 V, a flat sweep, "Instance temperature specified, dtemp ignored" (`temp` given at the circuit temperature, without `dtemp`) | 1.33 V, 0.73 → 1.13 V, honoured |
| built-in and OSDI diode, then `set temp=60` | unchanged (pinned) | moved |
| OSDI module with `reff = $param_given(w) ? rsh*w/1u*2 : r`, `w` never set | 2.0 V (`w` given now) | 1.0 V |
| AC `sens`, then `alter r1 r=2k`, then `ac` | the 1 kΩ response, 0.4995 (`ac` alias given at 1000) | 0.3327 |
| a second AC `sens` in the session | every resistor's sensitivity −0 | equal to the first |
| `noise` after a `sens` at 60 °C | 9.59e-8 (the 27 °C resistor) | 1.0248e-7 |

`show`, `@r2[temp]` and `@r2[tc1]` all printed the original values throughout; only `reset`
cleared it. Model-scope parameters were already safe (E-440).

## What changed

**The instance is snapshotted around each perturbation.** Beside E-440's per-parameter
model snapshot, the loop copies the instance struct (`DEVinstSize` bytes — for an OSDI
device that block holds the instance data and its given-flag table) before the setter is
called with the perturbed value, and copies it back after the original value is written
back, at both restore sites (the normal path and the "changes the model's node collapse"
path). The temperature update and the OSDI collapse check then run on the restored
instance, exactly as before. A model-parameter perturbation snapshots nothing extra: it
touches no instance flag, and the instance's derived values are recomputed by the same
temperature update.

The snapshot is taken after the per-frequency setup of an AC sweep and never spans a
matrix rebuild, so the matrix and node pointers it restores are the ones the instance
holds at that moment; under KLU the AC loop re-binds the device's pointers before each
load in any case.

## Verification

| check | result |
|---|---|
| built-in resistor with `tc1` at 60 °C: `op`, `sens`, `op` | 1.33, 1.33 (was 1.33, 1.00) |
| OSDI resistor beside it, then `set temp=80` | 1.33 after the `sens`, 1.53 after (was 1.33, then still 1.33) |
| "Instance temperature specified, dtemp ignored" during or after the sweep | absent |
| OSDI resistor with `dtemp=20`: `sens`, then `alter n1 dtemp=40` | 1.2, then 1.4 (was 1.0, then refused) |
| `$param_given(w)` rule, `w` never set | 1.0 before and after, `wg` = 0 (was 2.0, `wg` = 1) |
| AC `sens`, then `alter r1 r=2k` and `ac` | the fresh deck's response (was the 1 kΩ one) |
| a second AC `sens` | the same `r1` sensitivity as the first (was −0) |
| `noise` after a `sens` | equal to the one before it |
| the hunt's diodes, `dc temp` sweep, `.option temp=60` decks | all follow the temperature after a `sens` |
| the E-680 binaries on the suite | 7 of the 8 new checks fail |
| full sweep | 531 of 531 |

## What this does not do

- A `sens` still evaluates `@(initial_step)` once per perturbation ([E-683](Enhancement-683.md)'s
  note); the instance it leaves behind is now the one the netlist described.
- The AC form's per-frequency `CKTunsetup`/`CKTsetup` (the whole circuit rebuilt at every
  frequency) is upstream ngspice's design and is untouched.
