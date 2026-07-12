# CMC compact-model coverage sweep — Enhancement-160

[Enhancement-159](../../enhancements_doc/Enhancement-159.md) brought up two real
compact models (BSIM4, EKV). This is the comprehensive follow-up: it drives
**every** production CMC (Compact Model Coalition) Verilog-A model bundled with
OpenVAF through the full `openvaf-r → OSDI → ngspice` path and reports a coverage
matrix — like the [E-84](../../enhancements_doc/Enhancement-84.md) LRM sweep, but
for the models people actually tape out with. Model sources are the CMC reference
decks under `OpenVAF-master-20260610/integration_tests/`, **compiled in place, not
copied**, so their licenses stay put.

![coverage matrix + Gummel plot](cmcsweep_coverage.png)

## Result: 19 / 19 compile, 19 / 19 load

Twenty… nineteen real device models across **every major class** compile through
openvaf-r and load in ngspice:

| Class | Models |
|---|---|
| MOSFET | BSIM3, BSIM4, BSIM6, BSIMBULK, EKV, HiSIM2, HiSIMSOTB, MVSG_CMC |
| FinFET | BSIMCMG, BSIMIMG |
| SOI | BSIMSOI, HiSIMHV |
| GaN HEMT | ASMHEMT |
| surface-potential | PSP102, PSP103 |
| bipolar / SiGe HBT | HICUML2, MEXTRAM |
| diode | DIODE, DIODE_CMC |

(OpenVAF's primitive test fixtures — `resistor`, `vccs`, `cccs`,
`current_source`, `amplifier`, `strings` — are not real device models and are
excluded.)

Deeper **conduction + physics validation** is done for a representative model per
class (a full conduction column needs per-model biasing, which is model-specific):

* **BSIM4** vs ngspice's **built-in** BSIM4 → agree to ~2 % (needs `rdsmod=1`).
* **BSIM3** vs ngspice's **built-in** BSIM3 → agree to ~7 %.
* **EKV** → monotonic, saturating I-V (ngspice has no built-in reference).
* **HICUML2** (SiGe HBT) → bipolar current gain **β ≈ 100** (Gummel plot, Panel B).
* **DIODE_CMC** → exponential forward turn-on (× 16 000 over 0.2 → 1.0 V).

## Findings

* **The E-159 internal-node issue is BSIM4-specific, not universal.** BSIM4's
  default `rdsmod=0` leaves its internal drain/source nodes floating (Id = 0)
  because OSDI keeps nodes static; `rdsmod=1` connects them. **BSIM3**, by
  contrast, handles the zero-resistance case fine and conducts out of the box —
  its apparent "zero" at Vgs = 1 V is simply a high default threshold (~1.7 V), so
  it turns on above ~1.5 V and then tracks the built-in model.
* **HiSIMHV** (6 terminals `d,g,s,b,sub,temp`) needs `cosubnode=1` to enable the
  substrate node; instantiated with all six nodes and the default `cosubnode=0`
  its `$fatal` correctly guards the node-count mismatch (which also confirms
  `$fatal` works end-to-end).

## Run it

```
python3 verify_cmcsweep.py     # coverage matrix + cross-class validation (7 checks)
python3 make_cmcsweep_fig.py   # -> cmcsweep_coverage.png
```

The verify compiles all nineteen models (~35 s), so it is **SPARSE-only** (compile
and load are solver-independent) and excluded from the fast regression sweep; run
it directly. The cross-class conduction checks pass under both solvers.

## Why the results matter

Compiling and running the full CMC zoo — 12.6k-line BSIM4, surface-potential PSP,
a GaN HEMT, a SiGe HBT — end to end is the strongest possible statement that
openvaf-r + ngspice is a production-grade Verilog-A/OSDI toolchain, not a
teaching toy. The two findings are exactly the kind of practical gotcha a sweep
like this exists to surface and document.

See [Enhancement-160](../../enhancements_doc/Enhancement-160.md) for the full
write-up.
