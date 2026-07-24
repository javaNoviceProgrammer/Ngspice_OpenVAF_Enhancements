# SFFM/AM sources hold the DC offset before the delay (Enhancement-318)

A correctness-campaign find: the `SFFM` and `AM` voltage sources returned `0` for `time <= TD`
(`vsrcload.c`), dropping the DC offset `VO` at the operating point and over the whole pre-delay
window, and injecting a spurious startup transient. Three oracles show `VO` is correct: the `SIN`
case in the same function holds its quiescent value; ngspice's own current-source SFFM
(`isrcload.c`) has no such zeroing; and `SIN`/`PULSE`/`EXP`/`PWL` all preserve their offset. The
fix holds the waveform's `time=0` value, matching them.

## Verify

```sh
python3 verify_sffmoffset.py
```

Three checks: a delayed `SFFM(VO=1.5,…)` reads 1.5 and `AM(VO=2,…)` reads 2.0 in the pre-delay
window (both were 0 pre-fix), while the `SIN` control still reads 1.5.
