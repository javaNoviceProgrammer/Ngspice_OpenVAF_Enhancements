# Enhancement-600: a saved opvar warns once and an inferred save not at all; a missing model says why

**Scope:** `src/frontend/outitf.c` (the save probe, `ft_save_probe`), `src/osdi/osdiparam.c`
(`OSDIask` quiet under the probe), `src/include/ngspice/fteext.h`,
`src/spicelib/parser/inpdomod.c` (the unknown-type cards remembered), `inpkmods.c`,
`src/include/ngspice/inpdefs.h`, `src/spicelib/parser/inpgmod.c` (`INPgetMod`'s message,
`INPgetModBin`'s bin-miss message), `inp2n.c` and `inp2m.c` (the callers use it),
`examples/savemiss_examples/` (new, 11 checks per solver). **ngspice only.** Findings D1
and D2 of the 2026-09-10 integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)).

**Suites:** [`savemiss_examples`](../examples/savemiss_examples/) 11 of 11 per solver,
both solvers; `saveused`, `saveforms`, `savenoise`, `savecur`, `savekw` unchanged; full
sweep 494 of 494.

## D1 — the saved-opvar warning, twice, and for a save nobody wrote

```
save @n1[rt]
dc temp 27 127 50
```

```
Warning: (the accessor) is an operating-point variable and no operating point has been computed for n1, so it has no value.
Warning: save '(the accessor)': 'rt' has no value yet -- it is an operating-point variable and no analysis has computed one. It is recorded per point once an analysis runs.
```

(the accessor being `@n1[rt]`, written out in the run.)

Two sentences for one item. `beginPlot` checks a saved `@dev[param]` by asking the device
for it (`INPaName`), and the OSDI ask prints its own "no operating point yet" — a message
meant for a user *read* — before the save code prints Enhancement-418's, which says the
same and adds what will happen. And under `.option saveused`, which registers what the
control block reads, both were printed for a save the author never wrote — the case
Enhancement-496 silenced for the unmatched-name warning, and for the same reason: there
is nothing to tell them.

**What changed.** `ft_save_probe` is set around the two `INPaName` probes and `OSDIask`
stays quiet while it is up, so the E-418 sentence is the only one; a plain read of the
accessor (`print @n1[rt]`) before any analysis still gets the device's own line. An
inferred save (E-496's `autosaved` mark) gets neither.

## D2 — "Unable to find definition of model ma", for a card that is there

```
v1 a 0 1
n1 a 0 ma
.model ma resa r=1500
```

Pass 1 drops a card whose type nothing defines, with "Unknown model type resa -
ignored" attached to the card — but the deck's error loop stops at the first
instance-line error, and the card usually sits *after* the line that uses it, so what
the user saw was only the bare sentence. A plain `osdi file.osdi` in the control block
lands here too: it runs after the netlist is read, so the type is unknown when the card
is parsed. And an instance outside every bin of a binned model — Enhancement-495's
`nv.1`, `nv.2` — got the same sentence, or for a MOSFET "could not find a valid
modelname".

**What changed.**
- Pass 1 remembers the cards it dropped for an unknown type (name, type, line), cleared
  with the model table, and `INPgetMod` uses that: "Unable to find definition of model
  ma: the .model ma card (line 4) names the type "resa", which no built-in device and no
  loaded OSDI or XSPICE library defines. A Verilog-A module is loaded with `pre_osdi
  <file.osdi>` in a .control block before the netlist is read; an `osdi` command without
  the prefix runs after it, too late for this card."
- `INPgetModBin` returns a message when bins exist and none covers the instance, listing
  them with their ranges and the instance's `l` and `w` after `.option scale`; the `n`
  and `m` line parsers prefer it over the bare sentence. A bin hit and a model that is
  nowhere in the deck read as before.

## Verification

| check | result |
|---|---|
| `save @n1[rt] @n1[tk]` before `dc temp` | one warning per item, the device's line absent; 1000, 1500, 2000 Ω recorded per point |
| the same under `.option saveused` | no warning |
| `print @n1[rt]` before any analysis | the device's line, as before |
| unknown type, card after the instance | the card, its line, the type, `pre_osdi`, and why `osdi` is too late |
| card before the instance | pass 1's own warning, then the same explanation |
| a late `osdi` in the control block | the same explanation |
| an OSDI instance and a BSIM4 instance outside every bin | the two bins with their ranges and the instance's l = 5e-05, w = 1e-06 |
| a bin hit; a model nowhere in the deck | 21 mA as before; the plain sentence |

Full sweep 494 of 494 on both solvers.
