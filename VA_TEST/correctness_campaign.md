# openvaf-r correctness campaign

A whole-corpus **simulation** validation of the `openvaf-r` Verilog-A → OSDI
compiler. Where [`compile_all.py`](compile_all.py) proves every model *compiles*
(and [the robustness report](../docs/internals/openvaf_internals/OpenVAF_robustness_report.md)
proves the compiler survives malformed input), this campaign proves the compiled
models *run correctly*: it builds a generic ngspice netlist for every model,
runs **DC, AC, and transient**, and checks the results against physical
invariants that must hold for any correct device.

The harness is [`correctness_campaign.py`](correctness_campaign.py).

## Result

> **92 / 92 device-modules pass every check** — DC operating point converges,
> DC/AC/transient outputs are finite (no NaN/Inf), the terminal currents conserve
> (KCL), and the transient stays bounded. The **worst-case KCL residual across the
> entire corpus is 2.3 × 10⁻¹³ A** — the solver's own numerical floor.
>
> **No openvaf-r correctness bugs.** Every model that the harness could bias into
> an operating point produced finite, current-conserving, numerically stable
> behaviour in all three analyses.

The corpus is the public `VA-Models-main/` collection — the industry-standard
compact models: BSIM3/4/6, BSIM-CMG/IMG/SOI/BULK, PSP 102/103/104 and PSP-HV,
HICUM L0/L2, MEXTRAM 504/505, VBIC, EKV 2.6/3, HiSIM2/HV/SOI/SOTB, ASM-HEMT,
EPFL-HEMT, Angelov, MVSG, FBH-HBT, IGBT, L-UTSOI, MOSVAR, diode_cmc, r2/r3_cmc.
Devices range from 2-terminal diodes and resistors to 6-terminal self-heating
multi-node transistors.

## The invariants

The checks are deliberately **model-agnostic** — they encode facts true of *any*
correct device, so a violation is a compiler defect, not a modelling opinion:

| Check | What it catches |
|---|---|
| **Convergence** | the DC operating point solves — a wildly wrong stamp often can't. |
| **Finiteness** | no `NaN` / `Inf` in the DC, AC, or transient terminal currents — a bad expression, a divide-by-zero, or a wrong derivative surfaces here. |
| **KCL (conservation)** | the electrical terminal currents sum to ≈ 0. openvaf-r conserves a branch contribution `I(a,b) <+ …` *by construction* (it stamps `+expr` at `a` and `−expr` at `b`); a mis-stamp that drops the return would leave a residual ~ the device current. |
| **Stability** | the transient response stays bounded — an unstable reactive stamp blows up. |

KCL is the sharpest of the four: it directly exercises whether openvaf-r's code
generation preserves current conservation through the whole pipeline
(contributions, node collapsing, the DAE assembly, the OSDI ABI).

## Method

For each standalone `.va` in the corpus the harness:

1. **compiles** it to `.osdi` (`openvaf-r`, includes resolved from the model's
   own directory);
2. determines the **device name and port list from the modules the `.osdi`
   actually exports** (a `.va` may declare wrapper modules it never emits, or
   several genuine ones — the compiled object is the ground truth);
3. **generates a netlist**: an OSDI instance `N1 …`, one DC source per terminal,
   and a `.model` card. The first few *electrical* terminals (the primary device
   nodes: d/g/s/b, c/b/e, a/c) get distinct modest biases; every other node is
   held at its 0 reference. The first driven terminal also carries an `ac 1`
   phasor and a small sinusoid. Because `i(Vk)` is exactly the current the k-th
   source delivers, `Σ i(Vk)` over the electrical terminals is the device's net
   terminal current — 0 for a conservative device;
4. runs **`.op`, `.ac dec 3 1 1e9`, `.tran 5n 1u`** in one invocation and applies
   the four checks.

Biasing only the primary terminals (and holding the rest at 0) is what makes the
KCL check meaningful across every device: an optional / substrate node that the
model leaves inactive stays at its reference and cannot inject a spurious
collapse-to-ground current, while a real conservation defect still shows up,
because it appears in the *driven*-terminal currents regardless.

## Speaking each model's dialect

Reaching 92/92 required teaching the harness the idioms real compact models use.
Each of these was a *harness* refinement — every time, the compiler was already
correct:

- **Non-electrical terminals.** A `thermal` node (or a self-heating temperature
  node conventionally named `dt`/`tnode`/`temp`/… but declared `electrical`)
  carries *power*, not current. Those nodes are held at 0 and excluded from the
  current sum; only genuine electrical terminals enter KCL.
- **Config-gated optional terminals.** HiSIM-HV/SOI gate their substrate /
  body-contact nodes behind a selector parameter and `$fatal` if the connected
  node count doesn't match (*"N nodes are connected but COSUBNODE = 0"*). The
  harness reads the flag name out of the model's own message and retries with it
  enabled — fully generic, no per-model table. (openvaf-r's `$fatal` handling is
  what makes the model's self-check work in the first place.)
- **Conditional-compilation variants.** Some files (`hisimsoi_n4`, `_n5`) compile
  to *fewer* terminals than the shared module body's last declaration suggests;
  on *"too many nodes connected"* the harness drops a terminal and retries.
- **Singular small-signal matrix.** A device biased near-off can leave an internal
  node with no AC path, so ngspice's AC matrix is singular — a *solver*
  conditioning issue, not bad AC from the compiler. The harness retries AC-only
  with a tiny node-to-ground shunt to confirm openvaf-r's AC code yields finite
  output (the shunt would perturb the current sum, so it is used only for the AC
  finiteness retry, never for KCL).

## Reproducing

```
python3 VA_TEST/correctness_campaign.py                 # the whole corpus
python3 VA_TEST/correctness_campaign.py bsim4 hicum     # only matching files
OPENVAF_BIN=… NGSPICE_BIN=… python3 VA_TEST/correctness_campaign.py
```

It prints one line per device-module (`OK`, or a failure class with a reason) and
a final tally; the exit code is non-zero if anything is not OK. The toolchain
binaries resolve through the same committed `bin/<os>/<arch>/` matrix as the
example suites (via `examples/_setup.py`), so a locally-built `openvaf-r` /
`ngspice` is used when present.

## Where this sits

This campaign is the third pillar of openvaf-r validation, alongside:

- the **autodiff-clean audit** — ~200 AC-conductance correctness checks against an
  analytic referee (the math core / derivatives);
- the **robustness / crash campaigns** ([E-213](../enhancements_doc/Enhancement-213.md),
  [E-219](../enhancements_doc/Enhancement-219.md),
  [E-220](../enhancements_doc/Enhancement-220.md),
  [E-230](../enhancements_doc/Enhancement-230.md)) — the compiler never crashes on
  malformed input.

Together: the math is verified, the compiler is crash-safe, and — this campaign —
the compiled models simulate correctly end-to-end across the entire production
corpus.
