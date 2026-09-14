# Enhancement-634: the diagnostic findings of the 2026-09-12 hunt, D1–D24

**Scope:** twenty-two findings of the
[2026-09-12 hunt](../docs/bug_hunts/2026-09-12_statistics-record-and-kicad-hunt.md)'s
diagnostic table, each a place where the simulator or the compiler did something
defensible and said nothing, or said the wrong thing. Nothing binds, draws or solves
differently; what changes is what is said, four refusals, and the record's labels.
Simulator: `src/osdi/osdisetup.c` (D1, D10), `src/frontend/inp.c` (D2, D6),
`src/frontend/mcsave.c` (D3, D7, D12, D19), `src/frontend/com_sweep.c` (D3, D4, D14),
`src/spicelib/parser/inp2n.c` (D8, D13), `src/spicelib/parser/inpdpar.c` (D9),
`src/frontend/outitf.c` + `parse.c` (D11), `src/maths/misc/randnumb.c` (D19). Compiler:
`openvaf/basedb/src/ast_id_map.rs`, `openvaf/hir/src/{attributes,lib}.rs`,
`openvaf/sim_back/src/module_info.rs` (D5, D21). Documented: D11's multiplier, D15,
D16, D17, D18, D20 (the statistics guide §7.3, §7.4, the handbook §3.2). Already held:
D24 ([E-622](Enhancement-622.md)'s suffix rule matches `@x1.n1[dr]`). New suite
[`hunt12diag_examples`](../examples/hunt12diag_examples/) (20 checks per solver).
**Both sides.**

**Suites:** `hunt12diag_examples` 20 of 20 per solver, both solvers; `savemc`, `writemc`,
`osdimc`, `autoadapt`, `adaptquiet`, `autoopts`, `highsigma`, `mcpolicy`, `autobuskicad`,
`silentaccept`, `osdidist`, `wcd` green; full sweep 507 of 507.

## The findings, and what is done about each

| # | was | now |
|---|---|---|
| D1 | `mcseed=4294967297` "is not an integer; using 2147483647" — an integer past `int`, and every seed ≥ 2³¹ aliased onto one ensemble; `mcseed=-3` taken in silence | the seed is a 32-bit pattern, 0 … 4294967295: a value outside it is refused and said (seed 1); 4294967295 is a seed of its own; 1.5 is floored and said |
| D2 | `set controlswait` under `ngspice -b`: the commands behind it ran at once, before the `.op`, with nothing said | a note: the wait is for a host's run under libngspice; here there is none and the commands run now |
| D3 | `writemc trial=9 analysis=2` added a second `trial` and `analysis` column | `trial`, `analysis`, `status` are refused as the row's fixed columns, in `writemc` and in `montecarlo -writemc` |
| D4 | `highsigma` on a deck whose only statistics are uniform printed "scale = 2" and an "equivalent sigma" while running plain MC | when every weight is exactly 1 the report says nothing was inflated — a uniform has no sigma to scale — and that the figures are a plain estimate |
| D5 | *(compiler)* `(* std=25.0, std=30.0 *)`, `(* trunc=3, trunc=1 *)` took the last in silence | a warning names the attribute, the count and the one used (the last) |
| D6 | a second `.option savemc=` card, and `automc_save=` beside `savemc=`, dropped without a word | any `.option` given more than once with different values is warned (the first card's is used); `automc_save`/`osdimc_save` beside `savemc` is warned once (savemc used) |
| D7 | `writemc` after a run that made no row said "no analysis has run yet" | "the last run made no row — this circuit has no parameter with statistics to record" |
| D8 | `.option autoadapt` without `adapter=` printed "Error: … needs an adapter model" and ran anyway | a Warning that says the option is ignored (the same for `autoadapt` without `autobus`) |
| D9 | a model parameter on the instance line: "unknown parameter (r)" | "… it is a model parameter of this device — set it on the .model card, not on the instance line" |
| D10 | `altermod rm r=0` onto `from (0:inf)` was accepted; the next trial's failure blamed the draw ("value −5.11649") | the recentre is warned where it happens, naming the range (the text E-558 exports, read for numeric bounds and sets) |
| D11 | the OSDI flow vector `n1#flow(p,n)` was typed voltage and its name had to be quoted in expressions | typed `current`; the lexer reads the parenthesised name; the per-unit/×m difference against `@n1[i_p]` is documented |
| D12 | the txt writer put `nan` in a cell a row never got | empty, as csv and xlsx |
| D13 | a 4-bit bus into a 2-bit port bound the low two bits in silence | pass 3 names the bits of the base beyond the port's width (`/mid_2_, /mid_3_`) |
| D14 | a `setseed 5` in effect was overridden by the loop's default seed 1, never said | the seed note adds that the `setseed 5` is set aside, and that `-seed 5` draws from it |
| D15 | *(doc)* `resume` of a *completed* analysis re-runs it as a new trial | §7.3: the contract is for an interrupted run |
| D16 | *(doc)* rows per sweep depend on the path | §7.4: the device path is one `op` row per point, the model-parameter path one `dc` row |
| D17 | *(doc)* a host that loads the circuit twice restarts the trial counter; the analysis column says `run` | §7.4 |
| D18 | *(doc)* a `.param` derived from a `mvnorm()` one is recorded twice | §7.4: one shared draw, not inlined, recorded under its name and under every slot that reads it |
| D19 | `wcd`'s FORM iteration rows were indistinguishable from samples | labelled `op (wcd probe)` — the nominal point, the probes and the line searches, keyed on the search's own mode |
| D20 | *(doc)* `set mcseed=9` after `.option mcseed=7` wins for the next trial | §7.3 |
| D21 | *(compiler)* `(* std=0.5 *)` on `from {1.0, 2.0, 3.0}` compiled without a word and nearly every trial failed the range check | a warning: a draw around a member lands off the set; declare a continuous range or drop the statistics |
| D24 | `-inflate @x1.n1[dr]` "matched nothing" | held since E-622: the owner is matched on a `.`-suffix, so the print spelling matches the internal `n.x1.n1` |

## Verification

| check | result |
|---|---|
| D1 seeds 4294967297, −3, 1.5, 4294967295, 3 | the messages; 4294967297 and −3 draw as seed 1, 4294967295 and 3 each their own |
| D2 … D4, D6 … D14, D19 | each message or label as in the table, on a deck that provokes it |
| D5, D21 | the compiler's warnings; the object carries std 30 and trunc 1 (the last) |
| D24 | no "matched nothing" for `-inflate @x1.n1[dr]` |
| the twelve suites named above | unchanged |
| `hunt12diag_examples` | 20 / 20, both solvers |
| full sweep | 507 of 507 |
