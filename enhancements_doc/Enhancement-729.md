# Enhancement-729: `.option autoadapt` orients an adapter whose shared node sits at the same port index on both devices by the instance names, said in every mode, instead of by deck order in silence — `N1 b a` / `N2 b c` and the same two lines the other way round had put a different device on the adapter's p side (0.2890173 against 0.2881844 with an asymmetric adapter), the one thing E-463 ruled out; and `.adapt b:n2` names the forward device outright, tie or no tie

**Scope:** F1 of the
[five-options dig of 2026-09-25](../docs/bug_hunts/2026-09-25_five-options-dig.md).
**ngspice only.** `src/spicelib/parser/inp2n.c` (`INPadapt`: the orientation of the
adapter; `adapt_member_name_len`, `adapt_forward_of`, `adapt_inst_is`; `adapt_listed`
reads the node part of a `node:inst` member).
[`examples/autoadapt_examples/`](../examples/autoadapt_examples/) (`adapt.va` gains the
asymmetric `adapt2`; section E-729, 9 checks, 36 per solver);
[`examples/adaptlisted_examples/`](../examples/adaptlisted_examples/) (its chatter filter
passes the new note). Handbook [§3.7](../docs/handbook/03-ngspice-workflows.md). The
hunt page.

**Suites:** `autoadapt` 36 of 36 per solver, both solvers (28 of 36 on the E-728
binaries); `adaptlisted` 8 of 8, `adaptmsg` 10 of 10, `adaptquiet` 22 of 22, `autoopts`
43 of 43, `autobus` 12 of 12, `autobusopt` 27 of 27, `busmix` 13 of 13, `busmixed` 46 of
46, `subbus` 16 of 16, `silentaccept` 44 of 44, `optknown` 13 of 13, `hunt12diag` 20 of
20 unchanged; no new build warnings; full sweep, run alone.

## What was wrong

Four bits driven at `a`, a 1 kΩ load per bit at `c`, the shared node `b` at *port 0* of
both channels, and an adapter that is not symmetric (`adapt2`: the series `1/ra` plus a
`2e-4` S shunt on its `p` side):

```
N1 b a chan            N2 b c chan
N2 b c chan            N1 b a chan
v(c[0]) = 0.2890173    v(c[0]) = 0.2881844
```

The two decks are the same circuit. By hand, `NA b_f b_r adapt2` with `N1` on the `p`
side gives 0.2890173 and with `N2` on it 0.2881844, so the option put `N1` on `_f` in
the first deck and `N2` in the second. The rule of [E-463](Enhancement-463.md) is that
the device whose port index is higher takes the forward side, "not deck order: a SPICE
deck is order-independent and making a reordering change the circuit would be a far
worse bug than the one this feature fixes" — and when the two indices were equal the
code fell back to exactly that, deck order, with a warning under `autoadapt=debug`
alone. The shape is common: two instances of one model with the shared bus at the same
port (`N1 x s1 bm` / `N2 x s2 bm`, the deck of two other suites) is always a tie.

## What changed

- **A tie is decided by the instance names**, the one that sorts first (case-folded)
  taking the forward side. As arbitrary as the port convention, but a property of the
  two lines and not of their order, so a reordered deck is the same circuit. The
  choice is said in every mode, quiet default included, with the way to make the other
  one:

```
Note: autoadapt: node 'b' sits at port 0 on both n1 and n2, so the port rule cannot orient the adapter; n1 takes the forward side (b_f, the adapter's first port) by name order, whatever the deck order -- `.adapt b:n2` puts n2 there instead, or split the node by hand.
```

- **`.adapt node:inst` names the forward device.** A `.adapt` member may carry the
  device after a colon — `.adapt b:n2` — and that device takes `_f`, the adapter's
  first port, whether or not the port rule would have chosen it; the port rule and the
  name order apply only when no member says. A device that is not one of the two
  sharing the node is an error, not adapted. The member still selects the node as any
  `.adapt` member does (E-467's "names a node that is not shared" and E-593's listed
  refusals read the part before the colon), so `.adapt b:n2, nosuch` adapts `b` and
  reports `nosuch`. The spelling is a colon because numparam reads a `name=value` on
  a dot card as a parameter assignment and rewrites it.
- The debug-mode "falling back to deck order" warning is gone; the `split` line names
  the forward device as before.

## Verification

`autoadapt` section E-729, the asymmetric `amod2`: the two hand-written orientations
read differently (the control); the tie deck adapts with `n1` forward, the note is
printed, and the lines the other way round give the same answer (deck order used to
give the other); the note is printed in the quiet default mode too; `.adapt b:n2` gives
the hand-written `n2` answer with no note, whatever the deck order; `.adapt b:n9` is the
error and the deck reads as unadapted; without a tie the port rule puts `n1` (port 1)
forward with no note and `.adapt b:n2` overrides it to the hand-written `n2` answer;
`.adapt b:n2, nosuch` adapts `b` with `n2` forward and reports `nosuch`. On the E-728
binaries eight of the nine fail; the control passes. `adaptlisted`'s chatter filter,
which counted every line naming `autoadapt` as a refusal, passes the note (its decks
are ties, adapted with `n1` forward as before, so its values are unchanged).

By hand: the hunt's harness B [B1] decks on both binaries (0.3333333 unadapted and the
note with the first cut, which refused the tie; the name-order answer with this one);
the fourteen suites; the sweep.

## What this does not do

- The port rule is unchanged where it applies: the higher port index is forward, and a
  deck that relied on it reads as before.
- A tie between two devices of a *symmetric* adapter reads the same either way; the
  note is printed all the same, since the option cannot tell.
- `.adapt node:inst` does not select a device by model or by position — the instance
  name, whole or local (`x1.n1` answers to `n1`), is the only spelling.
- A first cut refused the tie outright, E-463's "a refusal rather than a guess", and
  two existing suites showed the shape is the ordinary one for two instances of one
  model; a refusal would have unadapted decks that adapt today. The name order keeps
  them adapted and says so.
