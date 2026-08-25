# Enhancement-481 — `.option silentports`

```
python3 verify_silentports.py
```

24 checks. 11/24 against the pre-fix binary.

## What it is

Enhancement-402 made an omitted OSDI terminal audible, and that stays the
**default**. It is worth saying: an omitted terminal looks exactly like a typo,
and it **dangles** rather than grounding, so the natural assumption is the wrong
one.

But a schematic front end emits what it emits. KiCad's exporter writes the short
form for every instance of a model that declares an optional thermal port, and
the schematic author cannot change that — so the deck collects five lines of
warning per device about a choice nobody made:

```
Warning: instance n1: 1 of the 5 terminals of model type 'bsimbulk' are not connected.
         terminal 5 ('t') is absent
         The model sees $port_connected() = 0 for these, and any branch
         to them carries no current. They are NOT grounded -- connect
         them to 0 explicitly if that is what you meant.
         Line: n1 d g 0 0 nm
```

`.option silentports` turns that off, and nothing else. Opt-in: a deck that does
not ask keeps the warning.

A front end that cannot edit netlists can ship `set silentports` in `.spiceinit`
instead — check [6] pins that route.

## What it deliberately does **not** do

It silences one warning. It does not make an ill-posed circuit well posed.

Measured on `misc/bsimbulk_thermal_repro`, the Enhancement-402 reproducer:

| deck | default | with `silentports` |
|---|---|---|
| `gnd.cir` — `t` written as `0` | clean, `i(vd) = -6.58515e-07` | unchanged |
| `four.cir` — `t` omitted | 5 warning lines **+ 6 × singular matrix** | 0 warning lines, **still 6 × singular matrix** |

The second row is Enhancement-402's decided territory: BSIM-BULK pins its
thermal node with a *potential* tie-off, so with the terminal absent the node
carries no current and the operating point fails on a singular matrix. The
answer there is still to write `0` for the pin. Checks [7]–[9] pin exactly this,
so nobody later reads `silentports` as a fix for it.

The two model shapes are both compiled here:

- `sp_rth.va` — thermal network contributed **unconditionally**, so the model is
  well posed with `t` absent and silencing gives a completely clean run;
- `sp_gated.va` — branch gated on `$port_connected`, so the node floats and the
  singular matrix is unaffected by the option.

## No openvaf-r change

The warning is entirely ngspice-side, raised in `INP2N` from
`numnodes < *dev->terms` using the terminal count already in the `.osdi`
descriptor. openvaf-r prints nothing about an unused port — it declares the
ports, and `$port_connected` already reports correctly. This enhancement touches
two ngspice files and no compiler code.

## Registered in both places

A `.option` name has to be known to `if_is_option()`'s list *and* to the type
dispatch beside it. Registered in only one, the option is either honoured while
being reported as "unknown ... ignored" (Enhancement-451) or warned about on a
setting the run then honours (Enhancement-445's note) — both of which teach the
reader to ignore the check.

## Every off-spelling is tested

`cp_getvar(.., CP_BOOL, ..)` reports a variable that is merely **present** as
true, so `silentports=0`, `=false`, `=no` and `=off` would each have turned the
feature **on**. Enhancements 450, 451, 454, 466 and 467 each shipped that defect
exactly once; check [5] walks all nine spellings.
