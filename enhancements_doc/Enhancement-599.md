# Enhancement-599: a card's instance defaults are listed by `showmod` and moved by `altermod`, and a hoisted `pre_osdi -f` says where it runs

**Scope:** `src/spicelib/parser/inpdpar.c` (the card-default side table, noted in both
parameter loops of `INPdevParse`), `src/include/ngspice/inpdefs.h`,
`src/frontend/spiceif.c` (`altermod_instance_default`, the card default in the
read-side message, the table cleared per deck), `src/frontend/device.c` (`showmod`
rows), `src/frontend/inp.c` (the pre-pass Note), `src/frontend/commands.c` (`pre_osdi`
as a live command), `src/spicelib/devices/dev.c` and `src/osdi/osdiregistry.c` (the
reload copy resolves its source like the first load), `examples/carddefault_examples/`
(new, 15 checks per solver); `examples/instdep_examples/` re-pinned. **ngspice only.**
Findings F4 and F5 of the 2026-09-10 integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)).

**Suites:** [`carddefault_examples`](../examples/carddefault_examples/) 15 of 15 per
solver, both solvers; `instdep` 23 of 23 with check [19] re-pinned to the new behaviour;
`osdireload`, `lifecycle`, `multimod`, `showwidth` unchanged; full sweep 493 of 493.

## F4 — the card's instance defaults

A `.model` card may carry instance parameters as the defaults of its instances
(`.model am cd width=3`, Enhancement-546): `INPdevParse` replays them onto each instance
as it is parsed. Honoured — the instance without `w` read 3 — but `showmod am` did not
list them (they live in no model-parameter table) and `altermod am width=5` was refused
with hunt F15's message, which recommended the very card it could not change. The
reason was real: after the replay the device sees an instance that took the default and
one that wrote its own value the same way, both "given".

**What changed.** The parser keeps the distinction. `INPcardDefaultNote` records, per
instance and parameter id, whether the value came from the card or from the instance
line; an `alter` marks it the instance's own; the table is cleared once per deck parse
(and not by the card a control-block command synthesises through the same pass).

- `altermod <model> <instance parameter>=<value>` sets the parameter on every instance
  that follows the card — took its default, or never set it — leaves the ones that gave
  their own value, records the value on the card, and says what it did: "'width' is an
  instance parameter; 5 is now the default of model am -- 1 instance follows it, 2 keep
  their own value", or, when every instance sets its own, "... is recorded as the
  default of model am, but every one of its 3 instances sets its own value, so nothing
  changes".
- An alias on the card and the base name in the command are one parameter (matched by
  id): the card's row is updated, not duplicated.
- `showmod` lists the card's instance defaults after the model parameters, under
  "instance defaults on this card:", in the card's spelling.
- Reading the parameter through the model name still refuses, and now names the card's
  default when there is one: "the .model card gives w=3 as the default of the instances
  that do not set it (`showmod am` lists it)".
- Built-in devices whose card carries a model-level twin of the parameter (a diode's
  `area`, a resistor's `w`) already had a model-level default and are untouched.

## F5 — the hoisted `pre_osdi -f`

Every `pre_` line in a control block is hoisted into the pre-pass, wherever it sits, so
a `pre_osdi -f two.osdi` written after a `shell` that recompiles the file ran before the
shell, printed "reloaded (3 devices)", reloaded the old object, and was gone at
execution time; typed at the prompt, `pre_osdi` was "no such command".

- A `pre_osdi -f` (or `-force`) behind other commands in its block gets a Note at the
  pre-pass: "`pre_osdi -f two.osdi` is a pre-pass command: it runs before the circuit is
  read, ahead of the 3 commands above it in this .control block. To reload at that point
  in the block -- after a `shell` that recompiled the file -- write it without the
  prefix: `osdi -f two.osdi`." A plain `pre_osdi` after a `set`, and a `-f` at the head
  of its block, stay quiet.
- `pre_osdi` is registered as a live command, the same as `osdi`, so the spelling every
  deck uses works at the prompt too.
- Found on the way: the forced reload stages a copy of the file before `load_object_file`
  resolves the name, so a relative `pre_osdi -f m.osdi` from a deck in another directory
  opened the name against the working directory and failed "could not stage a reload
  copy". The copy now resolves its source the way the first load did.

## Verification

| check | result |
|---|---|
| `.model am cd width=3`, instances with `w=2`, none, `width=4` | 2, 3, 4; `showmod am` lists `width 3` under the card's instance defaults |
| `altermod am width=5` | only the follower moves (n2 → 5); "1 instance follows it, 2 keep their own value" |
| `alter @n2[w]=9`, then `altermod am w=6` | n2 keeps 9; "every one of its 3 instances sets its own value, so nothing changes" |
| card `width=3`, command `w=5` | one row on `showmod`, updated to 5 |
| a card with no default, `altermod am w=7` | the follower reads 7, the other keeps 2, the row appears |
| `print @am[w]` with and without a card default | the refusal names the card's 3; unchanged otherwise |
| `pre_osdi -f` behind `set`, `op`, `shell` | the Note, with the count and `osdi -f cd.osdi`; a plain `pre_osdi` after `set` and a `-f` at the head are quiet |
| the same deck run from another directory | "reloaded" (was "could not stage a reload copy") |
| `pre_osdi cd.osdi` at the prompt, then `source` | loads; the circuit runs |
| instdep [19] | `altermod mm l=4e-6` moves the promoted parameter onto the instance that follows the card and leaves the one that set `l` |

Full sweep 493 of 493 on both solvers.
