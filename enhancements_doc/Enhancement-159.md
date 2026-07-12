# Enhancement-159 — Real production compact-model bring-up (BSIM4 + EKV)

Every enhancement so far has been validated on purpose-built teaching models. The
real question for a Verilog-A toolchain is: *does it run the models people
actually tape out with?* — the CMC (Compact Model Coalition) standards: BSIM4,
PSP, HICUM, BSIM-CMG, and the rest. This enhancement brings up two of them through
the full `openvaf-r → OSDI → ngspice` path and validates their physics, proving
the toolchain is production-real. It also surfaced a genuine, general finding
about OSDI internal nodes.

The model sources are the CMC reference decks already bundled with OpenVAF
(`OpenVAF-master-20260610/integration_tests/`); they are compiled **in place, not
copied**, so their licenses stay with them.

## BSIM4 — validated against ngspice's own built-in

[BSIM4](../OpenVAF-master-20260610/integration_tests/BSIM4/bsim4.va) is the
industry-standard bulk MOSFET — **~12,600 lines** of Verilog-A. It compiles
through openvaf-r in ~6 s to a 423 kB `.osdi` and loads in ngspice. Because
ngspice has a **built-in** BSIM4, the validation is a rigorous self-check: the
OSDI-compiled BSIM4.8 and the native BSIM4.8.3 are the *same model*, so they must
agree. They do — to **~2 %** across the `Id(Vds)` output family and **~4.5 %** on
the `Id(Vgs)` transfer curve, the residual being the BSIM4.8 → 4.8.3 point release.

![OSDI compact models](../examples/compactmodels_examples/compactmodels_iv.png)

Panel A overlays the OSDI BSIM4 (markers) on ngspice's built-in BSIM4 (lines):
they track across the whole family — a direct, end-to-end confirmation that
openvaf-r's code generation and ngspice's OSDI matrix/RHS stamping are correct on
a real 12.6k-line model.

## The internal-node finding

Bringing BSIM4 up surfaced something general about OSDI MOSFET models:

> **OSDI keeps every internal node static — there is no dynamic node collapsing.**

BSIM4 has internal drain/source nodes (`di`, `si`) joined to the external `d`/`s`
by the source/drain series resistance. With the default `rdsmod=0`, the model
expects the simulator to **collapse** `di→d` and `si→s` (zero resistance); the
built-in BSIM4 does exactly that. OSDI cannot — every node declared at setup stays
in the matrix — so `di`/`si` are left **floating**, no current can reach the
terminals, and the device conducts **exactly zero**. The model's own source even
carries `TODO` comments at the S/D-conductance code noting that all nodes are kept
static.

The fix is to enable the external series-resistance nodes with **`rdsmod=1`**: the
model then connects `di`–`d` and `si`–`s`, near-shorting them (`1×10³` mho ≈ 1 mΩ,
negligible) when no S/D geometry is given. ngspice even prints
`Drain diffusion conductance reset to 1.0e3 mho`, confirming the mechanism. So
`rdsmod=1` is the documented way to use these OSDI MOSFET models. The verify pins
this both ways: with `rdsmod=1` the device conducts 1.18 mA; with the default
`rdsmod=0` it conducts 0.

## EKV — a model ngspice has no built-in for

[EKV](../OpenVAF-master-20260610/integration_tests/EKV/ekv.va) (EPFL's compact
MOSFET, ~840 lines) is a model ngspice **cannot** simulate natively — so OSDI here
genuinely extends ngspice's device set beyond its compiled-in models. It works out
of the box (no `rdsmod` wrinkle) and gives textbook saturation curves (Panel B):
drain current rises with gate overdrive and saturates once `Vds` exceeds it.

## Verification

[`examples/compactmodels_examples/verify_compactmodels.py`](../examples/compactmodels_examples/verify_compactmodels.py),
under **both** the Sparse and KLU solvers:

- **[1]** BSIM4 (12.6k lines) compiles through openvaf-r and loads as OSDI.
- **[2]** with `rdsmod=1` the OSDI BSIM4 conducts a physical current (1.18 mA).
- **[3]** the finding: with the default `rdsmod=0` the internal S/D nodes float → Id = 0.
- **[4]** the OSDI BSIM4 output family matches built-in BSIM4 to < 5 %.
- **[5]** the OSDI BSIM4 transfer curve matches built-in BSIM4 to < 6 %.
- **[6]** EKV (no ngspice built-in) conducts, rises with Vgs, and saturates in Vds.

This is a validation/example enhancement — it exercises the existing toolchain on
real models and needs no ngspice/openvaf source change.

## Scope and follow-ups

The bundled CMC suite also includes BSIM3/6, BSIMSOI, BSIM-CMG, PSP102/103,
HICUM/L2, HiSIM2/HV/SOTB, ASMHEMT (GaN), MVSG, MEXTRAM, and the CMC diode —
extending this bring-up model by model is the natural continuation. The
internal-node-collapse limitation is inherent to OSDI's static-node ABI; teaching
openvaf-r to do compile-time **node collapsing** (so `V(a,b) <+ 0` merges the
nodes and `rdsmod=0` works) would be a substantial compiler enhancement of its own.
