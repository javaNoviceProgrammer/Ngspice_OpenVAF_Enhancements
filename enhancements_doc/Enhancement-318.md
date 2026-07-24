# Enhancement-318 — ngspice: SFFM/AM voltage sources dropped the DC offset before the delay

Found in the correctness campaign, oracle-checking transient waveform sources against their
closed-form definition — and, decisively, against the **same quantity computed two other ways**.

## The bug

`vsrcload.c` evaluated the `SFFM` (single-frequency FM) and `AM` (amplitude modulation) voltage
sources with, at `time <= 0` (before the source's delay `TD`):

```c
time -= TD;
if (time <= 0) {
    value = 0;          /* SFFM (line 279) and AM (line 315) */
}
```

Returning `0` **drops the quiescent value** — the DC offset `VO` and the initial phase term.
Three independent oracles show `VO` is correct:

1. The `SIN` case in the *same function* holds `VO + VA·sin(phase)` at `time <= 0` (the continuous
   limit at the start of the waveform).
2. ngspice's *own current-source* SFFM (`isrcload.c`) has **no** such zeroing and evaluates the
   formula directly — the two SFFM implementations in one binary disagreed.
3. `SIN`/`PULSE`/`EXP`/`PWL` all preserve their offset at `time <= 0`.

Consequences: the operating point of an SFFM/AM source (with the common `TD = 0`) was `0` instead
of `VO`, and over any pre-delay window the source read `0`, injecting a **spurious startup
transient** (e.g. an `SFFM(2, 0.001, …)` ≈ 2 V source into an RC started at 0 V and charged up to
0.785 V over 0.5 ms, where a DC-2 source stays flat at 2 V).

## The fix

Hold the waveform's `time = 0` value before the delay, matching `SIN` and the current-source
implementation:

- **SFFM:** `value = VO + VA·sin(phasec + MDI·sin(phasem));`
- **AM:** `value = VO + (VMO + VMA·sin(phasem))·sin(phasec);`

For zero phases these reduce to `VO`, as expected.

## Verification

`examples/sffmoffset_examples/verify_sffmoffset.py` — over a 0.2 ms-delayed window an
`SFFM(VO=1.5, …)` now reads 1.5 and `AM(VO=2, …)` reads 2.0, exactly as the `SIN` control reads
1.5; all three **fail on the pre-fix binary** (SFFM/AM read 0). No example or regression circuit
used SFFM/AM, so nothing else changes.

## Scope of change

`src/spicelib/devices/vsrc/vsrcload.c`, the `SFFM` and `AM` `time <= 0` branches only. The
current-source (`isrcload.c`) was already correct and is untouched.
