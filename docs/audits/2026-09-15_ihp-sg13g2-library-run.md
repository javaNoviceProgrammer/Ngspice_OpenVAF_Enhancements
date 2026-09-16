# The IHP SG13G2 Verilog-A paramset library, compiled with openvaf-r and run on ngspice

**Date:** 2026-09-15, at head `e1977ed5` (after E-641…E-644, the four
enhancements the [hunt of the same day](../bug_hunts/2026-09-15_ihp-sg13g2-paramset-library.md)
led to). **Library:** [IHP-Open-PDK `ihp-sg13g2/libs.tech/gnucap/models`](https://github.com/IHP-GmbH/IHP-Open-PDK/tree/dev/ihp-sg13g2/libs.tech/gnucap/models)
(branch `dev`) — seven paramset build units over PSP103, PSP103-NQS,
r3_cmc, cap_cmomi, cap_cmomf and two Distiller wrappers of ngspice's own
resistor and capacitor, with corner modules and gnucap testbenches. **Repro:**
[`2026-09-15_repro-ihp/`](2026-09-15_repro-ihp/) — `fetch.sh` (the sources
and reference outputs, not vendored), `build_all.py` (26 objects),
`run_all.py` (66 comparisons), `results.log`.

## Result

Every model in the library compiles, and every gnucap testbench that does
not need the statistical route reproduces gnucap's own reference numbers on
ngspice:

| what | objects / decks | agreement with the gnucap references |
|---|---|---|
| resistors `rsil`, `rppd`, `rhigh` (r3_cmc), `Rparasitic`, `ptap1`, `ntap1` (sp_resistor) | 3 corners typ/bcs/wcs | node voltages at 1 mA to the 5 digits the references print (max 2.3e-5 relative) |
| capacitors `cmim_core` (sp_capacitor), `cparasitic`, `cmomi`, `cmomf` | 3 corners | C from the −3 dB cutoff: cmim 1.05671 pF vs 1.05672, the rfcmim RLC network 1.05671 vs 1.05671, cmomi 26.1664 fF vs 26.1664, cmomf 39.812 fF vs 39.812 (typ); bcs/wcs alike |
| MOS `sg13g2_lv_{n,p}mos_psp`, `sg13g2_hv_{n,p}mos_psp` over PSP103 and PSP103-NQS | 5 corners × {lv, hv} × {psp, nqs} = 20 objects | inverter transfer curves: past the switching point (Vin ≥ 0.6 V) v(out) to 4e-6…4e-4 V and I(vdd) to ≤ 5e-4 relative; Id–Vd (366 points, ng = 1…4, nmos and pmos): ≤ 1.0e-3 relative at every point with I > 10⁻³ Imax, ≤ 3e-5 at Vd = 1.2 V |

66 of 66 comparisons; 26 objects compile in 0.2–4.9 s each (37.6 MB in
all). Each `.osdi` holds the whole family of the file — `rsil` and
`rsil__2` (mismatch on/off), `sg13g2_lv_nmos_psp` and `_pmos_psp` — and the
decks are written the way a SPICE library is used: **one `.model` card per
device, the geometry on the instance line**, `n1 a 0 0 0 rsil l=0.5u w=0.5u
mm_ok=0`, the member selected per instance (E-644).

## How the decks were built

The gnucap decks are Verilog-AMS; the translations are ordinary SPICE:

- `tb_res_basic`: `.model rsil rsil` etc., `l`/`w`/`mm_ok` on the instance
  lines, 1 mA sources.
- `tb_cap_cutoff`, `tb_cap_cmomi/f`: `ac dec 1000 1e6 1e9`, `meas ac fcut
  when vm(out)=0.707`, C = 1/(2π·fcut·100 kΩ) as the gnucap deck computes
  it. The `cap_cmim` (55 mΩ + `cmim_core`) and `cap_rfcmim` wrapper modules
  — an RLC network whose element values are `localparam` formulas of `l`,
  `w`, `wfeed` — are `.subckt`s with the same formulas as `.param`s.
- `tb_mos*_inv`, `tb_mos*_{n,p}mos_id_vd`: the `sg13_{lv,hv}_{n,p}mos`
  wrapper modules (as/ad/ps/pd from `w`, `ng`, `z1`, `z2` with the
  `ng/2`, `ng%2` integer arithmetic) are `.subckt`s with `floor()` in the
  `.param`s; `dc vin 0 1.2 0.02` and `dc vd 0 1.2 0.02 vg 0.2 1.2 0.2`
  (negated for pmos) exactly as the gnucap decks sweep.

## What the tool chain does not do yet, and how the run got past it

1. **The corner binding.** `corner_res`, `corner_cap`, `corner_moslv`,
   `corner_moshv` are *instances* the gnucap deck creates — `res_typ
   corner_res();` — and the paramsets' `corner_res.rsh_rsil` resolve through
   them. An OSDI object is compiled before any netlist exists, so the run
   binds them textually: `corner_res.` → `res_typ.` and the constant corner
   modules included, one object per corner (`resistor_res_typ.osdi`, …).
   This is *Features 1* of the hunt — a `--bind corner_res=res_typ` (or a
   root file) would make the compiler do exactly this.
2. **The statistical route.** The `_stat` corners (`$rdist_normal(seed +
   k, 0, σ, "global")` in localparams, a `seed` parameter swept by gnucap's
   `dc $seed 1 1000 1`) and the mismatch modules (`res_mm`, `cap_mm`:
   `$rdist_normal(k, 0, 1, "instance")`) are E-545's "random draw is not
   allowed in constants". The run leaves the `_stat` corners out and
   replaces the mismatch modules' draws by their means (mismatch off), so
   the `mm_ok=1` members compile and select but draw nothing. The eleven
   `*_mc_*` decks were therefore not run. This is *Features 2* of the hunt.
3. **Two library slips beyond the hunt's L1** (`.LEVEL = 103.8.2;`, the
   `Rparasitic` reference): `sg13g2_moshv_rf_paramset.va` line 434 says
   `.LEVEL = 108.3.2;` (108 for 103), and `cornerMOShv.va`'s `moshv_fs`
   declares `parameter real` where every other corner says `localparam
   real` — LRM 6.4.1 allows a paramset a hierarchical reference to a
   *local* parameter only, and the compiler refuses the non-local one as
   the clause says. The run reads both as what was meant.

## Two things in the gnucap references, not in the models

- **Rparasitic** (`sp_resistor` with `R=100`) at 27 °C: gnucap prints
  0.20595 V at 1 mA, i.e. 205.95 Ω = 100 × (1 + 0.00353 × 300.15); ngspice
  gives 100 Ω. `sp_resistor` computes `difference = temp − tnom` with `tnom
  = $simparam("tnom", 27) + 273.15`, so gnucap's number needs that simparam
  to come back as something other than 27 (hunt L1).
- **The inverter references below the switching point.** With the NMOS
  off (Vin = 0), gnucap's PSP reference draws 40 nA from the supply
  (v(out) = 1.1998 V instead of 1.2000), and its PSP-NQS reference draws
  **10 µA** (v(out) = 1.15 V; for the ss corner 0.263 V at Vin = 0.5 where
  the PSP reference and ngspice say 0.69). ngspice draws 0.06 nA in both and
  gives the NQS inverter the same dc curve as the QS one — which is what
  the NQS model is (it adds dynamics, not dc current). The comparison
  therefore starts at Vin = 0.6 V; from there the two simulators agree to
  microvolts. The gnucap decks carry `options itl6=150 // TODO: revisit
  iteration limit and convergence issues`.

Also visible: gnucap prints 0 for currents below ~10⁻¹¹ A (ngspice prints
the leakage), and the Id–Vd curves' worst point (1e-3 relative) is
always in the linear region at the highest Vg, Vd ≈ 0.1 V, with everything
else at ≤ 3e-5 — most likely gnucap's dc iteration tolerance rather than
the model.

## To reproduce

```bash
cd docs/audits/2026-09-15_repro-ihp
./fetch.sh          # gh api, ~0.5 MB of sources + the reference outputs, into work/
python3 build_all.py   # 26 .osdi under work/out
python3 run_all.py     # the 66 comparisons; decks and data under work/run
```

`OPENVAF_BIN` / `NGSPICE_BIN` override the repo builds.
