# The IHP SG13G2 Verilog-A paramset library against openvaf-r and ngspice

**Date:** 2026-09-15. **Target:** the compiler (`openvaf-r`) and the OSDI
side of `ngspice-46` at head `2e6ee686` (after E-640). **Prompt:** a comment
on the project — *"The library of the models make use of parameter set and
hierarchical references in order to provide corner analysis and advanced
statistical analysis. Since the Verilog-A code and the library structure is
compliant with VAMS-LRM maybe you are interested in extending openvaf-r to
support the feature needed in order to compile and expose the models to the
simulator via OSDI interface."* — pointing at
[IHP-Open-PDK `ihp-sg13g2/libs.tech/gnucap/models`](https://github.com/IHP-GmbH/IHP-Open-PDK/tree/dev/ihp-sg13g2/libs.tech/gnucap/models)
(branch `dev`). **Rule:** find and record; the fixes follow as enhancements.

## Summary

The library compiles, runs and agrees with its gnucap reference outputs
once two things are supplied by hand that nothing in the tool chain supplies
today — the corner binding and the statistical draws — and once four bugs
in the existing paramset support are worked around. So the twin-module
design (E-21/E-563/E-565) carries a real PDK's paramsets over PSP103, r3_cmc
and cap_cmom without numerical trouble; what is missing is plumbing around
it, and the bugs the library's spelling of that plumbing uncovered.

| # | finding | where | severity |
|---|---|---|---|
| A1 | the OOMR-to-localparam fold re-renders the **macro-expanded** tree: a macro with a trailing `//` comment swallows the rest of its line, a multi-line `\` macro glues tokens and leaks the `\` — every paramset with an out-of-module reference over r3_cmc or PSP103 fails to compile | openvaf-r, `hir/src/elaborate.rs` `elaborate_paramset_consts` | correctness — **fixed in [E-641](../../enhancements_doc/Enhancement-641.md)** (in the preprocessor: the comment is not macro text, the separators are kept) |
| A2 | a literal seed (`$rdist_normal(1, 0, 1)`) is refused everywhere, though LRM Syntax 9-9 allows `[sign] decimal_number`; the library also uses `seed + 3` | openvaf-r, hir_ty | compliance |
| B1 | paramset overload selection parses `exclude {0}` as "always satisfied", so a member whose parameter carries an `exclude` never applies; and it range-checks and counts the **module's** pass-through parameters as if they were the paramset's own (6.4.2: "only the ranges of the paramset's own parameters") — which is also why `.model rsil rsil` with nothing given picks the mismatch member `rsil__2` instead of reporting the tie | ngspice, `osdi/osdiinit.c` `osdi_range_accepts`, `osdi_select_paramset_overload` | correctness |
| B2 | the same selection re-evaluates each bound from its E-558 text with `INPevaluate`, one ulp off the compiler's double: `parameter real l = 0.96e-6 from [0.96e-6:10e-6)` refuses its own default (`0.5e-6` happens to pass) | ngspice, `osdi/osdiinit.c` `osdi_range_bound` | correctness |
| C1 | a paramset's own parameters are model-card-only: `n1 … rsil l=0.5u w=0.5u mm_ok=0` is refused ("it is a model parameter of this device"); a SPICE device library needs them on the instance line | OSDI export + ngspice | feature gap |
| C2 | a bound module parameter that differs from a paramset parameter only in case (PSP's `SWSOA`, the paramset's `swsoa`) draws "declared more than once differing only in case" although the bound one is fixed and cannot be set | ngspice | cosmetic |
| L1 | `.LEVEL = 103.8.2;` in the four MOS paramset files is not a number (PSP's `LEVEL` is an integer parameter); `Rparasitic`'s gnucap reference is 205.95 Ω for `R=100` at 27 °C, which needs `$simparam("tnom", 27)` to evaluate to something other than 27 | the library | upstream |

And, beyond bugs, what "compile and expose via OSDI" needs (§ *Features*):
a compile-time binding of the corner instance name to a corner module; the
§6.4.1 statistical route (`"global"`/`"instance"` draws in paramset and
localparam context, with a per-trial seed and an instance ordinal from the
simulator, and a `_stat` corner's `seed` parameter importable); instance-line
paramset parameters (C1); and, for the wrapper modules only, a decision on
gnucap's module overloading.

## The library

Eighteen files in `models/`, of which the `Makefile` builds seven plugins with
`gnucap-mg-vams` and, through a `--dump` of each paramset to a flat module,
OSDI objects with `openvaf-r` (the Makefile already names it). The pieces:

- **Device models** in `libs.tech/verilog-a/` — PSP103 (`psp103.va`,
  `psp103_nqs.va`), r3_cmc, cap_cmomi, cap_cmomf — plus two
  Distiller-generated wrappers of ngspice's own resistor and capacitor
  (`resistor.va` → `sp_resistor`, `capacitor.va` → `sp_capacitor`). All of
  them compile with the repo's `openvaf-r` as they are (IHP's own ngspice
  flow, `openvaf-compile-va.sh`, does exactly that).
- **Paramset files** `resistor_paramset.va`, `capacitor_paramset.va`,
  `sg13g2_mos{lv,hv}_paramset.va`, `sg13g2_mos{lv,hv}_rf_paramset.va`:
  `` `pragma modelgen nogen-module ``, `` `include "psp103.va" ``, then
  paramsets with their own parameters and `localparam`s, overloaded on a
  discriminator (`rsil` twice, `mm_ok from [0:0]` and `[1:1]`;
  `sg13g2_lv_nmos_psp` over `PSP103VA` with `rfmode from [0:0]` in one file
  and over `PSPNQS103VA` with `[1:1]` in the RF file), and overrides that
  read another module's local parameters:

  ```verilog
  paramset rsil r3_cmc
      parameter real w = 0.5e-6 from [0.5e-6:10e-6);
      parameter integer mm_ok = 1 from [1:1];
      localparam real weff = w + corner_res.dw_par_rsil;
      localparam real a0 = 0.5 * (leff + lhead) * w - (postsim > 0) * w * ax * 1e-6;
      .w = weff;
      .rsh = corner_res.rsh_rsil;
      .nsig_rsh = corner_res.nsig_rsh_rsil;
      .sig_rsh  = res_stat_param.drsh_rsil;
      .nsmm_rsh = res_mm.nsmm_rsh_rsil;
      …
  endparamset
  ```

- **Corner files** `cornerRES.va`, `cornerCAP.va`, `cornerMOS{lv,hv}.va`:
  port-less modules of localparams, one per corner (`res_typ`, `res_bcs`,
  `res_wcs`; `moslv_tt … moslv_fs`), a statistical corner with a `seed`
  parameter and global draws, and a mismatch module with instance draws:

  ```verilog
  module res_stat();
      parameter integer seed = 1;
      localparam real nsig_rsh_rsil = $rdist_normal(seed,   0, 1, "global");
      localparam real nsig_w_rsil   = $rdist_normal(seed+1, 0, 1, "global");
      …
  endmodule
  module res_mm();
      localparam real nsmm_rsh_rsil = $rdist_normal(1, 0.0, 1.0, "instance");
      …
  endmodule
  ```

- **The corner is chosen by the netlist.** `corner_res` is not a module: the
  gnucap deck instantiates one corner module under that fixed instance name,
  and the paramsets' `corner_res.X` resolve through it —

  ```
  include ../../../models/cornerRES.va
  res_typ corner_res();            // or res_bcs, res_wcs, res_stat
  tb_res_mc #(.mm_ok(1)) tb();
  dc $seed 1 1000 1 basic          // Monte-Carlo trials: sweep the seed
  ```

  `res_stat_param.X` and `res_mm.X`, by contrast, name modules directly (the
  LRM's `semicoCMOS.tox` idiom, which E-563 folds).
- **Wrapper modules** `sg13g2_mos{lv,hv}_module.va` (included as source by
  the decks, not compiled to plugins): `sg13_lv_nmos` computes `as/ad/ps/pd`
  from `w`, `l`, `ng` and instantiates the paramset; it is declared **twice**
  with `mm_ok from [0:0]` and `[1:1]` — module overloading, a gnucap
  extension the LRM does not have (6.4.2 overloads paramsets only) — and the
  mismatch twin draws `localparam real w_mm = $rdist_normal(1, w, 4e-9,
  "instance")` at module scope.

## What was read and run

The seven model files, the four corner files, the two wrapper modules, the
include trees of r3_cmc (2 files) and PSP103 (14 files), the gnucap
`README.md`, the resistor and moslv testbenches and their reference outputs
(`tests/gnucap/{resistor,moslv}/ref/*.gc.out`), all fetched from branch
`dev` into the session scratchpad (`ihp/`). Each paramset file was compiled
as it is, then through a small inliner (`ihp/inline.py`) that replaces
`corner_res.X` with the literal value of `res_typ`'s `X` (and `moslv_tt`'s
for the MOS files) — which sidesteps A1 by leaving no OOMR for the fold to
render — then with every `$rdist_normal(seed, m, s, "…")` replaced by `m`,
then with the ranges B1/B2 trip on edited, and run in the repo's `ngspice -b`
against the gnucap numbers. Minimal reproducers for A1, A2, B1, B2 are in
`pset/t3.py … t6.py` beside the earlier probes of the §6.4.1 idiom
(`pset/t.py`, from before the library was known).

Results of the working configuration (typical corner, draws at their means,
`w`/`l`/`mm_ok` on the `.model` card):

| gnucap test | quantity | gnucap reference | ngspice + OSDI |
|---|---|---|---|
| `tb_res_basic_typ` | `v(r1)` rsil 0.5µ/0.5µ at 1 mA | 0.024731 | 0.024731 |
| | `v(r2)` rppd | 0.39397 | 0.39397 |
| | `v(r3)` rhigh 0.96µ/0.5µ | 3.4375 | 3.4375 |
| | `v(r4)` Rparasitic R=100 | 0.20595 | 0.1 (see L1) |
| `tb_moslv_nmos_id_vd_ng1` | Id at Vd = Vg = 1.2 V, w = 0.3µ, l = 0.34µ | 85.558 µA | 85.558 µA |

`capacitor_paramset.va` compiles the same way (not run: its testbenches use
gnucap plugins that have no ngspice twin here).

## A1 — the OOMR fold re-renders macro-expanded text

*Fixed in [E-641](../../enhancements_doc/Enhancement-641.md): the preprocessor drops a body's trailing `//` comment (19.3.1) and keeps the trivia after an argument reference, a macro call and an `` `include ``, so the expanded stream re-renders as it means; the IHP resistor and PSP paramsets compile through the fold and reproduce gnucap's numbers.*

`elaborate_paramset_consts` (E-563) replaces each `module.localparam` path
with `(text)` and re-parses **the whole tree's text** as a virtual
`<file>__paramset.va`. That text is the preprocessed token stream, and two
things a macro body can carry do not survive being laid out on one line:

```verilog
`define TABS 273.15      // 0C in K
`define twice(x, blk) \
    begin : blk \
        real t; \
        t = (x); \
        g = g + t; \
    end
module res_va(p, n);
    …
    analog begin
        tk = `TABS + 27.0;
        `twice(0.0, blkA)
        …
module consts (); localparam real rsh = 7.0; endmodule
paramset rsil res_va;
    parameter real w = 1e-6;
    .r = consts.rsh / w * 1e-6;     // one OOMR is enough to trigger the re-render
endparamset
```

```
error: unexpected token identifier; expected ';'
    --> /macrofold.va__paramset.va:300:9
299 |         tk = 273.15      // 0C in K+ 27.0;
error: 't' was not found in the current scope
301 |         begin : blkAreal t; \
```

The comment kept in the macro's text (the preprocessor treats it as trivia,
so the normal path is fine — `r3_cmc.va` compiles standalone) is emitted
inline and comments out `+ 27.0;`; the continuation lines lose their
newlines, so `blkA` and `real` touch, and the `\` is printed. r3_cmc's
`r3_cmc_macros.include` has both (`TABS_NIST2004 … // (NIST2004) 0C in K`,
`psibi(…) \`), PSP103's macros have the second, so every IHP paramset with
an OOMR dies here:

```
error: unexpected token 'end'; expected ';'
    --> /res_typ_full.va__paramset.va:801:5
800 |         tiniK    = 273.15                 // (NIST2004) 0C in K+tnom;
```

Without an OOMR the fold returns early (`holes.is_empty()`) and nothing is
re-rendered, which is why the constant-only paramset suites never saw it.
The renderer has to drop comment trivia and separate tokens (or substitute
in the original source text before preprocessing) — either way the
re-parsed file must mean what the tree meant.

Repro: `pset/t3.py` (`macrofold.va`), `ihp/bound/res_typ_full.va`.

## A2 — a literal or computed seed is refused

```verilog
g = 1.0 + 0.01 * $rdist_normal(7, 0, 1);          // Syntax 9-9: seed ::= … | [sign] decimal_number
g = 1.0 + 0.01 * $rdist_normal(seed + 1, 0, 1);   // the library's spelling (beyond the LRM)
```

```
error: type mismatch: expected integer variable reference or integer parameter ref but found integer literal
error: type mismatch: expected integer variable reference or integer parameter ref but found integer value
```

Both forms fail in the analog block as well as in a paramset. The LRM's own
§6.4.1 example seeds with literals (`$rdist_normal(1,0,1n,"global")`), and
under the E-10 design (a draw is a pure function of seed and call site, the
seed variable is never written back) there is no reason to insist on an
lvalue: any constant integer expression can serve as the seed.

Repro: `pset/t2.py`, `pset/t6.py`.

## B1 — overload selection: `exclude {…}` and the module's pass-through parameters

`osdi_range_accepts` walks the E-558 range text. After `exclude` it calls
`osdi_range_bound` on `{0}`, which `INPevaluate` cannot read, returns the
`NAN` fallback, and the caller takes `isnan(x)` as "satisfied" — for an
`exclude`, that is "excluded":

```verilog
parameter integer type = -1 from [-1:1] exclude 0;   // r3_cmc's MPIty macro
```

```
Error: no paramset 'rs' applies to .model rs0 (LRM 6.4.2): rs: the default type = -1 is outside from [-1:1] exclude {0}; …
```

`type` is not the paramset's parameter at all: it is r3_cmc's, passed
through unbound. 6.4.2 ends with "The simulator shall consider only the
ranges of the paramset's own parameters when choosing a paramset", but the
default-range loop runs over every non-`PARA_FLAG_FIXED` parameter of the
member, and the "fewest un-overridden parameters" count does the same —
which is how `.model rsil rsil` with nothing given resolves to `rsil__2`
without the ambiguity error: the mismatch member binds six more module
parameters (`nsmm_*`, `smm_*`), so the plain member has six more
"un-overridden" ones. Both members have the same six own parameters, and
the LRM's answer for that card is the tie error.

Repro: `pset/t5.py` (`exclude`), `ihp/out/tb_res_wa.cir` (the silent pick).

## B2 — the bound text is one ulp off the default

```verilog
parameter real l = 0.96e-6 from [0.96e-6:10e-6);
```

```
Error: no paramset 'rs' applies to .model rs0 (LRM 6.4.2): rs: the default l = 9.6e-07 is outside from [0.96e-6:10e-6); …
```

The same spelling on both sides; `0.96u` and `9.6e-7` fail the same way,
`0.5e-6` passes. The default is the compiler's correctly rounded double
(`param_defaults`); the bound is `INPevaluate` of the text, whose
mantissa-then-scale arithmetic lands an ulp above it, and `v >= lo` fails.
The bounds are numbers the compiler already has; exporting them (or, at the
least, reading a plain number with `strtod` and reserving `INPevaluate` for
SI suffixes) removes the disagreement. The same `INPevaluate` path is used
for the card's own values, so a `.model … l=0.96e-6` value is compared with
the same skew against a `strtod`-parsed bound if only one side is changed —
both sides need to be parsed the same way.

Repro: `pset/t5.py` (`e6`, `u`, `e7`, `plain`).

## C1 — paramset parameters are not on the instance line

```
n1 n1 0 0 rsil l=0.5u w=0.5u mm_ok=0
Error … unknown parameter (l): it is a model parameter of this device -- set it on the .model card, not on the instance line
```

A paramset's own parameters become the twin's model parameters, and a
`.model` card is the only place ngspice can set them. The gnucap decks give
`w`, `l`, `ng`, `mm_ok` per instance, as any SPICE device library would
(`.model` for the corner, the instance line for the geometry). OSDI lets a
parameter be both (`type="instance"`, E-62), so the twin can mark every
paramset parameter instance-settable with the card value as its default.
Selection by an instance-line value (`mm_ok=1` on the instance while the
card says nothing) is a further step — ngspice would have to map that
instance to a sibling member's card — that `.model rsil_mm rsil mm_ok=1`
cards make unnecessary for this library.

## C2 — a fixed parameter's case-twin warns

```
Warning: sg13g2_lv_nmos_psp: model parameter 'swsoa' is declared more than once differing only in case; SPICE cannot tell the names apart, so only one of them can be set from a netlist.
```

The paramset declares `parameter real swsoa` and binds PSP's `SWSOA` to it.
The bound `SWSOA` is `PARA_FLAG_FIXED` and cannot be set from a netlist, so
there is nothing ambiguous to warn about. The check (E-3xx's case-collision
warning) should skip fixed parameters.

## L1 — library notes for upstream

- `.LEVEL = 103.8.2;` in all four MOS paramset files: `103.8.2` is not a
  number (`103.8` followed by `.2`); PSP declares `LEVEL` as an integer with
  default 103. openvaf-r reports "unexpected token integer; expected
  identifier" at the second dot; gnucap-mg-vams evidently accepts it. `.LEVEL
  = 103;` is what is meant.
- `Rparasitic #(.R(100))` at 27 °C: the gnucap reference reads 0.20595 V at
  1 mA, i.e. 205.95 Ω = 100 × (1 + 0.00353 × 300.15). `sp_resistor` computes
  `difference = temp − tnom` with `tnom = $simparam("tnom", 27) + 273.15`,
  so that value needs the simparam to come back as −273.15 or the
  initialiser not to run. ngspice with the OSDI twin gives 100 Ω. Worth a
  question to the authors rather than a change here.
- `parameter integer ng = 1 from [1:1000); // TODO: upper inf bound doesn't
  work for integers` — it does here since E-635.

## Features

What the library needs beyond the fixes above, in the order they unblock
things:

1. **Corner binding at compile time.** `corner_res.X` is an OOMR through an
   instance the netlist creates; an OSDI object is compiled before any
   netlist exists. A binding on the command line (`--bind
   corner_res=res_typ`) or a root file containing `res_typ corner_res();`
   would resolve the instance name to a module for the E-563 fold, giving
   one `.osdi` per corner — which is how a SPICE user selects corners anyway
   (`.lib cornerRES.lib res_typ` in IHP's own ngspice kit).
2. **The §6.4.1 statistical route.** `$rdist_*`/`$arandom` with constant
   arguments inside a paramset override and inside a localparam that a
   paramset reaches (E-545 refuses both today, by design); the `"global"`
   draw salted by a per-trial seed, the `"instance"` draw also by an
   instance ordinal — neither exists in OSDI, so ngspice has to supply them
   (the E-535 osdimc path already draws per run and per instance and can
   lend its plumbing); and a `_stat` corner's `seed` parameter, a non-local
   parameter the localparams depend on, imported as a model parameter of
   the twin so `alter`/osdimc can re-seed each trial. With the E-10 RNG
   (pure in seed and call site) "one value per trial shared by every
   instance" falls out for free once the trial seed is mixed in.
3. **Instance-line paramset parameters** (C1).
4. **The wrapper modules.** `sg13_lv_nmos` twice, split on `mm_ok`, is
   module overloading — not LRM; and `$rdist_normal(…, "instance")` at
   module scope is the §6.4.1 rule stretched to a module. Either accept
   overloaded modules as the paramset rule already is (E-565's selection
   generalised), or leave the wrappers to `.subckt`, where IHP's ngspice kit
   already has them.

## Verified correct along the way

- `` `pragma modelgen nogen-module `` is ignored, as an unknown pragma
  should be.
- Paramsets with their own `localparam`s, in terms of the paramset's
  parameters and of each other (`weff`, `leff`, `a0`, `a`, `rz`), including
  `(postsim > 0) * w` boolean arithmetic; overloading declared twice per
  name with integer discriminator ranges; a paramset targeting a module
  brought in through `` `include `` behind a `` `pragma ``; a paramset over a
  module with 300+ parameters (PSP103) and one with `aliasparam`s
  (`sp_resistor`'s `r`, `tc1`, `noise`, `dw`, `dlr`, …).
- The twins' numerics: rsil/rppd/rhigh at 1 mA and PSP nmos Id–Vd agree
  with gnucap to the printed digits (table above); the `(1 - 1 / (1.5 *
  leff * 1e6 + 1))` and `rzspec / w - (postsim > 0) * rqrc / w` expressions
  land in the right places.
- With `l`, `w`, `mm_ok` on the `.model` card and the member ranges edited
  around B1/B2, overload selection picks the `mm_ok` member the card asks
  for and reports it (`Note: .model rsil0: paramset 'rsil' resolved to its
  member 'rsil'`).
- Module-name OOMRs (`res_stat_param.drsh_rsil`, `res_mm.dl_mm_rsil`) fold
  as E-563 intends when the text contains no macro-expanded lines.
- The plain models (`psp103.va`, `psp103_nqs.va`, `r3_cmc.va`,
  `cap_cmomi.va`, `cap_cmomf.va`) build with `-D__NGSPICE__` in 0.1–3.2 s.

Not exercised: the HV files (same structure as LV, not run), the RF
paramsets in ngspice (the family name is shared with the non-RF file, so
loading both `.osdi` objects would need both in one compile unit), the
capacitor testbenches, gnucap itself.
