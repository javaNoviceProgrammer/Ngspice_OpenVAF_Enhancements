# ngspice + OSDI — a one-hour hunt over the statistics, the record, and the KiCad path

**Date:** 2026-09-12, 08:27 to 09:12 local time, the write-up interleaved with the
probing from 08:57 on; about 100 decks and 16 small Verilog-A models. **Rule:** probe, record, move on;
nothing was fixed. Every deck and model is in the session scratchpad (`hunt6/`). The
surfaces chosen were the ones the last two days added or touched — `.option osdimc`
and `mcseed`, `-inflate`, `.option savemc` / `writemc`, `montecarlo -track`/`-expr`,
`autobus=kicad` — and the way KiCad drives them (a `.subckt` exported from a block,
`.probe alli`, `set ngbehavior=kiltpsa`, paths with spaces, `/name` nets, a circuit
loaded twice). Both solvers where a value was compared; one finding was checked
against the stock `libngspice` KiCad ships.

**Toolchain:** commit d9c2a3f3 (the CI binaries after the E-611 fold),
`bin/macos/apple-silicon/ngspice` and `openvaf-r` 23.6.0 as committed;
`/Applications/KiCad/KiCad.app` 10.0.5 with this project's `libngspice`
(and its `libngspice.0.dylib.orig` for the stock comparison).

## Summary

| # | Finding | Severity |
|---|---|---|
| F1 | **`montecarlo`'s fast path freezes every `mvnorm()` written in a `.param`** as soon as one other random binding (`agauss`, `gauss`, `unif`…) is in the deck: the correlated parameters keep one value for the whole run (σ = 4e-12 over 200 samples) and the yield comes out 0 % or 100 % with full confidence. An `mvnorm`-only deck never arms the fast path and is right; an `mvnorm` written directly in a device brace or on an `X` line is captured. The guide's own `mccorr` + `montecarlo` idiom breaks the moment a plain `agauss` is added beside it. | **high — silent wrong yield** |
| F2 | **`altermod` of a parent parameter does not recentre the child parameter bound to it** through Verilog-A hierarchy: `leaf #(.r(rl)) c1` with `(* std *)` on the leaf's `r` draws around the nominal of the *first* setup (1000) after `altermod tm rl=500` — the device runs at 950 where 500 was set; `unset osdimc` restores 500, and with osdimc off the binding follows. | **high — silent wrong value** |
| F3 | **`unset osdimc` discards an `alter` recentre of an instance parameter the deck never gave**: `N1 a 0 rm` (no `dr`), `alter @n1[dr]=50`, draws around 50, `unset osdimc` → `dr = 0`. With `dr=20` on the line the same sequence restores 50, and a model parameter recentred by `altermod` restores correctly. The recentred nominal is still in the table (re-enabling draws around 50 again); only the restore writes the default. | medium |
| F4 | **`-inflate` does not scope netlist `.param` dimensions.** They stay inflated at full `-scale` whatever `-inflate` names (`rr`, `r1`, `@r1[resistance]` all "match nothing"), the banner says "on the -inflate parameters only" and the NOTE says "NOTHING was inflated and this run sampled the nominal spread" — both false (132 of 2000 failures, identical to the unscoped run). Ten netlist bystander `.param`s beside an OSDI metric collapse the weights to ESS 6.3 of 3000 and `-inflate @mm[r] -inflate @n1[dr]` cannot rescue it. | medium-high |
| F5 | **`montecarlo -lhs` does not stratify the model-declared draws.** The netlist `agauss` beside them lands on its 20 quantiles (0.01, 0.07, 0.13 …); the `(* std *)` draws clump (0.71–0.78 six times) — plain hashes — while the banner says "20 Latin-Hypercube samples". | medium — silent |
| F6 | *(fixed in [E-612](../../enhancements_doc/Enhancement-612.md))* **`.option savemc=<path>` is lower-cased with the deck**, and every non-ASCII byte becomes `_`: `savemc=pD.csv` writes `pd.csv`, `Résumé_MC.csv` writes `r__sum___mc.csv`, and under KiCad the absolute path came out `/private/tmp/claude-501/-users-meisam-...` — it landed only because the volume is case-insensitive. The `pre_osdi` line beside it keeps its case (that reader is exempt; `.option` is not). | medium — silent loss on a case-sensitive volume |
| F7 | *(fixed in [E-613](../../enhancements_doc/Enhancement-613.md))* **A `savemc` directory that does not exist is announced and then nothing is written** — "recording … to ./nodir/p8a.csv", no error, no file, every row and `writemc` value lost. | medium — silent loss |
| F8 | **`writemc` after a trial that failed writes the previous run's value onto the `failed` row** (rows 10–11 carry row 9's `ia`), because the failed run leaves the old plot current. `montecarlo -writemc` correctly leaves the cells empty; the plain command does not check. | medium |
| F9 | **An analysis stopped at a breakpoint gets no row, and every `writemc` after it lands on the previous run's row**: `op`, `stop when time > 2u`, `tran`, three `writemc` → one row (the `op`'s) with the last value. The trial's draws are never recorded. | medium |
| F10 | **The `dc`/`sweep` row over the statistical parameter itself records a draw that was never applied**: `dc @rm[r] 900 1100 100` pins `r` (E-535), the device ran at 900/1000/1100, and the row says `@rm[r] = 987.78` — the skipped draw. E-610 promised "a pinned … draw: what the device actually ran with". | low-medium |
| F11 | **`.probe alli` — KiCad's default — on a bus device gives 0 V and rc = 0.** The probe's measuring source is spliced into the bus pin, autobus expands the probe node, the real net floats: `v(/out_3_) = 0` where 4 V is right, with ten warnings that name the node split and the gmin install but never the probe. On a scalar OSDI device the probe works (`n1#branch`). | **high for KiCad** — silent wrong answer |
| F12 | **An `.osdi` in a path with spaces cannot be loaded with double quotes**: `pre_osdi "dir with space/va res.osdi"` keeps the quotes in the file name (`""dir with space/va res.osdi""`), a backslash-escaped path loads `dir`, `with`, `space/va`…; only single quotes work. Every KiCad project under `~/My Projects/` hits this. | medium — KiCad |
| F13 | **`track` and `montecarlo -track` cannot parse a `/name`** ("cannot parse expression 'v(/out)'"), and `vdb/vm/vp/vr/ph(/name)` fail in `print` — the E-611 quoting reached `v()`/`i()` in print, `-expr`, `-spec`, `-writemc`, `highsigma`, `wcd` and `sweep -output`, not these. Workarounds: `vdb("/out")`, `db(v(/out))`; none for `track`. | medium — KiCad |
| F14 | **Under `set ngbehavior=kiltpsa` (what KiCad sets) the random `limit(nom, avar)` is a fatal exit**: ngspice's own PSpice-compatibility pass (`inpcompat.c`) inserts `.func limit(x, a, b)`, the two-argument call is a "parameter mismatch … fatal error in ngspice, exit(1)", and the warning says "every expression in this deck will use *your* definition" for a `.func` the user never wrote. Everything else (`agauss`, `gauss`, `unif`, `aunif`, `mvnorm`, `osdimc`, `savemc`, `autobus`) is unchanged under the compat mode. | medium — KiCad, fatal |
| F15 | **Bracket-spelled bits beside `autobus=kicad` float silently**: `V1 in[0] 0 …` with `N1 in out vares` under the kicad spelling leaves `in_0_..3_` on gmin and the output at 0 V, with only "no DC path" warnings — the other spelling of the very bits being expanded is never mentioned (E-572 covers a *base* reused as a plain node, not this). | medium — silent |
| F16 | **`std_rel` on a zero nominal draws 0 on every trial without a word.** A mismatch parameter's natural default is 0 (`(* type="instance", std_rel=0.1 *) parameter real dr = 0.0`) — sigma resolves to 0, `osdimc_verbose` prints `= 0 (nominal 0)` forever, nothing says the declared statistics can never vary. A `std=0.0` compiles too and simply never appears. | low-medium — silent |
| F17 | **A second deck sourced with the same fixed `savemc` name silently replaces the first deck's file** (E-610: "a different deck starts its own" — with a fixed name that is an overwrite, unannounced). | low-medium |
| F18 | **A `.model` card that draws in the netlist *and* carries `(* std *)` never varies on both channels inside a loop.** `.model rm rstat r={agauss(1000,300,3)}` under `.option osdimc`: through `montecarlo` (fast path) the netlist draw is *recorded* per sample (`rm:r` 1066 → 1034 → 1094 → 910) but osdimc keeps "nominal 1066.08" on every trial — the device runs with the first sample's value plus δ, and the row contradicts itself (`@rm[r]` − `rm:r` = 38.8, 48.1, −31.2, **173.0**); through a `reset` loop the netlist value varies and osdimc never draws (every pass is the baseline, δ = 0). The instance slot is the same (`N1 a 0 rm dr={agauss(0,30,3)}`: "nominal 6.60751" on every sample while `n1:dr` records 3.4, 9.4, −9.0). The in-place write of the fast path is neither pinned (as a `sweep`'s push is, E-535) nor recentred; the guide's §8 ("both channels compose") was drawn from a two-`op` test and needs correcting. | **high — silent, and the record misleads** |
| F19 | **The restore that follows `unset osdimc` overwrites the first machine write of the same run.** `op; op; unset osdimc; sweep rr 500 1500 500` (a `.param` behind `.model rm rstat r={rr}`) reads `@rm[r]` = **1000**, 1000, 1500 — the first point's pushed 500 is replaced by the restored nominal; an `op` between the `unset` and the sweep absorbs the restore and the sweep is right (500, 1000, 1500). | medium — silent wrong point |
| F20 | **The loop commands bypass the stale-circuit refusal after `osdi -f`.** After a reload the note says the circuit "keeps its data; `reset` … before its next run, which is refused until then", and a plain `op`, `dc` and `tran` *are* refused — but `montecarlo` and `highsigma` run every sample on the circuit built against the previous object, using the new object's statistics table (σ 96 from the reloaded `std=100`); `sweep` has each inner run refused yet still reports "3 points into plot 'sweep1'" (stale values), and `wcd` turns the refusals into "the metric does not respond to any statistical parameter (zero gradient)". The guard exists because a reloaded object may have a different layout; the fast path does not go through it and the other loop commands do not stop on it. | medium-high |
| F21 | **A drawn parameter whose default depends on another drawn parameter keeps the baseline nominal.** `(* std=10 *) r = 1000`, `r2 = 2*r` (no statistics), `(* std=10 *) r3 = 2*r`: per trial `r2` follows the drawn `r` (2017.1 = 2 × 1008.55, re-derived at setup) but `r3` draws around a fixed 2000 (2003.5, 2006.3) whatever `r` drew — the dependency is lost for the parameter that carries statistics. A model author writing `(* std *) parameter real r3 = 2*r` expects 2·r(drawn) + δ. | low-medium — semantic |
| D1 | `mcseed=4294967297` (2³²+1) → "is not an integer; using 2147483647": it is an integer, out of `int` range, and every seed ≥ 2³¹ aliases onto the one ensemble 2147483647. `mcseed=-3` is accepted silently. | diagnostic |
| D2 | `set controlswait` in a batch run is inert: the commands behind it run at once, before the `.op` ("vector a is not available"), with no note that there is no background run to wait for. A deck written for the KiCad host misbehaves under `ngspice -b` silently. | diagnostic |
| D3 | `writemc trial=9 analysis=2` adds a **second** `trial` and `analysis` column — the fixed columns are not reserved, unlike `-expr`'s `sample`/`montecarlo_n` (E-557). | diagnostic |
| D4 | `highsigma` on a deck whose only statistics are a uniform prints "scale (sigma inflation) = 2" and an "equivalent sigma 1.311" while running plain MC (nothing can inflate); `-inflate @um[ru]` naming the uniform says nothing. `wcd` on the same deck refuses properly ("nothing to search over"). | diagnostic |
| D5 | Duplicate attributes take the last value silently: `(* std=25.0, std=30.0 *)` → σ 30.5; `(* trunc=3, trunc=1 *)` → ±1σ. (compiler) | diagnostic |
| D6 | A second `.option savemc=` line, and `.option automc_save=` beside `savemc=`, are dropped without a word (the first `savemc` wins). | diagnostic |
| D7 | `writemc` on a deck with nothing to record says "no analysis has run yet, so there is no row" after an `op` did run — the reason is that no row was ever made. | diagnostic |
| D8 | `.option autoadapt` without `adapter=` prints "Error: … needs an adapter model" and then runs anyway. | diagnostic |
| D9 | A model parameter on an instance line (`N1 a 0 rm r=2k`) is "unknown parameter (r)"; the reverse — an instance parameter on the card — is accepted as a default (hunt-5 F4). The message could name the cause. | diagnostic |
| D10 | `altermod rm r=0` onto the exclusive bound `(0:inf)` is accepted; the next trial's failure blames the draw ("value -5.11649"), not the recentre. | diagnostic |
| D11 | An OSDI flow vector (`n1#flow(n)`, `n1#flow(n[0])`) is typed **voltage** where `e1#branch`/`v1#branch` are `current`; with `m=2` the flow vector is the per-unit current (−0.5 µA) while `@n1[i_n[0]]` is the total (−1 µA), with `m=1` they agree. The name itself needs quoting in expressions (`"n1#flow(n[0])"`). | diagnostic |
| D12 | The txt writer puts `nan` in a cell a row never got; csv and xlsx leave it empty. | diagnostic |
| D13 | A 4-bit bus into a 2-bit port (`N2 /mid /out b2`) binds the low two bits with no mention of the width mismatch. | diagnostic |
| D14 | A `setseed 5` in effect is overridden by `montecarlo`'s default seed 1; the banner says "seed 1 (default)" and never that a `setseed` was set aside. | diagnostic |
| D15 | `resume` of a *completed* analysis re-runs it and is a new trial (new draws); the documented "resume never redraws" holds for the interrupted case, which was checked (a breakpoint, two resumes, the draw kept). | doc nuance |
| D16 | Rows per sweep depend on the path: `sweep @r2[resistance]` (device path) writes three `op` rows with one held draw; `sweep @rm[r]` (model-parameter → dc path) writes one `dc` row. | diagnostic |
| D17 | Under a host that loads the circuit twice (KiCad: open, then Run) the trial counter restarts, so the first Run is a **second baseline** and `savemc` labels it trial 2; the `analysis` column says `run` (the command), not `op`. | doc / diagnostic |
| D18 | A `.param` that uses `mvnorm()` is recorded **twice** by `savemc` — as its own column (`pm`) and as the device slot (`r2`) — while an `agauss` `.param` is recorded by slot only. | diagnostic |
| D19 | `wcd`'s FORM iteration — every finite-difference probe — is recorded as an ordinary `op ok` row (rows 5–35 of a 38-row file for one `wcd -is 3`), indistinguishable from samples. | observation |
| D21 | `(* std=0.5 *)` on a parameter declared `from {1.0, 2.0, 3.0}` compiles without a word, and nearly every trial then fails the range check ("value 0.7021; range from {1.0, 2.0, 3.0}") — statistics on a discrete-valued parameter can only fail. (compiler) | diagnostic |
| D24 | `-inflate @x1.n1[dr]` — the spelling `print` accepts for a device inside a subcircuit — "matched nothing"; only the internal `@n.x1.n1[dr]` matches. `@MM[R]` is case-insensitive as documented. | diagnostic |
| D20 | `set mcseed=9` in the control block after `.option mcseed=7` takes effect for the next trial (the later `set` wins) — consistent, but undocumented next to the "deck card wins" rule of E-464. | doc |
| G1 | A bus-base actual onto **bit-level subcircuit formals** (`X1 /in /out blk`, `.subckt blk in_0_ … out_3_`, or the bracket form) is refused "Too few parameters for subcircuit" — E-449 covers bits passed *into* a subcircuit whose device line uses the base, not this direction; the message does not mention autobus. A KiCad block exported with bit ports cannot be driven by a bus wire. | gap |
| N1 | `.param rb = ra * 2` — spaces around the operator — is "; sign expected" (write `ra*2`, `2 * ra` or `{ra * 2}`). Stock `libngspice` (KiCad's original) fails identically; this build names the line. | stock |
| N2 | An explicit `m=0` makes the device vanish without a message (hunt-5 F2 recorded the bare-word form). | stock-like |
| O1 | A `.model` card **inside** a `.subckt` gets one independent draw per copy (`x1:m` 971, `x2:m` 1024): what the Verilog-A declared as process becomes per-placed-symbol variation — exactly what a KiCad `.subckt` wrapper with the card inside does. | by design, document |
| O2 | `.option`, a `.control` block and `pre_osdi` inside a `.subckt` body (a block sheet that carried the directives) are honoured globally. | by design, document |
| O3 | `(* std *)` through module hierarchy flattens to `c1__r`, `c2__r`, `c1__dr` …, each with the leaf's statistics and independent draws — process per leaf instance inside one card. | by design, document |

Everything else probed held, and the table at the end says what.

## F1 — `mvnorm()` in a `.param` is frozen on the fast path

```spice
.param pa = agauss(1000, 100, 3)
.param pm = 1000 + 50*mvnorm(1)
V1 a 0 DC 1
R1 a 0 {pa}
R2 a 0 {1000 + 50*mvnorm(1)}       ; the same draw, written in the device brace
R3 a 0 {pm}                        ; through the .param
.control
mccorr 1 1
montecarlo 5 -seed 1 -analysis op -expr direct=@r2[resistance] -expr viaparam=@r3[resistance]
print direct viaparam
.endc
```
```
montecarlo: fast path armed (2 random value bindings, no per-sample reset)
0   1.033038e+03   9.953804e+02
1   1.047202e+03   9.953804e+02
2   9.898083e+02   9.953804e+02
3   9.935471e+02   9.953804e+02
4   9.593474e+02   9.953804e+02
```

Two bindings are counted — the `agauss` and the direct brace — and the `.param` form is
not one of them, so `viaparam` never moves. E-346 lists `mvnorm` among the captured
functions, and the `.param`-inlined `agauss` *is* captured, so the inlining path drops
`mvnorm` specifically. The consequence on the guide's matched-divider deck
(`r1 = 1000 + 50*mvnorm(1)`, `r2 = 1000 + 50*mvnorm(2)`, `mccorr 2 …`):

| deck | fast path | `stddev(a)` | yield |
|---|---|---|---|
| the two `mvnorm` params alone | not armed | 49.9 | 70.0 % (correct) |
| plus one `.param r3 = agauss(1000,100,3)` on an unrelated resistor | armed (1 binding) | **4.3e-12** | **0.0 %** |

The reset idiom redraws every sample (1019.8, 1028.3, 993.9 …). The slot does not
matter: `.model rp rstat r={pm}` is frozen the same way (972.7 on every sample) while
`.model rm rstat r={pa}` and a subcircuit call's `c={pc}` (a `gauss` `.param`) redraw.
`limit()`, `gauss`, `unif`, `aunif` are captured; `highsigma`, `wcd -is` (checked
through the `savemc` rows: the `mvnorm` slot moves on every sample) and `mcsample lhs`
handle `mvnorm` — the freeze is `montecarlo`'s fast path alone, with and without `-lhs`
and `-warm`. Both solvers.

## F2 — the child of a hierarchy is not recentred with its parent

```verilog
module leaf(p, n);  ...  (* std=25.0 *) parameter real r = 1000.0 from (0:inf);
module top(p, n);   ...  parameter real rl = 1000.0;
                         leaf #(.r(rl)) c1(p, m);   leaf c2(m, n);
```
```spice
.option osdimc mcseed=1
N1 a 0 tm
.model tm top rl=1k
.control
op                                   ; baseline
op
print @tm[rl] @tm[c1__r]             ; 1000     1029.93   (c1 draws around 1000 -- fine)
altermod tm rl=500
op
print @tm[rl] @tm[c1__r]             ; 500      950.24    <- 1000 - 49.8: the old nominal
unset osdimc
op
print @tm[rl] @tm[c1__r]             ; 500      500       (the binding holds when nothing draws)
.endc
```

With `rl=1meg` on the card from the start, `c1__r` draws around 1 MΩ, so the binding is
resolved at the first setup; the `OSDImParam` recentre hook updates `rl`'s own entry
and not the flattened `c1__r` that depends on it. With osdimc never on, `c1__r` follows
`rl` through the same `altermod` (1000 → 500). KLU the same.

## F3 — `unset osdimc` loses the recentre of a never-given instance parameter

```spice
N1 a 0 rm                         ; dr not given: its nominal is the default, 0
.control
op
alter @n1[dr]=50
op
print @n1[dr]                     ; 39.0008   (50 - 11.0: recentred, drawing)
unset osdimc
op
print @n1[dr]                     ; 0         <- expected 50
set osdimc
op
op
print @n1[dr]                     ; 39.0008   (the table still says nominal 50)
.endc
```

`N1 a 0 rm dr=20` → `alter @n1[dr]=50` → `unset` restores 50; `altermod rm r=2000` →
`unset` restores 2000; `alter n1 dr=50` behaves like the accessor form. The restore
writes the *default* for a parameter the deck never gave — the E-555 "given" flag is
the likely seam. Also visible: re-enabling the option restarts the sequence at trial 2
(the same 39.0008 again).

## F4 — `-inflate` and the netlist dimensions

```spice
.param rr = agauss(1000, 100, 3)      ; the only statistics in the deck
R1 a 0 {rr}
highsigma 2000 -scale 3.0 -seed 1 -analysis op -metric -1/i(v1) -max 1150
highsigma 2000 -scale 3.0 -seed 1 -analysis op -inflate rr -metric -1/i(v1) -max 1150
```
```
highsigma: 2000 samples, scale (sigma inflation) = 3, analysis 'op', ...
  failures observed : 132 / 2000 (in the inflated sampling)
  P(fail)           : 3.3064e-06  +/- 5.76e-07
highsigma: 2000 samples, scale (sigma inflation) = 3 on the -inflate parameters only, ...
  failures observed : 132 / 2000 (in the inflated sampling)     <- identical: rr WAS inflated
  P(fail)           : 3.3064e-06  +/- 5.76e-07
  NOTE    : none of the 1 -inflate parameter matched a statistical parameter in this circuit, so NOTHING was inflated and this run
            sampled the nominal spread; check the names against the model's (* std *) parameters.
```

`-inflate r1` and `-inflate @r1[resistance]` say the same. The scope mechanism only
knows OSDI dimensions; the netlist SSS path always inflates all of its Gaussians. The
other way round is the damaging one — an OSDI metric with ten netlist bystanders:

```
  P(fail) : 3.3147e-02 +/- 3.06e-02 (relative error 92.2%)
  NOTE    : the importance weights have collapsed -- an effective sample size of 6.3 out of 3000.
highsigma_ess = 6.261472e+00          <- with -inflate @mm[r] -inflate @n1[dr]: 6.261472e+00, unchanged
```

## F5 — `-lhs` and the model-declared draws

```spice
.option osdimc mcseed=1
.param rr = agauss(1000, 75, 3)
R1 a 0 {rr}
N1 a 0 rm
.model rm rstat r=1k
montecarlo 20 -lhs -seed 1 -analysis op -expr rn=@r1[resistance] -expr rm=@rm[r]
```
Sorted and mapped through Φ:
```
netlist  (LHS): 0.01 0.07 0.13 0.19 0.21 0.27 0.32 0.40 0.44 0.50 0.51 0.55 0.62 0.69 0.74 0.79 0.83 0.86 0.94 0.97
model-side    : 0.07 0.10 0.24 0.31 0.32 0.34 0.45 0.61 0.63 0.71 0.73 0.74 0.75 0.75 0.78 0.81 0.89 0.91 0.94 0.96
```
The banner: `montecarlo: 20 Latin-Hypercube samples`. The model draws are pure hashes of
(seed, sample, owner, id) with no stratum to land in; saying so once — or stratifying the
`u01` — would do.

## F6, F7, F17 — the `savemc` file name

| `.option savemc=` | file written | said |
|---|---|---|
| `pD.csv` | `pd.csv` | "to ./pd.csv" |
| `Résumé_MC.csv` | `r__sum___mc.csv` | "to ./r__sum___mc.csv" |
| `nodir/p8a.csv` (no such directory) | **nothing** | "recording … to ./nodir/p8a.csv" — no error, ever |
| the same fixed name from a second deck (`source other.cir`) | the first deck's file **replaced** | "recording … to ./shared.csv" |

Under `libngspice` the note read
`to /private/tmp/claude-501/-users-meisam-git-ngspice-openvaf-enhancements/…/host.csv`
while the `pre_osdi` path on the next line kept its case — `inpcom.c` exempts `pre_osdi`,
`osdi`, `write`, `wrdata`, `codemodel`, `source`, `cd`, `load` … from lower-casing, and
`.option` is not on the list. `savemc=<name>` column names written by `writemc` keep
their case (`PK`, `Ia`), which makes the contrast odd.

## F8, F9 — `writemc` and the row it lands on

```
9,op,ok,2.40215715223,72.5975555229,-0.0133333844135
10,op,failed,6.93065923453,-6.53525346323,-0.0133333844135     <- row 9's value
11,op,failed,1.17428616211,-7.98659455268,-0.0133333844135     <- row 9's value
12,op,ok,26.7411137654,31.4897797061,-0.0171730148789
```
(`repeat 12 / op / writemc ia=i(v1)` on `rstat` with `r=30`, σ 25 — trials 10 and 11
drew below the `(0:inf)` bound.) "result vectors from the previous successful run remain
current" is exactly what the plain `writemc` then reads.

```spice
op
stop when time > 2u
tran 1u 6u
writemc n=length(time)
resume
writemc n=length(time)
```
```
trial,analysis,status,@n1[dr],@rm[r],n
1,op,ok,0,1000,29                          <- the only row; n is the last writemc's value
```

## F10 — the row of a run that sweeps the parameter

`op; dc @rm[r] 900 1100 100` → `-1/i(v1)` = 889, 989, 1089 (r + dr with dr = −11: the
sweep's values), and the row: `2,dc,ok,-10.999234629,987.784797889` — the trial-2
draw that E-535 pinned away. `sweep @rm[r] 900 1100 100` the same, one row.

## F11 — `.probe alli` on a bus device

The 4-bit `va_res` cascade of `KiCad/example5` with the one card KiCad's simulator adds
by default:
```
.probe alli
```
```
Warning: instance n2: 'probe_int_/out_n2' was expanded to the 4 bus bits probe_int_/out_n2_0_ .., but the deck
         also uses 'probe_int_/out_n2' as a plain node -- a different node from every bit.
Warning: no DC path from node 'probe_int_/mid_n1' to ground; gmin (1e-12 S) installed to provide one
Warning: no DC path from node '/mid' to ground; gmin (1e-12 S) installed to provide one
...  (10 warnings)
0   0.000000e+00   0.000000e+00        <- v(/out_3_): 4 V is right
```
`example3/README.md` records the same failure seen from KiCad and the workaround
(`fix_sim_probes.py`); the simulator itself could say "a series measuring source cannot
sit on a bus port" and refuse, instead of installing gmin and returning zeros. The same
happens through a subcircuit boundary — the E-611 `va_res_block` as `X1 /in /out` with
`.probe alli` splices `probe_int_/out_x1` and returns 0 V. A scalar OSDI device probes
fine (`n1#branch`, typed current).

## F12 — paths with spaces

| spelling | result |
|---|---|
| `pre_osdi "dir with space/va res.osdi"` | `Error opening osdi lib ""dir with space/va res.osdi""` |
| `pre_osdi dir\ with\ space/va\ res.osdi` | loads `dir`, then `with`, then … |
| `pre_osdi -f "dir with space/va res.osdi"` | as the first |
| `pre_osdi 'dir with space/va res.osdi'` | **loads** |

The same for an absolute path — the spelling a schematic tool would write.

## F13 — `/name` coverage

| accepts `v(/out)` | does not |
|---|---|
| `print v(/out)`, `let x = v(/out)`, `meas … v(/out)`, `montecarlo -expr/-spec`, `-writemc`, `writemc`, `highsigma -metric`, `wcd -metric`, `sweep -output` | `track v(/out) …`, `montecarlo -track "v(/out) …"` ("cannot parse expression"), `print vdb(/out)`, `vm`, `vp`, `vr`, `ph` (PPerror) |

`vdb("/out")` and `db(v(/out))` work.

## F14 — `limit()` under KiCad's compatibility mode

```
$ cat .spiceinit
set ngbehavior=kiltpsa
$ ngspice -b deck.cir        # .param r1v = limit(1000, 100)
Warning: .func limit() redefines the built-in function 'limit'; every expression in this deck will use your definition instead of the built-in.
Warning: .func pwr() redefines the built-in function 'pwr'; ...
Warning: .func int() redefines the built-in function 'int'; ...
ERROR: parameter mismatch for function call in string limit(1000,100)
ERROR: fatal error in ngspice, exit(1)
```
`ngbehavior=ki` alone: 900 (the coin). The `.func` lines are `inpcompat.c`'s PSpice set,
inserted by ngspice for the `ps` flag; `example6/README.md` attributed the warnings to
KiCad's prologue — they are ours.

## F15, F16 — two silences

`V1 in[0] 0 1u … N1 in out vares` under `autobus=kicad`: `in_0_..3_` get gmin and
`v(out_3_) = 0`; nothing relates the `in[k]` nodes that exist to the `in_k_` bits being
expanded. (`autobus=KICAD` is accepted case-insensitively.)

`(* std_rel=0.1 *) parameter real z = 0.0`: `osdimc: trial 2: mm:z = 0 (nominal 0)`,
every trial, and 300 `montecarlo` samples give `minimum(z) = maximum(z) = 0`. A uniform
with `std_rel` works (half-width relative: 900.7 … 1098.6 for 0.1 of 1000).

## G1 — a bus base onto bit formals

```
.subckt blk in_0_ in_1_ in_2_ in_3_ out_0_ out_1_ out_2_ out_3_
N1 in /mid vares
N2 /mid out vares
.ends
X1 /in /out blk
```
```
Too few parameters for subcircuit type "blk" (instance: xx1)
```
Bracket formals under the default style: the same. The subcircuit shape that works is
E-449's (bits passed in, the base used inside) and `.subckt blk in out` with the base
as the formal (the E-611 `va_res_block.subckt` shape, verified again: 1–4 V).

## What held

| probed | result |
|---|---|
| `.option`, `.control`, `pre_osdi` inside a `.subckt` body | honoured globally (O2) |
| `osdimc` through `.subckt`: per-instance mismatch independent, one process draw per shared card, `@x1.n1[dr]` and `@n.x1.n1[dr]` both read back | held |
| range-violating draws: `failed` row with the draw kept, `montecarlo_nfailed`, next trial recovers | held |
| `-inflate @*[dr]` wildcard; `-inflate` naming nothing / malformed | reported as documented |
| `mcseed=0`, `-3`, `1e3` | accepted; `1e3` = `1000` |
| `montecarlo 0 / -2 / 2.5 / 1e1`, `highsigma -scale 0 / 1 / -2`, `wcd -is 0`, `-seed 0` | refused with clear messages; `1e1` = 10 |
| `mccorr` shrunk below an index the deck uses | refused at the next reset, naming the range |
| `resume` after a breakpoint | draw kept, twice |
| `std_rel` per card (1k → σ 101, 100 → σ 9.3), on an instance value (`w=100` → σ 10), after `altermod` (σ follows) | held |
| the netlist draw and the `(* std *)` on one parameter (`.model rm rstat r={agauss(...)}`): netlist value = nominal, osdimc adds δ, both columns (`rm:r`, `@rm[r]`), `show` = `@` | held |
| card-level default of an instance statistic (`.model rm rstat dr=5`): draws around 5; `N2 … dr=20` around 20 | held |
| `savemc=csv/CSV/xls/excel/xlsx/txt/foo/foo.dat/1` | formats and fall-backs as documented |
| `savemc=excel` with `-writemc` and with plain `writemc` | a valid zip, values present |
| `writemc` after a `montecarlo` | onto the last sample's row |
| complex values in `-writemc`/`writemc` | magnitude, as `-expr` |
| `automc_save=` alone | OSDI columns only |
| `-writemc` names keep case | `PK`, `Ia` |
| paramset with `.r = …` | the fixed parameter is excluded with a compile note; the instance one draws |
| duplicate `dr=5 dr=7` on a line, `r=1k r=2k` on a card, unknown `foo=1` | warned as documented |
| `alter @n1[m]=2`, `altermod pm r=100` then σ | held |
| adapter cascade `va_res → va_adapter → va_res` (bit permutation) | `[3,4,1,2]` V |
| `.subckt … params: R_ohm` around the OSDI device, per-instance override, autobus through it | held (E-609/E-449 shapes) |
| `ac`, `tf`, `pz` on the bus VCVS | correct (`pz`: no poles — an ideal source with the cap across it; the scalar VCVS gives −1e6 rad/s) |
| `.nodeset`/`.ic`/`.save`/`.print` on `_k_` bit names in a batch deck | accepted |
| KiCad's `ngbehavior=kiltpsa` with `agauss/gauss/unif/aunif/mvnorm`, `osdimc`, `savemc`, `autobus` | identical to the plain run |
| `libngspice`: `.option savemc` + `osdimc` across two loads and three `bg_run`s | rows written (D17 for the labels) |
| `.param rb = ra*2`, `2 * ra`, `{ra * 2}` | fine (N1 for the spaced form) |
| `sens v(out)` under osdimc: `sens1.n1_dr` = `sens1.n1:r` = −2.38874e-04 at the drawn point | exact (analytic −2.38874e-04); `sens` consumes one trial |
| 3000 `montecarlo` trials, osdimc on vs off | 0.31 s vs 0.30 s — no draw overhead |
| `.option mcseed=7` then `set mcseed=9` | the later `set` wins for the next trial (D20) |
| two `.osdi` files defining the same module (`va_res` scalar from example6, 4-bit from example5) | "already registered; keeping the existing device and ignoring this one" — the first load wins, with a warning (the file names could be said) |
| every run-class command makes a `savemc` row: `op`, `ac`, `tf`, `sens`, `pz`, `noise`, `dc`, `tran`, `run` | rows labelled by command; a bare `run` with no analysis card still consumes a trial and writes an `ok` row |
| `.probe alli` on the exported block through KiCad's own `libngspice` | `v(/out_3_) = 0` — F11 seen from the host |
| `wcd` with a nominal that already fails (`v(2) = 0.8` against `-max 0.68`, four shared-card devices) | says "FAILS at nominal", β = −34.6 σ — legitimate: the pass region needs the card's `r` to nearly double, 34 σ at σ = 25; the passing spec beside it gives β = 4.78 |
| `(* std *)` on a parameter with a plain dependent default (`r2 = 2*r`, no statistics) | `r2` follows the drawn `r` at every setup (F21 is the case where `r2` itself carries statistics) |
| `pre_osdi -va va/rstat2.va` | the on-the-fly object carries the statistics (σ 24.5 over 100 draws) |
| `-spec @n1[dr] -max 5` over 2000 samples | 70.0 % against Φ(0.5) = 69.1 %, and equal to a recount of the recorded draws |
