# Enhancement-210 — PSS polish: `.pss` dot-card runs in batch + complex spectrum vectors

Two usability fixes to the [E-117](Enhancement-117.md) shooting-method periodic
steady state (`pss`), in the spirit of [E-209](Enhancement-209.md) (which did the
same for `hb`).

## 1. The `.pss` dot-card now auto-runs in batch

The `pss` **command** (inside `.control`) worked, but a top-level **`.pss`** card
by itself silently did nothing in batch mode — `ngspice -b deck.cir` with just
`.pss …` reported *"no simulations run"*, unlike `.tran`, `.ac`, or `.hb`, which
run automatically. A deck had to wrap it in `.control … run … .endc`.

`.pss` is now dispatched to the `pss` command the same way E-146 (`.sweep`) and
[E-162](Enhancement-162.md) (`.hb`) handle their cards: during deck loading a
top-level `.pss …` line is stripped of its leading `.` and appended to the
post-parse control list, so it executes as `pss …` once the circuit is built
(`src/frontend/inp.c`). A boundary check keeps it from matching a longer name, and
it never matches `.psp` (periodic S-parameters, a distinct card). Decks that already
wrap `.pss` in `.control … run` keep working (one PSS run, unchanged output).

```
* now runs straight from the deck, no .control needed
V1 in 0 SIN(0 1 1meg)
...
.pss 1meg 20u 1 1024 10 50 5m uic
.end
```

## 2. The frequency-domain spectrum is published as complex vectors

The `pss` analysis already published two plots — `pss1` (the time-domain periodic
waveform) and `pss2` (the frequency-domain spectrum). But `pss2` stored **magnitude
only** (`IF_REAL`): the DFT computed each harmonic's phase and then threw it away, so
`vp(out)` was unavailable and `print out` gave a bare magnitude — inconsistent with
AC analysis (whose node vectors are complex) and with the `hb` command's E-209
vectors.

`pss2` now publishes **complex** node vectors (`IF_COMPLEX`): each harmonic is stored
as `mag · e^{jφ}` (the DFT already returns `φ` in degrees), built into `IFcomplex`
rows and emitted with `OUTpData` (as PAC/PXF/PSP do) instead of the real-only
`CKTdump`. `mag(out)` reproduces the old magnitude spectrum exactly and `vp(out)`
now recovers the phase. The time-domain `pss1` plot is unchanged (a real waveform).

```
.control
  pss 1meg 20u 1 1024 10 50 5m uic
  plot mag(out)        * the spectrum (as before)
  print vp(out)        * ...and now the phase, too
.endc
```

### Backward compatibility

Because `pss2` node vectors are now complex, `print out` / `wrdata out` emit
`re, im` columns (exactly as AC analysis does), not a bare magnitude. Decks that
parsed the magnitude directly should use `mag(out)`; the bundled `rc_pss.cir` was
updated from `print b` to `print mag(b)` accordingly. This is the same
magnitude-vs-complex convention the rest of ngspice's frequency-domain analyses use.

## Verification

[`examples/rfpss_examples/verify_rcpss.py`](../examples/rfpss_examples/verify_rcpss.py)
gains two checks: a top-level `.pss` card (no `.control`) auto-runs in batch and
reaches convergence; and the frequency-domain spectrum resolves as complex — both
`vm(out)` (magnitude) and `vp(out)` (phase) return, with a driven diode rectifier's
harmonics showing the expected non-trivial phase. The existing PSS / PAC / PXF /
solver-parity checks pass unchanged (`rc_pss.cir` migrated to `mag(b)`).

## Scope

ngspice-only, `src/frontend/inp.c` (dispatch) + `src/spicelib/analysis/dcpss.c`
(complex `pss2` output). The shooting-PSS numerical core, the retained periodic
operating point, and every analysis built on it (PAC/Pnoise/PXF/PSP) are untouched.
