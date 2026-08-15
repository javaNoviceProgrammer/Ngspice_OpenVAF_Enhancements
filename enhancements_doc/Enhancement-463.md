# Enhancement-463 — `.option autoadapt`

A device often has to sit *between* two others that share a bus node. Written by
hand that means renaming the shared node on both instances and keeping the two
halves consistent:

```
N1 a b mymodel1                 N1 a b_f mymodel1
N2 b c mymodel2       ->        N2 b_r c mymodel2
                                n_adapt1_ b_f b_r amod
```

With `.option autoadapt adapter=<model>` the deck is written as the left-hand
form and ngspice performs the split.

## Where it runs, and why that is the whole design

Between `INPpas1` and `INPpas2` (`spiceif.c`). Three things have to be true at
once, and only that seam satisfies all three:

- **pas1 has built the model table**, so a line's *port structure* is knowable.
  "Is this token a bus node, and how wide?" cannot be answered by a textual pass
  earlier in `inpcom.c`, which is where the closest existing machinery
  (`inpc_probe.c`, which renames a terminal's node and splices an element across
  the gap for `.probe`) lives.
- **Subcircuits are already flattened**, so "inside a subcircuit" needs no second
  implementation — the bill Enhancement-449 paid to give autobus one.
- **INP2N has not run**, so the rewrite is at the TOKEN level and `.option
  autobus` then expands all three lines. The bus handling is not extra work; it
  is a consequence of the seam. Injecting after expansion would mean emitting one
  adapter per bit and getting the pairing right by hand.

## The rules, each a refusal rather than a guess

| situation | what happens |
|---|---|
| token occurs exactly twice, both bus ports of equal width | adapted |
| node also touched by a resistor — three occurrences | refused, reported |
| both occurrences on **one** device | error |
| three or more OSDI ports | refused, reported |
| widths differ, or differ from the adapter's | error |
| `autoadapt` without `autobus` | error — it would otherwise do nothing at all |
| adapter model missing, not OSDI, or not two equal-width bus ports | error |
| `b_f` or `b_r` already in the deck | error |
| shared **scalar** node | never adapted |

**The forward side comes from the port index, not the deck order.** The device
whose port index is higher gets `_f`. Deck order would have been easier and is
what the original sketch implied, but a SPICE deck is order-independent, and
making a reordering change the circuit would be a worse bug than the one this
fixes. The suite reverses the two instance lines and requires the same answer.

`.adapt n1, n2, ...` restricts the node set; absent, every qualifying node is
adapted. Matching is by whole token — a substring test would make `.adapt bb`
silently select `b` — and a flattened node's trailing component is accepted, so
one `.adapt b` covers the same local node in every instance of a subcircuit.

## Three things the prototype found that the design discussion did not

**The adapter's `.model` card was deleted before the pass could use it.**
`inp_rem_unused_models` comments out models nothing references, and at that point
nothing references the adapter — the instance that will use it does not exist
yet. The symptom pointed somewhere else entirely: `Unable to find definition of
model amod`, blaming the injected instance rather than the card silently removed
thousands of lines earlier. The cull now protects the model named by `adapter=`.

**It was not idempotent.** A deck already carrying adapters had them adapted in
turn — `b_f` becoming `b_f_f`/`b_f_r` with a second adapter between — and the
answer moved from 0.7590 to 0.7647. An instance *of the adapter model* is now
never a candidate.

**A reference to a bus BIT is a use of the bus.** The occurrence count first
looked only for the bare token, so `Rb0 b[0] 0 1k` was invisible: the bus was
split and the resistor left on an orphan node, silently. Both spellings now
count — `b[0]`, and `b_0_` under Enhancement-462's KiCad spelling.

## Known limitation, deliberately out of scope

Inside a subcircuit this works when the shared bus node is **local**. When an
OSDI instance line mixes an expanded bus *formal* with a local bus node, nothing
is adapted — which is the wanted behaviour for an interface port, and falls out
of the "exactly twice" rule on its own, since an interface node appears once.

But that configuration is *already* broken without this feature, and the control
proves it: with the adapter hand-written and `autoadapt` off,

```
.subckt s a[0] a[1] a[2] a[3]
N1 a b mymodel1          <- bus FORMAL a, local bus b
```

reports `3 of the 8 terminals of model type 'chan' are not connected` and answers
1.0 where the hand-flattened equivalent answers 0.5238095. Enhancement-449
expands the bus formal into its four actuals while the local bus base stays one
token, so the line carries five node tokens where autobus needs two or eight;
the tokens then bind positionally and the top three bits dangle. Fixing it needs
E-449 to tell INP2N which token ranges it already expanded — the caller's actuals
(`n0 n1 n2 n3`) are indistinguishable from an ordinary bus base — so it is its
own change, tracked separately rather than bundled here.

## Verification

`examples/autoadapt_examples/verify_autoadapt.py` — **26/26**, both solvers.
Every value check is a differential against the same circuit with the adapter
written out by hand, on a ladder where every bit reads differently so a
mis-paired, reversed or dropped adapter cannot pass by coincidence. Also pinned:
the port-index orientation and its invariance to deck order, a local shared node
inside a subcircuit giving the flat circuit's answer, idempotence on an
already-adapted deck, all nine refusals above, `.adapt` whole-token matching
including the subcircuit-local form, two shared nodes in one deck, the option off
leaving the deck untouched, and E-438's checker accepting both new option names
while still flagging an unknown one.

Full regression **377/377**, both solvers. ngspice-only; no compiler change.
