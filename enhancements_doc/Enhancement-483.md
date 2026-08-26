# Enhancement-483 — `set qpss_tol` / `set qpss_maxiter`, and HB stall detection

The harmonic-balance convergence bound and iteration cap become reachable from a
deck, and a Newton residual that has stopped moving is recognised as stopped
instead of being ground against for minutes and then discarded.

## Why

`QPSShb` was called with both numbers compiled in:

```c
err = QPSShb(ckt, f1, f2, K1, K2, 0, 0, 60, 1e-10, verbose ? 1 : 0);
```

`tol` is an **absolute** bound on the residual norm `|F|`, so what is reachable
depends entirely on the circuit. The diode two-tone deck in `distoexact_examples`
settles at `|F| = 2.3e-15`. An FET amplifier carrying tens of milliamps floors
around `1e-8`, and no number of iterations will take it to `1e-10`.

**The way it failed was the real defect.** On such a circuit:

```
iter 0: |F| = 5.018e+00
iter 1: |F| = 2.912e+00
iter 2: |F| = 1.776e-02
iter 3: |F| = 5.200e-06
iter 4: |F| = 9.482e-09    <- nine orders down, quadratic convergence
iter 5-59: 9.429e-09 ... flat to seven digits
```

Having "failed" the level, the continuation ladder halved its step and walked all
the way back to `lambda = 0` — **1022 Newton iterations** — then reported a bare
`error 103` (`E_ITERLIM`). A perfectly good answer, found in five iterations, was
thrown away after minutes of work. At `hb 4 4` those minutes are six or seven,
which is indistinguishable from a hang.

## What changed

### The knobs

`set qpss_tol` and `set qpss_maxiter`, read in `com_qpss.c` the same way
`qpss_verbose` beside them already was.

Both published types are asked, because Enhancement-454's lesson is that the
spelling decides the type: `set qpss_tol=1e-8` arrives as a CP_REAL while
`set qpss_tol = 1e-8` can arrive as a CP_STRING. The parse is `strtod` and not
`atoi`, so `qpss_maxiter=2e2` means **200 and not 2** — Enhancement-478's trap,
where a count was validated as a float and then truncated by `atoi`.

A value that is present but unusable is **reported and the default kept**, never
silently dropped:

```
Warning: qpss_tol must be positive; 0 ignored.
Warning: qpss_tol: 'abc' is not a positive number; ignored.
```

### Stall detection

An iterate that improves `|F|` by less than 0.1% has not improved it.
`QP_STALL_RUN` (4) of those in a row is a stall.

A stalled residual is **accepted as the answer only if it earned it** — at least
`QP_STALL_ACCEPT` (1e6) below the residual the level opened with. A stall at a
residual that never came down is a real failure and still falls through to the
continuation ladder; it simply gets there in a few iterations instead of
`maxiter`. That distinction is the whole design: the test is not "give up early",
it is "stop pretending a converged answer has not converged".

When acceptance carries it, the closing message says which test did the work:

```
QPSS-HB: converged in 10 iterations, 1 continuation step (|F| = 9.429e-09,
STALLED above tol = 1.0e-10 after a 532224607x reduction -- accepted;
`set qpss_tol` to change the bound).
```

## The claim, and how it is checked

**Stall-acceptance must not change the answer.** Check [5] runs the same circuit
twice — once accepted on the stall test at 10 iterations, once converging the
ordinary way under a loosened bound at 5 — and compares the mix spectra:

| | stall-accepted | `qpss_tol=1e-8` | rel. diff |
|---|---|---|---|
| fundamental f₁ | 1.040979e-01 | 1.040979e-01 | **0** |
| fundamental f₂ | 1.037436e-01 | 1.037436e-01 | **0** |
| IM3 2f₁−f₂ | 4.515496e-06 | 4.515547e-06 | 1.1e-05 |
| IM3 2f₂−f₁ | 4.468506e-06 | 4.468561e-06 | 1.2e-05 |
| **OIP3** | **33.9762 dBm** | **33.9762 dBm** | **< 0.01 dB** |

The fundamentals are bit-identical and the third-order products agree to about
0.0001 dB on OIP3.

**A genuine failure must still fail.** Check [3] is the counterweight: `hb 3 3` on
the same circuit stalls at `|F| = 5.5e-05` at `lambda = 0`, a residual that never
came down, and is still refused. That check asserts the *property* — orders above
the floor check [1] accepts — rather than the digits, so it tracks the distinction
and not solver drift.

## Effect

On the two-tone ATF-34143 IP3 deck that prompted this:

| | before | after |
|---|---|---|
| `hb 2 2` | `E_ITERLIM` after 14 s | **converges**, 10 iterations, < 1 s |
| `hb 2 2` + `set qpss_tol=1e-8` | not reachable from a deck | converges, 5 iterations, no caveat |
| `hb 4 4` | `E_ITERLIM` after ~6-7 min | fails in **48 s** |

The convergence grid opens up considerably (`ok*` = accepted on the stall test):

```
        K2=1     K2=2     K2=3     K2=4
  K1=1  ok       ok       ok       ok
  K1=2  ok       ok*      ok*      ok*
  K1=3  ok       ok*      FAIL     FAIL
  K1=4  ok       ok*      FAIL     FAIL
```

`hb 2 2` is the case that matters for IP3 — third-order products need only K = 2 —
and it now yields OIP3 ≈ +34 dBm with the two sidebands agreeing to 0.1 dB.

## What it deliberately does NOT fix

`hb 3 3` and above on that circuit still fail, and the bound does not rescue them:
`qpss_tol` at 1e-8, 1e-6 and 1e-4 all die at the same residual, at `lambda = 0`,
before the continuation can take its first step. That is a separate fault and is
left alone. What this enhancement changes there is the **cost of finding out** —
48 s instead of six to seven minutes, with a message that names the residual.

## Verification

`examples/hbconv_examples/verify_hbconv.py` — **23/23**, about 13 s. Against the
pre-fix binary the same suite scores **6/23**: seventeen checks discriminate.

The existing harmonic-balance and quasi-periodic suites are unaffected —
`qpssleak`, `distoexact` (both solvers), `plotorder` 25/25 and `pzklu` 4/4 all
pass unchanged, and the diode deck still converges in 4 iterations to
`|F| = 2.3e-15` with no caveat, which is check [4].

Full regression **397/397**, both solvers. ngspice-only, no compiler change.
