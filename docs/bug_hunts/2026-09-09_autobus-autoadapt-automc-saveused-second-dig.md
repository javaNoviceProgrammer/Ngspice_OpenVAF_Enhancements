# `autobus`, `autoadapt`, `automc`, `saveused` — a second dig

**Date:** 2026-09-09, 13:32 to 13:45 local time, about sixty decks, both solvers where
values were compared. **Rule:** probe, record, move on; nothing was fixed. Every
deck is in the scratchpad (`hunt4/`). This follows the 2026-09-02 hunt on the same four
options and Enhancement-572's survey; the aim was the surfaces both left open — the
`autobus` subcircuit path, `autoadapt`'s node filter and its interplay with the other
three, `saveused` beside every kind of analysis and loop command, and the `osdimc`
policy layer under `montecarlo -track`, `alter`, `dc` and a control-block `option`.

**Toolchain:** commit d27dadcb (E-590), `ngspice-46/build/src/ngspice` and
`OpenVAF-master-20260610/target/opt/openvaf-r` as built.

## Summary

| # | Finding | Severity |
|---|---|---|
| F1 | `.option saveused` aborts every `noise` analysis: the block's own `noise v(out) v1 ...` line puts `out` in the save set, a noise run produces only its spectrum vectors, and ngspice answers "no data saved for Noise analysis; analysis not run". | analysis lost |
| F2 | The `saveused` scanner knows `v()`, `i()` and `@dev[param]` only. `print v(in) vdb(out)` loses `out`; `.meas ac gain find vdb(out)` fails "no such vector"; a block that uses only `vm(out)` works by accident, because nothing is collected and the option stands down. | under-save |
| F3 | `autoadapt`: a third touch on one **bit** of a shared bus (`c1 x[2] 0 1p`) leaves the whole bus unadapted and says nothing; a third touch on the base token is reported only by E-572's bus-reuse warning, never as an adaptation refusal. | silent no-op |
| F4 | The adapter refusal "must have exactly two bus ports of equal width (found 2 port(s), widths 1/1)" fires for a `[0:0]` adapter, whose two bus ports are of equal width; the unstated rule is a width of two or more, and for a scalar adapter on a 5-bit node the text should name the node's width. | misleading diagnostic |
| F5 | `.ic v(x[2])=0.5` on a split bus gets ngspice's generic "IC on non-existent node", while `.save v(x[2])` gets E-572's explanation of the split. | diagnostic gap |

Two of the 2026-09-02 findings (an implicit-all `write` pruned, a bare node in `let`
under-saved) no longer reproduce; both are covered by the keep-all rule that `write`
and `print all` now trigger and by the scanner's handling of `let`.

## F1 — `saveused` and a `noise` analysis

```
.option saveused
...
.control
noise v(out) v1 dec 2 100 10k
print noise1.onoise_spectrum
.endc
```

```
Error: no data saved for Noise analysis; analysis not run
```

The scanner collects `out` from the `noise v(out) ...` line itself, so no deck with a
noise analysis can avoid it. A noise run's plot holds `onoise_spectrum`,
`inoise_spectrum` and the totals and no node, so a save list of `out` alone saves
nothing and the analysis is skipped. Stock ngspice does the same for a user-written
`save out` before `noise` (`s24.cir`: "save 'out': nothing of that name is in this
analysis" and the same abort), and `save all` runs it (3.4456e-9 V/√Hz). The
difference is that here the user wrote no `save`; Enhancement-469's one promise is
that the deck still works. `sens`, `pz` and `tf` are unaffected (their plots are not
gated by the save list).

**Status (2026-09-10):** resolved by Enhancement-594. Whenever the option acts it also
registers a `save all` restricted to the noise analysis and one restricted to the sp
analysis, which every other analysis ignores, so a transient beside them stays pruned.
Two slips found under it are fixed too: `name_eq` compared a lowercased save name with
the mixed-case `S_2_1` an sp run publishes (stock `save S_2_1` failed the same way),
and the E-417 dedup in `ft_getSaves` dropped a second `save all` that differed only in
its analysis restriction. Stock semantics are untouched: `save out` before `noise`
still refuses the run.

## F2 — the scanner's vocabulary

| block | result |
|---|---|
| `print v(in) vdb(out)` after `ac` | "vector out is not available" |
| `.meas ac gain find vdb(out) at=1k` beside a block printing `v(in)` | "no such vector as v(out)", the measure fails |
| `print vdb(out) vp(out) vm(out) vr(out) vi(out)` alone | all five print, but only because the scan found nothing and the option did not act (`length(in)` = 3: every node saved) |

`e469_scan_refs` looks for `v(` or `i(` preceded by a non-identifier character, so
`vdb(`, `vm(`, `vp(`, `vr(`, `vi(` and their upper-case twins are invisible, in the
control block and in the dot cards E-572 added. The same textual scan is what makes a
`v()` inside a quoted `-track` string or an `if` condition work, so the fix is the list
of prefixes, not the method.

**Status (2026-09-09):** resolved by Enhancement-591. The scan registers the
`vm`/`vp`/`vr`/`vi`/`vdb`/`vg` forms, one or two nodes, as the plain accessor of each
node; `saveforms_examples` 16 of 16 per solver, sweep 486 of 486.

## F3 — a bit-level third touch is silent

`N1 x s1 bm` and `N2 x s2 bm` share the 5-bit bus `x`; with `adapter=am5` (a 5-bit
adapter) the bus is split (`v(x_f[2])` 0.9411, `v(x_r[2])` 0.9393, `e5.cir`). Add
`c1 x[2] 0 1p` (`e6.cir`): no `x_f` exists, `v(x[0])` is the unadapted 0.94118, and
nothing is printed — not E-463's "three occurrences" refusal, not a note that bit 2 is
touched elsewhere. With `r9 x 0 1k` instead (`e6b.cir`) the bus is again not adapted
and the only message is E-572's "'x' was expanded to the 5 bus bits, but the deck also
uses it as a plain node", which is about the resistor, not about the adaptation that
did not happen.

**Status (2026-09-10):** resolved by Enhancement-593. E-466's quiet default stands for
unlisted nodes; a `.adapt`-listed candidate's refusal is a Warning that quotes the
extra line (`c1 x[2] 0 1p`) or names the third OSDI instance; `adaptlisted_examples`
8 of 8 per solver, sweep 488 of 488.

## F4 and F5 — two messages

`e1.cir`: an adapter declared `inout [0:0] p, n` on a scalar shared node is refused
with "must have exactly two bus ports of equal width (found 2 port(s), widths 1/1)".
E-463's own table says a shared scalar node is never adapted, so the deck is simply
out of scope; the message contradicts itself instead of saying so. `d3b.cir`: a scalar
adapter on a 5-bit shared node gets the same words, where "the node is 5 wide and the
adapter 1" is the fact.

`e5.cir`: `.ic v(x[2])=0.5` on the split bus prints "IC on non-existent node - x[2],
ignored"; the `.save v(x[2])` on the same deck prints E-572's "autoadapt split node
'x' into 'x_f' and 'x_r' ... refer to x_f or x_r instead".

**Status (2026-09-10):** F4 and F5 resolved by Enhancement-592 -- three messages for
the three adapter faults, and `.ic`/`.nodeset` on a split bit name the split and
offer `x_f[2]` / `x_r[2]`; `adaptmsg_examples` 10 of 10 per solver, sweep 487 of 487.

## Withdrawn and observations

- **`v(x1.a[2])` after `X1 n0 n1 n2 n3 n4 b bs` is not a node** — a subcircuit formal is
  replaced by the caller's node, so `v(n2)` is the name, exactly as without the option;
  a bus that is *local* to the subcircuit reads as `v(x1.a[2])` (0.857, `b11.cir`). Not
  a defect. `save v(x1.a[2])` silently saves nothing, which is ngspice's rule for any
  unknown name.
- A subcircuit formal written `a[4:0]` lists its bits descending, so a caller's
  positional nodes bind `n0` to `a[4]` (`b3.cir`: `v(b)` 2.1875 against 3.4375 for
  `a[0:4]`). That is what positional binding means and E-572's note about device lines
  (the compiler's terminal order is ascending whatever the declaration) does not carry
  to formals; a reader who writes the formal descending gets the reversal without a
  word.
- A bare token at the *caller* of a bus formal (`X1 abus b bs`) is "Too few parameters
  for subcircuit type" — the expansion lives inside the subcircuit (E-449), not at the
  call. Design, and the message is the stock one.
- `track v(out) > 0.3` at the prompt is eaten by the shell's `>` redirection, `gt` is
  not an operator, and a quoted bare expression without `-spec` records every point
  ("208 hits of every sample" with `value` 0 at t = 0.93 ms). The form is
  `track v(out) -spec 'v(out) > 0.3'`; the summary's word "hits" for a spec-less
  track reads as a count of true samples.
- `montecarlo -lhs` under `automc` prints its own NOTE that the model-declared draws
  are sampled plainly; documented, and the twenty draws looked plain.
- `.adapt x[2]` is refused clearly (a bit is not a shared bus node); `.adapt x` inside a
  subcircuit adapts every instance (`e3.cir`). `option automc mcseed=9` from the
  control block works like the dot card. `automc` on a model without statistics is a
  silent no-op.
- `print length(a[3])` reads `a[3]` as vector indexing; `v(a[2])` is the form. Known
  since E-572.

## What held

- **autobus, the subcircuit path:** an explicit caller with a bare inner token
  (3.4375 V, `vs` −2.1875, `b1.cir`), two formals of different width (`b4.cir`), KiCad
  formals `a_0_ .. a_4_` under `autobus=kicad` (`b6.cir`), a line with more tokens than
  ports refused with the terminal count (`b7.cir`), `.ic` and `.probe` on a bus bit,
  a local bus inside a subcircuit, `v(a[2])` in a `print` under `saveused` (`s5.cir`).
- **autoadapt:** a 5-bit bus split at top level and inside two instances of a
  subcircuit with `.adapt x`, the same values in both; `montecarlo` re-sourcing a deck
  with adapters under `automc` (the adapter's own draws recorded per sample, 10.86,
  9.85, 8.22, `e9.cir`); an adapter with `(* type="instance", std=1 *)` drawn per trial
  and named `n_adapt1_:r` by `osdimc_verbose` (`e7.cir`); `saveused` collecting
  `v(x_f[2])` (`e8.cir`).
- **automc:** two instances of one model — `n1:dr`, `n2:dr` differ, `sm:r` once per
  trial; a `noise` run is a trial; `dc @sm[r] 1500 2500 500` sweeps the knob exactly
  while the trial's `dr` stays (1480.0, 1973.4, 2466.7 = 1500·(1 + dr)); `altermod`
  and `alter n1 dr=0.5` recenter the next draws; `montecarlo -track "v1#branch"` on a
  dc analysis records values consistent with `-expr rr=@n1[rr]` sample by sample
  (−1/1008.99, −1/860.69, −1/1000.44), so the track's run does not take a second
  draw.
- **saveused:** `echo $&v(out)`, `meas`, `fft`, `track ... -spec`, `stop when` and
  `resume`, an included control block, two control blocks, `@n1[ir]` beside `v(out)`
  per point, `write` and `print all` keeping everything, `sens`, `pz`, `tf`,
  `montecarlo -track`, and `automc` draws recorded per point (`m4.cir`).
