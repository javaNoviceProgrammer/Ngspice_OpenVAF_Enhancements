# Transient-form QPSS mixing-bin leakage (Enhancement-319)

A correctness-campaign find. The transient-form `qpss <expr> <f1> <f2> [periods] [maxorder]`
computed each 2-D harmonic by a trapezoidal integral over the raw transient grid's "last period" —
a window that was not exactly the beat period `T`, was non-uniform, and had non-periodic endpoints,
so the fundamental leaked into every mixing bin at `~5.8e-4` (~−45 dB). On a **linear** two-tone RC
(every product must be 0) confirmed against the HB-form (`~1e-16`) and a plain `.tran` + DFT. The
fix resamples the last period onto a uniform grid over exactly `T` and uses a rectangular-rule DFT
(exact for commensurate tones); the floor drops ~4 decades to ~−122 dB, and real products are
unchanged. See the write-up.

## Verify

```sh
python3 verify_qpssleak.py
```

Two checks: the linear circuit's mixing products are `< 1e-5` of the fundamental (pre-fix ~7e-3),
and the two fundamentals are present.
