# Enhancement-141 — Two-tone small-signal QPXF (quasi-periodic transfer function)

With QPSS (E-136), QPAC (E-137) and QPnoise (E-138/139) in place, the two-tone
small-signal set was one piece short of the single-tone PSS → PAC → pnoise → **PXF**
suite. This enhancement adds that piece — **QPXF**, the quasi-periodic transfer
function, the adjoint of QPAC:

```
qpxf <output_node> <f_in>
```

Run after a `qpss <expr> <f1> <f2> hb`, it reports the transfer from an input at **every
sideband** `f_in + k1·f1 + k2·f2` to the chosen output at `f_in` — the small-signal
frequency conversion of the pumped operating point, seen from the output's perspective.

## Method

QPXF is exactly PXF (E-125) on the two-tone harmonic set. It reuses the **adjoint** of
the 2-D conversion matrix already built for QPnoise (`qp_solve_adjoint`):

```
Hᵀ · Ψ = e_{out,(0,0)}
```

`Ψ_{(k1,k2),j}` is then the transimpedance from an injection at `(node j, sideband
(k1,k2))` to the output at sideband `(0,0)`. Dotting each sideband block of `Ψ` with the
netlist `AC`-source pattern `B0` (the same stimulus QPAC uses, captured at the operating
point) gives the transfer from that input sideband to the output:

```
H_{(k1,k2)} = Σ_j Ψ_{(k1,k2),j} · B0_j
```

The whole set of sideband transfers comes from **one** adjoint solve — the point of an
adjoint/transfer-function analysis. By the reciprocity identity `(H⁻¹B)_out =
(H⁻ᵀe_out)ᵀB`, the sideband-`(0,0)` transfer is **bit-identical** to the QPAC response at
the output node — a cross-check that pins the adjoint solve. Because QPXF only reads the
retained conversion data, it is **solver-independent** (KLU and Sparse bit-identical) by
construction.

## Verification

`verify_qpxf.py` (6/6), numpy-free:

- **reciprocity** — the QPXF `(0,0)` transfer equals the QPAC `(0,0)` response
  bit-identically (the defining PXF↔PAC cross-check, now two-tone);
- **sideband reciprocity** — the conversion-sideband magnitudes match QPAC too;
- **reduce-to-XF** — with the pump ~0 the operating point is time-invariant, so the
  `(0,0)` transfer is the plain linear transfer (a 1 A stimulus into `R = 1 kΩ` gives
  `1000`) and every conversion sideband vanishes;
- **clean failure** — `qpxf` with no `qpss … hb` operating point reports "no QPSS
  operating point";
- **solver parity** — KLU and Sparse transfers are bit-identical.

The rest of the suite is unaffected: QPSS 11/11, QPSS-HB 7/7, QPAC 7/7, QPnoise 10/10.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `QPXFanalyze` — one adjoint solve (`qp_solve_adjoint`), each sideband block of `Ψ` dotted with the AC-source pattern `B0`, printed as the per-sideband transfer |
| `ngspice-46/src/frontend/com_qpxf.c` / `.h`, `commands.c`, `com_commands.h`, `Makefile.am` (+ `Makefile.in`) | the `qpxf` command |
| `ngspice-46/src/include/ngspice/cktdefs.h` | `QPXFanalyze` prototype |
| `examples/qpss_examples/verify_qpxf.py` | the 6-check QPXF suite |

## Scope

Two-tone small-signal transfer function around the E-136 QPSS operating point, single
input frequency per call, `AC`-source or unit-input reference. With QPAC and QPnoise this
**completes the quasi-periodic small-signal suite** (QPSS → QPAC → QPnoise → QPXF),
mirroring the single-tone PSS/PAC/Pnoise/PXF. Follow-ups: an input-frequency sweep and
more than two tones.
