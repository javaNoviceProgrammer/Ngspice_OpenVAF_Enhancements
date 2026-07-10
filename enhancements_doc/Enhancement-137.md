# Enhancement-137 — Two-tone small-signal QPAC (quasi-periodic AC)

Enhancement-136 added the frequency-domain two-tone Harmonic Balance engine (`qpss …
hb`), the true quasi-periodic steady state, and had it **retain its operating point**.
This enhancement adds the small-signal analysis that sits on top of it — **QPAC**, the
two-tone analogue of PAC:

```
qpac <f_in>
```

Run after a `qpss <expr> <f1> <f2> hb`, it injects a small signal at `f_in` around the
retained quasi-periodic operating point and reports the response at **every sideband**
`f_in + k1·f1 + k2·f2`. A time-varying (here two-tone-pumped) operating point *mixes* the
small signal to those sidebands — the effect a static `.ac` cannot see.

## Method

QPAC is exactly `pac_solve_at` (E-121/122) on the two-tone harmonic set. Around the QPSS
operating point retained in `qpss_hb_saved`, the small-signal Kirchhoff system is the
**2-D conversion matrix** `H_{(n),(m)} = G_{n−m} + jω_m·C_{n−m}` built at the input
frequency (`qp_build_matrix(hd, f_in, …)` — the same matrix the QPSS Newton used as its
Jacobian, re-evaluated with `ω = 2π(f_in + m1·f1 + m2·f2)`). The stimulus is placed in the
`(0,0)` sideband — a netlist `AC`-flagged source's RHS `B0` (captured, bias-independent,
at the operating point) or a unit current fallback — and the dense complex solve
(`pss_csolve`) returns the full sideband response `X_{k1,k2}` in one shot:

```
H(f_in) · X = B0   →   X_{k1,k2} = response at  f_in + k1·f1 + k2·f2
```

Because the conversion data is read straight from the retained operating point, QPAC adds
no device evaluation of its own and is **solver-independent** (KLU and Sparse
bit-identical) by construction.

## Verification

`verify_qpac.py` (7/7), numpy-free:

- **reduce-to-AC** — with the pump driven to ~0 the operating point is time-invariant, so
  the direct `(0,0)` response equals the plain `.ac` response (a 1 A stimulus into
  `R = 1 kΩ` gives exactly `1000`) and every conversion sideband vanishes — the essential
  correctness anchor;
- **conversion ratio** — under a real two-tone pump, `G(t) = 3g₃v²` has an `f1±f2`
  harmonic twice its `2f1` harmonic, so the converted sidebands satisfy
  `|(1,1)| / |(2,0)| = 2` exactly;
- **conversion present** — sidebands are non-zero under the pump (the mixing happens);
- **tone symmetry** — for equal tones `|(1,1)| = |(1,−1)|` and `|(2,0)| = |(0,2)|`;
- **clean failure** — `qpac` without a prior `qpss … hb` reports "no QPSS operating point"
  rather than crashing;
- **solver parity** — KLU and Sparse responses are bit-identical.

The QPSS suites are unaffected: E-136 `verify_qpss_hb.py` stays 7/7 and E-133
`verify_qpss.py` stays 11/11.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `QPACanalyze` (build the 2-D conversion matrix at `f_in`, inject the `(0,0)` stimulus, solve, print the sideband table); `qp_harm` gains `B0r`/`B0i`/`has_src`, captured at the QPSS operating point during retention |
| `ngspice-46/src/frontend/com_qpac.c` / `.h`, `commands.c`, `com_commands.h`, `Makefile.am` (+ `Makefile.in`) | the `qpac` command |
| `ngspice-46/src/include/ngspice/cktdefs.h` | `QPACanalyze` prototype |
| `examples/qpss_examples/verify_qpac.py` | the 7-check QPAC suite |

## Scope

Two-tone small-signal QPAC around the E-136 QPSS operating point, single input frequency
per call, `AC`-source or unit-current stimulus, verified against the reduce-to-AC limit
and analytic pump conversion. With E-136 this completes the **quasi-periodic (QPSS / QPAC)**
gap. Follow-ups: an input-frequency sweep (like `.pac`'s dec/oct/lin), quasi-periodic noise
(QPnoise) and transfer function (QPXF) on the same retained operating point, and more than
two tones.
