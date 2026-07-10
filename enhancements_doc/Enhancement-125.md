# Enhancement-125 — periodic transfer function (`.pxf`)

The third and final RF periodic small-signal analysis, completing the
**PSS → PAC → Pnoise → PXF** suite. PXF is the **adjoint** counterpart of
[`.pac`](Enhancement-122.md): where PAC injects one input and reads the response at
every output, PXF fixes one **output** and gives the transfer from the input at each
sideband — the efficient way to ask "what reaches this node, and from where."

## The idea

PXF solves the **adjoint of the conversion matrix**,

```
Hᵀ Ψ = e_{out,0},
```

whose sideband-`k` block `Ψ_k(j)` is the transfer from a unit injection at node `j`,
sideband `k`, to the fixed output at sideband 0. Dotting each block with the netlist
AC-source pattern `B0` (the same stamp `.pac`/`.pnoise` capture) gives the transfer
from the input to the output at that sideband:

```
xf_k(f) = Σ_j Ψ_k(j) · B0(j).
```

The sideband-0 result is not merely *close* to the PAC response — it is **exactly**
equal, by the linear-algebra identity

```
(H⁻¹ B)_out = e_outᵀ H⁻¹ B = (H⁻ᵀ e_out)ᵀ B = Ψᵀ B,
```

so `.pxf`'s `xf` and `.pac`'s output at the same node agree to machine precision.
That is the reciprocity cross-check that pins the adjoint solve
([`pac_solve_adjoint`](Enhancement-124.md), reused from pnoise) to the forward
[`pac_solve_at`](Enhancement-122.md).

## The command

```
.pxf Fguess StabTime OscNode Points Harmonics SC_iter Steady_coeff \
     OutNode <DEC|OCT|LIN> Npts Fstart Fstop [maxsideband]
```

The first seven fields are the [`.pss`](Enhancement-117.md) parameters, then the
output node, an `.ac`-style sweep, and an optional sideband count. It reuses the PSS
analysis via a `PSSdoPXF` flag and produces a `PXF Analysis` plot with `xf`
(sideband 0) plus `xf_usb<k>`/`xf_lsb<k>` for the upper/lower conversion transfers.

## Verification

The 1 MHz-driven RC low-pass (`R=1k`, `C=1n`), output `b`, input `V1 AC 1`, swept
10 kHz–1 MHz:

```
Index   frequency       mag(xf)
0       1.000000e+04    9.980319e-01
...
20      1.000000e+06    1.571767e-01
```

- The sideband-0 transfer equals the analytic low-pass `1/√(1+(2πfRC)²)`
  (`0.998` → `0.157`) to a worst-case relative error of **1.6e−7**, and it is
  **bit-identical** to the [E-123](Enhancement-123.md) PAC response `mag(b)` at the
  same node — the reciprocity identity holding to the last digit.
- The `xf_usb1` / `xf_lsb1` conversion transfers come back at `~2e−16` — floating-
  point zero: a **linear** circuit does not convert between sidebands. A pumped
  nonlinear circuit fills them, giving the genuine up/down-conversion transfer
  functions through the same adjoint.

`verify_rcpxf.py` asserts `xf` against the analytic transfer and the conversion
sidebands against zero.

## Files changed

| File | Change |
|---|---|
| `ngspice-46/src/include/ngspice/pssdefs.h` | `PSSan.PSSdoPXF`, `PxOutNode`; `PXF_*` param ids |
| `ngspice-46/src/spicelib/analysis/psssetp.c` | `pxf` / `pxf_out` setters + IFparm entries |
| `ngspice-46/src/spicelib/parser/inp2dot.c` | `dot_pxf` — parse the `.pxf` card onto the PSS analysis |
| `ngspice-46/src/spicelib/analysis/dcpss.c` | `pxf_sweep` — per frequency solve the conversion adjoint (`pac_solve_adjoint`) and dot each sideband block with `B0`, emitting the input→output transfer at each sideband |
| `examples/rfpss_examples/rc_pxf.cir`, `verify_rcpxf.py` | `.pxf` example + checks vs. the analytic transfer (== the PAC response by reciprocity) |

## Scope — the RF periodic small-signal suite is complete

With PXF the trio built on the hardened PSS is done: **PAC** (conversion gain),
**Pnoise** (folded device noise), and **PXF** (adjoint transfer). All three share
one conversion-matrix solve and its adjoint. The same dense-solve scale caveat and
stationary-source note apply; the substrate for full cyclostationary noise, phase
noise, and quasi-periodic (multi-tone) extensions is now all in place.
