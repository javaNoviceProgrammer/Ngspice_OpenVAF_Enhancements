# Enhancement-725: `.option saveused` beside `.option autocorner` saves the base of a corner copy the block reads — `print v(out_ss)` alone had `out_ss` in the save set, a name no analysis produces, and every run of the pass was refused "no data saved for D.C. Operating point analysis; analysis not run"; and a name the option inferred draws none of the save warnings

**Scope:** F3 of the
[five-options dig of 2026-09-25](../docs/bug_hunts/2026-09-25_five-options-dig.md).
**ngspice only.** `src/frontend/dotcards.c` (`e469_strip_corner`,
`e469_add_corner_bases`, called from `ft_saveused` before the save is registered),
`src/frontend/outitf.c` (`beginPlot`, Pass 2: the two device-name save warnings, not
for an inferred name). [`examples/autocorner_examples/`](../examples/autocorner_examples/)
(section [21], 3 checks, 26 per solver). Handbook
[§3.7](../docs/handbook/03-ngspice-workflows.md). The hunt page.

**Suites:** `autocorner` 26 of 26 per solver, both solvers (22 of 26 on the E-722
binaries: the three new checks and E-724's [16]); `saveused` 44 of 44 and `saveforms`
16 of 16 with [E-726](Enhancement-726.md) and [E-727](Enhancement-727.md), `savekw`
46 of 46, `savenoise`, `multisave`, `savemiss`, `saveguard` 38 of 38, `autosave`,
`savecur`, `savecuroff`, `savecorner` 29 of 29, `autoopts` 43 of 43, `savemc` 37 of 37,
`reusedev` unchanged; no new build warnings; full sweep, run alone.

## What was wrong

The `cr` model (`ss` and `ff` declared) behind 100 Ω, `.option autocorner saveused`,
and the block

```
op
print v(out_ss)
```

```
Error: no data saved for D.C. Operating point analysis; analysis not run     (× 3)
Warning from checkvalid: vector out_ss is not available or has zero length.
```

With `print v(out) v(out_ss)` the pass ran and both printed; with a `let z = out_ff*2`
alone, "RHS invalid". The combined plot [E-656](Enhancement-656.md) builds holds the
nominal's vectors under their names and each corner's as `<name>_<corner>` —
`v(out_ss)`, `i(v1_ss)`, `@rm_ss[rsh]` since [E-666](Enhancement-666.md) — which is
the option's documented idiom; the `saveused` scan ([E-469](Enhancement-469.md)) took
`out_ss` from the line as a node name, saved that alone, and no analysis of the pass
has a node of it. A save set that matches nothing refuses the analysis
([E-594](Enhancement-594.md)'s failure mode), so the nominal and both corners were
refused in turn. The copies are built from the per-corner plots' own vectors: `out`
must be saved for `out_ss` to exist.

## What changed

**A corner copy's name also registers its base** (`e469_add_corner_bases`). After the
scan, when the loaded models declare corners (`OSDImcCornerNames`, the list the pass
itself takes), every collected name whose identifier runs end in `_<corner>` for one
of them also registers the name with that suffix off: `out_ss` gives `out`,
`v(out_ss)` gives `v(out)` (each node of a two-node form), `v1_ss#branch` gives
`v1#branch`, `@rm_ss[rsh]` gives `@rm[rsh]`, `x1.out_ss` gives `x1.out` — the
suffix sits on the node or device part, where E-666 put it. Case does not matter. It
is not gated on the option: the suffix is a corner copy's only when a model declares
that corner, and the extra name is inferred, so it costs a slot and warns about
nothing. The nominal `tt` has no copy and needs no rule.

**An inferred name draws none of the save warnings.** [E-418](Enhancement-418.md)'s
"save '…': no such device, so this vector will stay empty" and "device has no
parameter '…'" were printed for a name `.option saveused` inferred, which
[E-496](Enhancement-496.md)'s rule forbids and [E-600](Enhancement-600.md) had applied
to the third message of the three; with the scan now deriving names the author never
wrote, both are held to it. The command that named the device reports it itself
("no such device or model name"); a hand-written save warns as before.

## Verification

`autocorner` [21]: `.option autocorner saveused` and a block of `op` / `print
v(out_ss)` runs the pass, prints the ss value (0.798085) and holds `out_ss`; the
option still prunes — `out` is the one node of the circuit in the plot, `in` is not;
`i(v1_ff)`, `v1_ss#branch`, `@rm_ss[rsh]` in a `print` and a bare `out_ff` in a `let`
all read, with no "not available", "invalid" or "stay empty". On the E-722 binaries
the three checks fail as the hunt saw. The twenty other checks unchanged.

By hand: the hunt's harness E [E5] on both binaries (the `op`, the `print v(out)
v(out_ss)` and the `wrdata` forms); the accessor spellings above; the fourteen suites;
the sweep.

## What this does not do

- A name whose suffix is a corner no loaded model declares is left as it is: the scan
  cannot tell `out_ss` from a node called that unless `ss` is declared, and when it
  is, both are saved.
- The `corners` command ([E-655](Enhancement-655.md)) builds no `<name>_<corner>`
  copies, so nothing there changes; a `set autocorner` in the block is served, since
  the declared corners, not the option, decide.
- The base is registered for the whole run, not restricted to the pass; a later plain
  run in the same block keeps it too, which the option's own policy (over-saving costs
  a slot) accepts.
