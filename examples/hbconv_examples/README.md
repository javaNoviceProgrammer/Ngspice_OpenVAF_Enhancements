# Enhancement-483 — `set qpss_tol` / `set qpss_maxiter`, and HB stall detection

```
python3 verify_hbconv.py
```

23 checks, ~13 s. **6/23** against the pre-fix binary — 17 checks discriminate.

## What it is

`QPSShb` was called with its convergence bound and iteration cap compiled in:

```c
err = QPSShb(ckt, f1, f2, K1, K2, 0, 0, 60, 1e-10, verbose ? 1 : 0);
```

`tol` is an **absolute** bound on the residual norm `|F|`, so what a circuit can
actually reach depends on the circuit. The diode two-tone deck in
`distoexact_examples` settles at `|F| = 2.3e-15`. An FET amplifier carrying tens
of milliamps floors around `1e-8` and could never satisfy `1e-10`, however many
iterations it was given.

**The way it failed was the real defect.** On such a circuit the Newton iteration
reached `|F| = 9.4e-09` at iteration 4 — a reduction of nine orders — and then sat
on that number, flat to seven digits, for the remaining 55 iterations. Having
"failed" the level, the continuation ladder halved its step and walked all the way
back to `lambda = 0`, 1022 Newton iterations in all, and reported a bare
`error 103` (`E_ITERLIM`). A good answer found in five iterations was discarded
after minutes of work. At `hb 4 4` those minutes are six or seven, which reads as
a hang.

## The two fixes

**The knobs.** `set qpss_tol` and `set qpss_maxiter`, read like `qpss_verbose`
beside them. Both published types are asked, because the spelling decides the type
(E-454): `set qpss_tol=1e-8` arrives as a CP_REAL, `set qpss_tol = 1e-8` can
arrive as a CP_STRING. `strtod` and not `atoi`, so `qpss_maxiter=2e2` means 200
and not 2 — E-478's trap, pinned by check [7].

**Stall detection.** Four consecutive iterates that fail to improve `|F|` by 0.1%
is a stall. A stalled residual is *accepted* as the answer only if it sits at
least `1e6` below the residual the level opened with; otherwise it is a real
failure and still falls through to the ladder — it just gets there in a few
iterations instead of `maxiter`. When acceptance carries it, the message says so:

```
QPSS-HB: converged in 10 iterations, 1 continuation step (|F| = 9.429e-09,
STALLED above tol = 1.0e-10 after a 532224607x reduction -- accepted;
`set qpss_tol` to change the bound).
```

## The two checks that carry the claim

**[5] — stall-acceptance must not change the ANSWER.** Against the same circuit
run under a loosened bound, which converges the ordinary way in 5 iterations:

| | stall-accepted | `qpss_tol=1e-8` | rel. diff |
|---|---|---|---|
| fundamental f₁ | 1.040979e-01 | 1.040979e-01 | **0** |
| fundamental f₂ | 1.037436e-01 | 1.037436e-01 | **0** |
| IM3 2f₁−f₂ | 4.515496e-06 | 4.515547e-06 | 1.1e-05 |
| IM3 2f₂−f₁ | 4.468506e-06 | 4.468561e-06 | 1.2e-05 |
| **OIP3** | **33.9762 dBm** | **33.9762 dBm** | < 0.01 dB |

The fundamentals are bit-identical; the third-order products agree to ~1e-5, about
0.0001 dB on OIP3.

**[3] — a genuine failure must still fail.** `hb 3 3` on the same circuit stalls at
`|F| = 5.5e-05` at `lambda = 0` — a residual that never came down — and the stall
test must not accept it. The check asserts the *property* (orders above the floor
that [1] accepts) rather than the digits, so it tracks the distinction and not
solver drift.

## What it does not fix

`hb 3 3` and above on this circuit still fail, and loosening the bound does not
rescue them: `qpss_tol` at 1e-8, 1e-6 and 1e-4 all die at the same residual. That
is a different fault — the continuation cannot take its first step — and it is
deliberately left alone here. What changed is the *cost* of finding out: `hb 4 4`
now reports in 48 s instead of six to seven minutes.

## Where it came from

A two-tone ATF-34143 IP3 deck that appeared to hang. It did not — it ground for
minutes and then reported a bare iteration limit. With these two fixes `hb 2 2`
converges in well under a second and yields OIP3 ≈ +34 dBm, the two IM3 sidebands
agreeing to 0.1 dB.
