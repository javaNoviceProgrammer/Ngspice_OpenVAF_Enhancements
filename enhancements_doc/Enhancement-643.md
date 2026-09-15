# Enhancement-643: a netlist number is the double its text names, and a paramset is selected by its own parameters (IHP hunt B1/B2)

**Scope:** B1 and B2 of the
[2026-09-15 IHP SG13G2 hunt](../docs/bug_hunts/2026-09-15_ihp-sg13g2-paramset-library.md).
ngspice: `src/spicelib/parser/inpeval.c` (`INPdecimal`, a correctly rounded
literal; `INPevaluate`, `INPevaluate2` and the three `INPevaluateRKM_*`
through it), `src/frontend/parser/numparse.c` (`ft_numparse`: `alter`,
`let`, `print`, `.meas`), `src/frontend/numparam/xpressn.c` (suffixed
literals in `.param` expressions), `src/osdi/osdiinit.c` (value sets in a
range text; the selection judges and counts the paramset's own parameters;
the tie message names what selects), `src/osdi/osdiregistry.c` +
`src/include/ngspice/osdiitf.h` (the `OSDI_PARAMSET_OWN` table). Compiler:
`openvaf/syntax/src/ast/expr_ext.rs` (a scaled literal parsed as one
number), `openvaf/hir/src/lib.rs` (`Module::paramset_decl_range`),
`openvaf/sim_back/src/module_info.rs` (`ParamInfo::paramset_own`),
`openvaf/osdi/src/{metadata,lib}.rs` (the table). Suites:
`hbconv_examples` (the loosened bound moved to 1e-7 — the deck's residual
floor sits at 3.3e-8 with correctly rounded inputs) and
`inputguard_examples` (`0e400` is zero) updated; new
[`cardbound_examples`](../examples/cardbound_examples/) (10 checks per
solver). **Both sides.**

**Suites:** `cardbound_examples` 10 of 10 per solver, both solvers (7 fail
on the E-642 binaries); `paramsetoverload`, `paramrange`, `intrange`,
`paramset` green; workspace `cargo test` green; full sweep 516 of 516.

## What was wrong

**B2 — wider than the hunt saw it.** Every ngspice number parser computed
`mantissa × pow(10, exponent)`: the digits accumulated into a double, then
one multiplication — two roundings. For a large share of ordinary
spellings the result is an ulp off the nearest double:

| text | `INPevaluate` | nearest double |
|---|---|---|
| `1.2` | 1.2000000000000002 | 1.2 |
| `3.3` | 3.3000000000000003 | 3.3 |
| `0.96e-6`, `0.96u`, `9.6e-7` | 9.600000000000001e-07 | 9.6e-07 |
| `10e-6` | 9.999999999999999e-06 | 1e-05 |
| `0.34u` | 3.4000000000000003e-07 | 3.4e-07 |

The compiler reads a plain literal correctly (Rust's `parse`), so a card
value **at a declared bound** was refused by the model's own range check —
`parameter real vmax = 1.0 from [0:1.2]` with `.model … vmax=1.2` gave
`Parameter vmax of 'mm' is out of bounds (value 1.2; range from [0:1.2])`
— and the paramset selection, which re-reads a bound's text through the
same parser, judged `l = 0.96e-6 from [0.96e-6:…)` outside its own range.
The compiler's *scaled* literals had the same flaw the other way round:
`1.1u` was `1.1 * 1e-6`, an ulp off for 28 % of such spellings (`0.1n`,
`0.34u`, `1.1u`, …), so a correctly parsed card value could miss a
compiler bound too. numparam (`.param w=1.1u`) multiplied by the suffix as
well; `ft_numparse` (`alter`, `let`, `print`) added the fraction to the
integer part and multiplied.

**B1.** `osdi_range_accepts` read the E-558 range text bound by bound and
knew `from [a:b)` and a bare value; the compiler writes every single-value
constraint as a set — `exclude {0}`, `from {1, 2, 4}` (E-589) — which the
bound reader turned into one unparseable token, and an unparseable bound
counts as satisfied. For an `exclude` that meant *every* value was
excluded: r3_cmc's `type from [-1:1] exclude 0` disqualified each IHP
resistor paramset at its own default. And the selection ran its range
check and its "fewest un-overridden parameters" count over every non-fixed
parameter of the member — the target module's pass-through parameters
included — where LRM 6.4.2 ends with *"The simulator shall consider only
the ranges of the paramset's own parameters when choosing a paramset"*.
That is why `.model rsil rsil` with nothing given resolved to the mismatch
member `rsil__2` in silence: it binds six more module parameters, so it had
six fewer "un-overridden" ones, where the clause's answer for that card is
the tie error.

## What changed

- **`INPdecimal(digits, end, more, more_end, exp10)`** builds the literal's
  digit run (decimal point dropped; an RKM spelling's second run after the
  scale letter appended) followed by `e<exp10>` — the fraction's length,
  the written exponent and the scale factor folded into one power of ten,
  exactly the exponent the old product used — and hands it to `strtod`.
  Every C library rounds that correctly. No decimal point is written, so
  the locale's separator does not matter; a run longer than the buffer
  takes the old road. All five copies of the netlist parser use it, the
  value computed before the token is freed (the digits point into it).
  `ft_numparse` does the same for an integral exponent (it allows `1e1.5`,
  which keeps the multiplication); numparam builds `<mantissa>e<suffix>`
  when a suffix follows a mantissa without its own exponent. The E-426
  overflow refusal stays (`1e400` is infinity from `strtod` too); `0e400`
  is zero now, not "not a representable number" — it was refused only
  because `0 × pow(10, 400)` is NaN.
- **Compiler:** `SiRealNumber::value` parses `"<mantissa>e<exp>"` — a
  scaled literal carries no exponent of its own (LRM 2.6.2), so appending
  one is unambiguous.
- **`OSDI_PARAMSET_OWN`:** one `uint32` per parameter in `param_opvar`
  order, counted by `OSDI_PARAM_DEFAULT_COUNTS` and exported with the
  family table — 1 for a parameter declared inside the `paramset` the twin
  was lowered from (`Module::paramset_decl_range` contains the parameter's
  declaration), 0 for a target-module parameter passed through, a parent
  paramset's parameter in a chain, or any parameter of a plain module.
  ngspice's `osdi_param_is_own` reads it; an object without the table (an
  older compiler) keeps the old reading.
- **Selection:** a card value is range-checked, a default is judged, and an
  un-overridden parameter is counted only for the paramset's own parameters
  (a pass-through on the card must still exist and not be fixed, as
  before). `osdi_range_accepts` reads `{a, b, c}` sets for both `from` and
  `exclude` — a member the card cannot judge gives the benefit of the
  doubt (a from-set accepts, an exclude-set does not exclude). A tie names
  the tied members' own ranged parameters whose ranges differ:
  `paramset 'rsil' is ambiguous for .model r0 (LRM 6.4.2): 2 members apply
  with 6 un-overridden parameter(s) each -- give a parameter whose value
  only one of them accepts: rsil takes mm_ok from [0:0]; rsil__2 takes
  mm_ok from [1:1]`.

## Verification

| check | result |
|---|---|
| `vmax=1.2` / `w=3.3` / `l=0.96u` / `t=1.1u` on the cards against `[0:1.2]`, `(0:3.3]`, `[0.96u:10e-6]`, `[1.1u:inf)` | accepted, read back exactly, `I = 1.2 × 3.3 mA`; `l=10e-6` at the inclusive upper bound accepted, parsed as exactly 1e-05 |
| `alter`/`altermod` to 3.3 and 1.2; `.param wv=3.3 tv=1.1u` substituted into the cards | accepted, exact |
| `v1 1 0 1.2` then `print v(1) - 12/10`; `print 0.96e-6 - 96/1e8` | 0 and 0 (2.2e-16 before) |
| two `rs` members over `type from [-1:1] exclude 0` and `q = 5 from [0:1]` (pass-through), own `l = 0.96e-6 from [0.96e-6:…)`, own `bins from {1, 2, 4}` | `mm_ok=0` selects `rs`, `mm_ok=1` `rs__2`; `bins=2` applies, `bins=3` is "outside from {1, 2, 4}" |
| `.model r0 rs` with nothing given | the tie error, naming `mm_ok from [0:0]` / `[1:1]` — `rs__2`'s extra binding no longer wins |
| IHP `resistor_paramset.va` through the fold with the **unedited** ranges | `.model rsil0 rsil l=0.5u w=0.5u mm_ok=0` → `rsil`, `mm_ok=1` → `rsil__2`, `rhigh l=0.96u` applies; the same card with nothing given → the tie error with the hint |
| `hbconv` [5] | the deck's HB residual floor moved from 9.5e-9 to 3.3e-8 with correctly rounded inputs (`0.8p`, `20m`, …); the loosened bound is 1e-7 now, 5 iterations, the spectrum bit-identical to the stall-accepted run as before |
| `inputguard` [7] | `1e400`, `1e2147483648`, `1e21474836480` still refused; `0e400` is 0 |
| `paramsetoverload`, `paramrange`, `intrange`, `paramset`, `osdimc` | green |
| workspace `cargo test` (the sim_back snapshots carry `paramset_own`) | green |
| `cardbound_examples` | 10 / 10 per solver, both solvers; 7 / 10 fail on the E-642 binaries |
| full sweep | 516 of 516 |

## What this does not do

The LRM's second tie-break, "the greatest number of local parameters with
specified ranges", is not applied on the `.model` route (a `localparam`'s
range is not exported); the clause's third, unconnected ports, has no
meaning on a card. Selection by an instance-line value (`mm_ok=1` on the
instance, nothing on the card) is the hunt's C1, a separate enhancement.
