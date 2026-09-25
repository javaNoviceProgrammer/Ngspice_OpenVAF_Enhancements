# Bug hunt, 2026-09-25 — `autobus`, `autoadapt`, `automc`, `saveused` and `autocorner`, a third dig

The five front-end options were read as designed — [E-444](../../enhancements_doc/Enhancement-444.md),
[E-463](../../enhancements_doc/Enhancement-463.md), [E-530](../../enhancements_doc/Enhancement-530.md),
[E-469](../../enhancements_doc/Enhancement-469.md), [E-656](../../enhancements_doc/Enhancement-656.md)
and the folds that followed each — beside the two earlier digs
([2026-09-02](2026-09-02_autobus-autoadapt-osdimc-saveused.md),
[2026-09-09](2026-09-09_autobus-autoadapt-automc-saveused-second-dig.md), and the
[corners hunt of 2026-09-18](2026-09-18_openvaf-r-corners-and-run-control.md)) and the
eleven suites that pin them, and then pushed where none of those had gone: the
options against each other, the control block as the place an option is set or unset,
the line shapes and analyses the rules do not name, and a run that fails half way.
Five harnesses, about seventy decks, every value read against the same circuit written
out by hand or against the option off. The harnesses and their reports are in the
session scratchpad (`h5/harnA.py` … `harnE.py`, `harnX.py`).

## The ground, and what held

- **`autobus`** (harness A). A parameter after the model name in every spelling
  (`r=2k`, `r = 2k`, `r={1k*2}`, with `m=1`, with a trailing `$` comment); a numeric
  token (`1` → `1[0]`), a dotted token, an upper-case token unified with its lower-case
  bits; a model card whose name is not the module's, with its own parameters; a
  32-bit port on a 120-character token; shorthand mixed with written-out bits on a
  two-bus model in either order, and a reversed bit order written out; one subcircuit
  instantiated twice on the same external token (the bits shared, as the explicit
  twin); the same token on a 5-bit and a 1-bit port; a token equal to the instance's
  own name; `alter` and `altermod` after the expansion; a short *scalar* line under the
  option still the `$port_connected` idiom with E-402's warning; a bus token reused as
  a scalar node on another device, named by E-572's warning; a line with more tokens
  than terminals refused with the terminal and port counts.
- **`autoadapt`** (harness B). The adapter named by its model card, and the card's
  parameters in force; a card that is not the module's name refused by name; explicit
  bits without `autobus` refused with the reason; the adapter being the devices' own
  model refused per device; a missing adapter and a missing `adapter=` each said; a
  shared node inside a subcircuit instantiated twice adapted in each copy; the shared
  node between two *different* subcircuits adapted; a chain of two shared nodes; equal
  widths across different models adapted, unequal widths refused with both widths;
  `alter` of the injected instance's model parameter refused with `altermod` offered.
- **`automc`** (harness C). A draw that leaves the parameter's range fails that trial
  and says so twice (the parameter, the value, the range; "trial 3 FAILED during setup;
  result vectors from the previous successful run remain current"), the next trial
  going on — E-554's policy; `std_rel` on a nominal of 0 warned at compile time and at
  run time; a `dc` sweep of a drawn instance parameter restores the draw after the
  sweep, the next `op` a fresh trial; `reset` restarts the ensemble at the nominal (the
  same draws again, deterministic); `set mcseed` in the block beats the card's, the
  later spelling; `set osdimc` and `set noosdimc` from the block act; an instance
  parameter given on the line, `alter`ed, and `unset osdimc` restoring the given value;
  two instances of one card in lockstep on the model parameter and apart on the
  instance one; `osdimc_verbose`, `showmod` and `show` reading the draw.
- **`saveused`** (harness D). `let z = abs(out)` collects `out`; `print all` and
  `write` stand aside; `PRINT` in upper case and a redirected print; an author's `save`
  inside an `if` block honoured; `sens`, `tf` and `disto` beside a `print v(out)` run
  (the sens plot restricted to what the block reads, `print all` keeping it whole);
  `pz` runs as without the option; `.option savecurrents` beside it reads as without
  it; `reset` clears the automatic save.
- **`autocorner`** (harness E). Two models with different corner sets: the pass runs the
  union (`tt ss ff sf`), a model at nominal for a name it does not declare, one Note per
  such pair; `altermod` between two passes recentres the percentage corners and keeps
  the absolute ones, every corner value as computed by hand; `set autocorner` from the
  block acts; the cornered model loaded but not instantiated runs no pass and sets no
  variables; `noise`, `pz`, `tf`, `sens` and `ac` under the option all combine (the
  noise spectrum, the poles, the transfer function and the sensitivities get their
  corner copies); a `dc` sweep of a model parameter refused as not sweepable, as
  without the option; two passes in one block make two combined plots.

## Summary

| # | Finding | Kind |
|---|---|---|
| [F1](#f1--autoadapt-with-the-shared-node-at-the-same-port-index-on-both-devices-deck-order-decides-which-side-gets-_f) | *(fixed in [E-729](../../enhancements_doc/Enhancement-729.md): a tie goes to the instance that sorts first by name, said in every mode; `.adapt b:n2` names the forward device)* `autoadapt`: when the shared node sits at the same port index on both devices, deck order decides which side gets `_f` — with an asymmetric adapter `v(c[0])` is 0.28902 with `N1` first and 0.28818 with `N2` first — and the fallback is said only under `autoadapt=debug` | silent order dependence, against E-463's own rule |
| [F2](#f2--autobus-a-bare-bus-token-on-an-under-connected-line-binds-as-a-scalar-node) | `autobus`: `N1 a busdev` (one token for two ports, the `$port_connected` shape) binds `a` as the scalar node `a` on terminal `a[0]`; the deck's `a[0]` drive reaches nothing (0 A) and E-402 reports `a[1]` … `a[4]` and `b` absent — E-572's one-bit fix covers the equal-count line only | silent wrong wiring |
| [F3](#f3--saveused-beside-autocorner-refuses-every-run-when-the-block-reads-a-corner-copy) | *(fixed in [E-725](../../enhancements_doc/Enhancement-725.md): a name ending in `_<corner>` for a declared corner also saves its base; an inferred name draws no save warning)* `saveused` beside `autocorner`: a block that reads the combined plot's `v(out_ss)` alone puts `out_ss` in the save set, no analysis has such a node, and every run of the pass is "no data saved … analysis not run" | two options' documented idioms collide |
| [F4](#f4--saveused-a-plot-qualified-bare-name-stops-every-analysis) | *(fixed in [E-726](../../enhancements_doc/Enhancement-726.md): a dotted name saves both spellings; an inferred set that names nothing of an analysis keeps everything of it, said once)* `saveused`: `print tran1.out` saves the name `tran1.out`; no analysis can match it, so the `op` *and* the `tran` before the line are "no data saved … analysis not run" — the whole deck's output gone for one cross-plot reference | the option's one promise broken |
| [F5](#f5--saveused-the-scanner-does-not-see-a-bare-vector-in-an-expression-in-meas-or-behind-) | *(fixed in [E-727](../../enhancements_doc/Enhancement-727.md): expression tokens on every command, the `meas` words, `$&name`, dotted and hashed names kept whole)* `saveused`: a bare vector inside an expression on an output command (`print v(in) mag(out)`: `out` lost), in `meas` (`meas tran m find out at=0.5u`: "no such vector as out") and as `$&mid` in `echo` or `if` ("no such variable") is invisible to the scan; `print out*2` alone works by accident, nothing collected | the scanner's vocabulary, the class of the second dig's F2 |
| [F6](#f6--autocorner-a-corner-whose-transient-aborts-half-way-contributes-a-full-length-vector) | *(fixed in [E-728](../../enhancements_doc/Enhancement-728.md): a failed corner's copies end where its data ends, nan from there, said where; `$autocorner_failed` names it)* `autocorner`: a corner whose transient aborts at 4.86 µs of 10 keeps its 44-point plot, and the combined plot's `v(out_ss)` is resampled onto the nominal's 70 points with the last value held flat to the end; "corner ss: the run failed" is printed, the vector carries no mark | a phantom tail on the plot a host draws |
| [F7](#f7--set-nosaveused-set-noautobus-and-set-noautoadapt-in-the-control-block-turn-nothing-off) | *(fixed in [E-723](../../enhancements_doc/Enhancement-723.md): the block's `saveused` lines count, the later winning; a `set` of `autobus` or `autoadapt` there is named as too late; the handbook says which pairs the block reaches)* `set nosaveused`, `set noautobus` and `set noautoadapt` in the control block turn nothing off (nor do the positive spellings turn anything on): the three options act at parse time, before the block runs, while `autocorner` and `osdimc` answer to the block; E-670 and handbook §3.7 say the later spelling wins "from the control block … for every registered pair" and list the three | documentation contradicts behaviour, silently |
| [F8](#f8--two-messages) | *(fixed in [E-724](../../enhancements_doc/Enhancement-724.md): the injection skips a taken name; the batch measures name their corner)* `autoadapt`: a user instance already named `n_adapt1_` makes the injection collide — "device already exists, bail out" on the *user's* line, the injected adapter unnamed; `autocorner`: batch `.meas` cards print each corner's value in turn with no corner label | two messages |

## F1 — `autoadapt`: with the shared node at the same port index on both devices, deck order decides which side gets `_f`

**Observed.** `harnB.py` [B1]: four bits driven at `a`, a 1 kΩ load per bit at `c`, the
shared node `b` at *port 0* of both channels, and an adapter that is not symmetric
(`adapt2`: the series `1/ra` plus a `2e-4` S shunt on its `p` side):

```
N1 b a chan            N2 b c chan
N2 b c chan            N1 b a chan
v(c[0]) = 0.2890173    v(c[0]) = 0.2881844
```

The two decks are the same circuit. By hand, `NA b_f b_r adapt2` with `N1` on the `p`
side gives 0.2890173 and with `N2` on it 0.2881844, so the option put `N1` on `_f`
in the first deck and `N2` in the second. Under `autoadapt=debug` it says why:

```
Warning: autoadapt: node 'b' sits at port 0 on both n1 and n2; falling back to deck order for _f/_r.
autoadapt: b split -> b_f (n1 port 0) / b_r (n2 port 0), 4 bits, adapter n_adapt1_ adapt2
```

In the default mode neither line is printed.

**Where.** `inp2n.c`, `INPadapt`, the `_f`/`_r` decision: "the device whose PORT INDEX
is higher gets `_f`", with a fallback to deck order when the indices are equal, the
warning under `if (verbose)`.

**Expected.** E-463's own rule — "Not deck order: a SPICE deck is order-independent and
making a reordering change the circuit would be a far worse bug than the one this
feature fixes" — applied to the tie as well: a deterministic tie-break that does not
depend on line order (the instance names in sorted order, say, or the refusal E-463
uses for every other ambiguity, naming both devices and asking for `b_f`/`b_r` by
hand), and said in the default mode when it is taken.

**Kind.** Silent order dependence, against the feature's stated design rule.

*Fixed in [E-729](../../enhancements_doc/Enhancement-729.md).* A tie goes to the
instance that sorts first by name, whatever the deck order, and is said in every mode
("Note: autoadapt: node 'b' sits at port 0 on both n1 and n2, so the port rule cannot
orient the adapter; n1 takes the forward side (b_f, the adapter's first port) by name
order, whatever the deck order -- `.adapt b:n2` puts n2 there instead, or split the
node by hand."); `.adapt b:n2` names the forward device outright, tie or no tie, and a
device that is not one of the two is an error. A first cut refused the tie, and two
existing suites showed the shape is the ordinary one for two instances of one model.
`autoadapt` section E-729, nine checks: 36 of 36 per solver, 28 of 36 on the E-728
binaries.

## F2 — `autobus`: a bare bus token on an under-connected line binds as a scalar node

**Observed.** `harnA.py` [A9]: `busdev` has the ports `a[0:4]` and `b`; under
`.option autobus`, `V1 a[0] 0 1` and

```
N1 a busdev
```

give `i(v1) = 0` and

```
Warning: instance n1: 5 of the 6 terminals of model type 'busdev' are not connected.
         terminal 2 ('a[1]') is absent  …  terminal 6 ('b') is absent
Warning: no DC path from node 'a' to ground; gmin (1e-12 S) installed to provide one
```

The one token was bound as the node `a` onto the terminal `a[0]`, not expanded; the
deck's `a[0]` drives nothing that the device touches, and the warning lists four bits
of the very port the token names as absent.

**Where.** `inp2n.c`, `INP2N`: the shorthand branch runs for `numnodes < terms` and
expands a token per *port*; a line with fewer tokens than ports falls through to the
positional binding, where a bracket-free token on a bus port is just a name. E-572
indexed the bracket-free token for the `numnodes == terms` line (the one-bit trap); the
under-connected line, `$port_connected`'s own shape, keeps the trap.

**Expected.** Under the option a bracket-free token on a bus port stands for that port,
in every line shape: `N1 a busdev` is `a[0] … a[4]` with `b` unconnected — the
`$port_connected` idiom applied to the trailing *port* — and the E-402 warning then
names `b` alone. Or, if the shape is to stay unexpanded, a warning that says the token
was not indexed.

**Kind.** Silent wrong wiring with a misleading warning.

## F3 — `saveused` beside `autocorner` refuses every run when the block reads a corner copy

**Observed.** `harnE.py` [E5]: the `cr` model (`ss`, `ff` declared) behind 100 Ω,
`.option autocorner saveused`, and the block

```
op
print v(out_ss)
```

```
Error: no data saved for D.C. Operating point analysis; analysis not run     (× 3)
Warning from checkvalid: vector out_ss is not available or has zero length.
```

With `print v(out) v(out_ss)` the pass runs and both print; with `wrdata` of both the
same. The scan collected `out_ss`, the combined plot's spelling of the corner copy
([E-656](../../enhancements_doc/Enhancement-656.md): `<name>_<corner>`), saved that name,
and no analysis holds a node of it — the E-594 failure mode (a save set no analysis
can match), one option's documented idiom feeding the other's scanner.

**Where.** `dotcards.c`, `ft_saveused` / `e469_scan_refs`: the `v(out_ss)` form is a
node reference to the scanner. `com_sweep.c`, `autocorner_run` builds the copies from the
per-corner plots' own vectors, so `out` must have been saved for `out_ss` to exist.

**Expected.** The scanner knows the corner spelling when `autocorner` (or a `corners`
loop) is in force: a reference `x_<corner>` for a declared corner name saves `x`. Or the
combined plot's copies are exempt from the save set with a note. Either way the two
options together must run the deck.

**Kind.** Two options' documented idioms collide; the deck fails.

*Fixed in [E-725](../../enhancements_doc/Enhancement-725.md).* When the loaded models
declare corners, every collected name whose node or device part ends in `_<corner>`
for one of them also registers its base — `out_ss` gives `out`, `v(out_ss)` gives
`v(out)`, `v1_ss#branch` gives `v1#branch`, `@rm_ss[rsh]` gives `@rm[rsh]` — so the
pass runs and the copy exists; not gated on the option, since only a declared corner
makes the suffix a copy's. And a name the option inferred draws none of the save
warnings (E-418's "no such device" and "no parameter" were still printed for one).
`autocorner` [21], three checks: 26 of 26 per solver, 22 of 26 on the E-722 binaries.

## F4 — `saveused`: a plot-qualified bare name stops every analysis

**Observed.** `harnD.py` [D3]: the RC divider, `.option saveused`, and

```
op
tran 0.1u 1u
print tran1.out
```

```
Error: no data saved for D.C. Operating point analysis; analysis not run
Error: no data saved for Transient analysis; analysis not run
Warning from checkvalid: vector tran1.out is not available or has zero length.
```

`print op1.v(out)` in the same place works (the `v()` form collects `out`). The bare
word `tran1.out` — ngspice's own cross-plot spelling — went into the save set as a
name, no analysis matched it, and both analyses were skipped: under an option whose one
promise is that the deck still works ([E-469](../../enhancements_doc/Enhancement-469.md)).

**Where.** `dotcards.c`, `e469_scan_bare`: a bare token with no operator character is a
vector name; a `plot.vector` form is not split at the dot. Then `com_save` of a name
nothing produces, and E-594's "analysis not run" for every analysis.

**Expected.** A `plot.name` token saves `name` (the part after the last dot), or is
left out of the set; and a save set that no analysis of the deck can satisfy is
detected before the run rather than turning every analysis off.

**Kind.** The option's one promise broken by one line.

*Fixed in [E-726](../../enhancements_doc/Enhancement-726.md).* A bare name with a dot
registers both spellings — the whole (`x1.out` is a subcircuit node, spelled the same
way) and the part after the last dot — and an inferred set that names nothing an
analysis produces no longer refuses it: when every applicable save is the option's own
and none matched, the analysis keeps every vector and says so once ("saveused: nothing
the control block names is in the pole-zero analysis; everything of it is kept"). A
`pz` beside `print v(out)`, refused before because no block names `pole(1)` by a form
the scan reads, runs. A hand-written save that matches nothing is refused as before.
`saveused` section E-726, four checks: 44 of 44 per solver with E-727's, 34 of 44 on
the E-722 binaries.

## F5 — `saveused`: the scanner does not see a bare vector in an expression, in `meas`, or behind `$&`

**Observed.** `harnD.py` [D1], [D2], each with `.option saveused` on the RC divider:

| block | result |
|---|---|
| `op` / `print v(in) mag(out)` | `in` saved, "vector out is not available" |
| `tran 0.1u 1u` / `meas tran m find out at=0.5u` / `print v(in)` | "meas … failed! Error: no such vector as out" |
| the same with `find v(out)` | `m = 2.20998e-01` |
| `op` / `print v(out)` / `echo mid is $&mid` | "Error: &mid: no such variable" |
| `op` / `print v(out)` / `if ($&mid > 0.4) …` | the same, then "PPerror: syntax error" |
| `op` / `print out*2` alone | works: nothing collected, the option stands aside |
| `op` / `let z = abs(out)` / `print z` | works: `let` is scanned for names |

**Where.** `dotcards.c`: `e469_scan_bare` skips any token holding an operator character
unless the command is `let` (`e469_expr_cmds`); `meas` is in `e469_no_bare` (its bare
words are grammar — E-496), so a vector named bare in a `meas` is never seen; and
`$&name` is neither a `v()` form nor a bare word.

**Expected.** The expression-name scan `let` already gets (`e469_add_expr_names`) applied
to every output command's expression tokens and to `meas`'s arguments after its keywords;
`$&name` collected as `name`. Over-saving a grammar word is harmless (E-469's own
argument); under-saving is the correctness bug the option must not have.

**Kind.** The scanner's vocabulary, the class of the second dig's F2 (`vdb()` and
friends, closed by E-591).

*Fixed in [E-727](../../enhancements_doc/Enhancement-727.md).* A token with an operator
character is split into its names on an output command as on a `let`; a measure's
words after the analysis and the result name are taken, either side of an `=`;
`$&name` registers `name` on any line; a dot followed by an identifier character and a
hash stay inside a name, so `x1.mid` and `v1#branch` are kept whole (a `let y =
x1.mid*2` had been "RHS invalid", a blind spot the dig had not listed); the file after
a `>` is skipped. `print out*2` alone now prunes to `out`. `saveused` section E-727,
nine checks (eight fail on the E-722 binaries); `saveforms` [5] and [7] re-pinned,
their probe `print length(in)` having named the node they declared unnamed.

## F6 — `autocorner`: a corner whose transient aborts half way contributes a full-length vector

**Observed.** `harnE.py` [E3]: `cz` divides by zero at the `ss` corner once `$abstime`
passes 5 µs; `.option autocorner`, `tran 1u 10u`:

```
doAnalyses: TRAN:  Timestep too small; time = 4.86308e-06, timestep = 2.5e-19: cause unrecorded.
tran simulation(s) aborted
autocorner: corner ss: the run failed
autocorner: 9 vectors of tran1 and its 2 corner plots into 'autocorner1' (now current): …
```

| plot | length | last time | `v(out_ss)` at index 40, 50, 69 |
|---|---|---|---|
| `tran2` (corner ss, its own) | 44 | 4.863 µs | — |
| `autocorner1` (combined) | 70 | 10 µs | 0.4651163, 0.4651163, 0.4651163 |

The corner's own plot ends where the run did; the combined copy runs to 10 µs, flat at
the last computed value from 4.86 µs on, and nothing in the plot says so. A host that
draws the combined plot (the option's purpose) shows a waveform that was never computed.

**Where.** `com_sweep.c`, `autocorner_run`: the failure is counted (`err`, the message)
but the partial plot still exists (`nnew[c] == 1`), so the copy loop takes it and
`ac_resample` holds the last sample beyond the source's range. E-656's check [9] pins
the case where the failed run made *no* plot.

**Expected.** A corner that failed is either left out of the combined plot (its name in
a `$autocorner_failed` variable, say) or its copy ends where its data ends — `nan`
beyond the abort, which every consumer treats as missing — and the banner counts it.

**Kind.** A phantom tail on the one plot a schematic host reads.

*Fixed in [E-728](../../enhancements_doc/Enhancement-728.md).* The copies of a corner
whose run failed, made no plot or was interrupted end where its data ends — nan (real,
or nan + i·nan) for every point of the nominal's scale past the corner's last point —
and one line per combined plot says where ("autocorner: corner ss: its tran2 ends at
time = 4.86308e-06 of 1e-05, where the run stopped; its copies in 'autocorner1' are nan
from there"); `$autocorner_failed` names the corners, unset when every corner ran. A
`find v(out_ss) at=9u` now fails "out of interval" instead of reading 0.4651163; a
corner that succeeded is resampled as before. `autocorner` [22], three checks, and one
in [9]: 30 of 30 per solver, 28 of 30 on the E-727 binaries.

## F7 — `set nosaveused`, `set noautobus` and `set noautoadapt` in the control block turn nothing off

**Observed.** `harnX.py` [X1], [X2]:

| deck | block | result |
|---|---|---|
| `.option saveused` | `set nosaveused` before `op` | `out` alone saved |
| `.option autobus` | `set noautobus` before `op` | the line expanded, `i(v1) = -1e-3` |
| `.option autoadapt adapter=…` | `set noautoadapt` before `op` | adapted, 0.3278689 |
| no card | `set saveused` / `set autobus` / `set autoadapt` | nothing saved / not expanded / not adapted |
| no card | `set autocorner`, `set osdimc` | the pass runs, the draws happen |

Nothing is printed in any of the five silent rows.

**Where.** The three options act while the deck is parsed — `INP2N` (autobus), `INPadapt`
between pass 1 and pass 2 (autoadapt), `ft_saveused` "immediately before the control
block executes" (saveused, [E-469](../../enhancements_doc/Enhancement-469.md)) — so a
`set` inside the block is too late in both directions; `autocorner` and `osdimc` are read
at each run. [E-670](../../enhancements_doc/Enhancement-670.md)'s heading says "the
later spelling of an option pair wins … from the control block" and handbook §3.7 lists
`nosaveused`, `noautobus`, `noautoadapt` among the pairs that follow that rule; E-670's
own table pins `set noautocorner` from the block and the deck-card forms for the rest.

**Expected.** Either the three off-words act from the block too (the saveused set is
built before the block runs, but `save` is a command the block could undo; the other two
cannot be undone after parsing and would have to say so), or the documentation says
which pairs the control block reaches, and a `set` of a parse-time option from the block
draws a note that it comes too late.

**Kind.** Documentation contradicts behaviour, in silence.

*Fixed in [E-723](../../enhancements_doc/Enhancement-723.md).* `saveused` is decided from
the block's text before the block runs, so its own `set saveused`, `set nosaveused` and
`unset saveused` lines count now, the later line winning and the block beating the
cards. `autobus` and `autoadapt` act while the deck is parsed and cannot be reached from
the block; every `set`, `setcs` or `unset` of them there draws a note that it comes too
late and where the option is decided. The handbook paragraph now says which pairs the
control block reaches. `autoopts` section E-723, eight checks: 43 of 43 per solver, 37 of
43 on the E-722 binaries.

## F8 — two messages

**`autoadapt` and a user's `n_adapt1_`** (`harnB.py` [B4]): a deck that already holds an
instance named `n_adapt1_` (an unrelated `chan`) fails with

```
Error on line 9 or its substitute:
  n_adapt1_ x y chan
  device already exists, bail out
```

— the user's own line blamed for a name the option injected. The injected name should be
checked against the deck (`n_adapt2_`, or a counter that skips taken names), or the
message should say the adapter took it.

**`autocorner` and batch `.meas`** (`harnE.py` [E2]): `.option autocorner` with `.tran`,
`.meas tran vmax max v(out)` and `.meas tran vend find v(out) at=20u` prints

```
vmax = 3.33333e-01 at= 2.00000e-05    vend = 3.33333e-01
vmax = 2.83286e-01 at= 2.00000e-05    vend = 2.83286e-01
vmax = 3.86997e-01 at= 2.00000e-05    vend = 3.86997e-01
```

— one pair per corner, in pass order, none labelled. The `.print` cards name their plot
(E-602); the measures could carry the corner the way `corners -output` does.

*Fixed in [E-724](../../enhancements_doc/Enhancement-724.md).* The injected adapter takes
the first `n_adapt<k>_` no line of the deck begins with (`n_adapt2_` beside a user's
`n_adapt1_`, the hand-written values), and `do_measure` prints `autocorner: measures at
corner <name>` once before each run's first result under the option, nothing on a plain
run. `autoadapt` one check (27 of 27 per solver, 26 of 27 on the E-722 binaries),
`autocorner` [16] two checks (23 of 23, 22 of 23).

## Observations, not findings

- An out-of-range draw under `automc` fails its trial and says so — "Parameter r of
  'wide' is out of bounds (value -1897.96; range from (0:inf))!" and "osdimc: trial 3
  FAILED during setup; result vectors from the previous successful run remain current" —
  which is [E-554](../../enhancements_doc/Enhancement-554.md)'s recorded policy (`trunc`
  clamps when that is wanted).
- `reset` restarts the `automc` ensemble at the nominal and the same draws follow: the
  draws are pure functions of seed and trial, so a deck after `reset` is a deck sourced
  anew.
- After a `dc` sweep of a drawn instance parameter the parameter reads the trial's draw
  again, and the next run-class command is a fresh trial.
- `sens v(out)` at DC reads `r1 = -0` for the divider with and without `saveused`, and
  `@r1[i]` under `.option savecurrents` reads 0 at an `op` with and without it: ngspice's
  own answers, not the options'.
- Under `autocorner` the union of two models' corner sets runs, each model at nominal
  for a name it does not declare, and `altermod` between two passes moves the absolute
  and the percentage corners exactly as [E-654](../../enhancements_doc/Enhancement-654.md)
  says; a cornered model that is loaded but not instantiated runs no pass.
- `autoadapt=debug` is the only verbose spelling; `autoadapt=verbose` draws "unknown
  autoadapt value 'verbose'; expected 'debug'" and proceeds.
