# Proposal — `.option autoadapt`: orientation from the models, and a split that keeps the net's name

*Scoped 2026-09-26, after the question "the `_f`/`_r` renaming is not deterministic
and depends on how the netlist is generated, and the original net name is lost —
is there a better way?" Nothing here is implemented. The feature as it stands is
[E-463](../../enhancements_doc/Enhancement-463.md) with the orientation fix of
[E-729](../../enhancements_doc/Enhancement-729.md) and the reference handling of
[E-572](../../enhancements_doc/Enhancement-572.md) and
[E-592](../../enhancements_doc/Enhancement-592.md); the code is `INPadapt` in
[`inp2n.c`](../../ngspice-46/src/spicelib/parser/inp2n.c).*

## What the feature does today

A shared bus node between two OSDI instances is split and an adapter put between
the halves:

```
N1 a b mymodel1                 N1 a b_f mymodel1
N2 b c mymodel2       ->        N2 b_r c mymodel2
                                n_adapt1_ b_f b_r amod
```

Which device lands on `_f`, the adapter's first port, is decided in this order:

1. a `.adapt b:n1` member naming the forward device (E-729);
2. else the device at whose **higher port index** the shared node sits;
3. else, on equal indices, the instance whose **name sorts first**, with a Note
   in every mode saying so (E-729; before it, deck order in silence).

Every reference to the original name — `.save v(b)`, `.ic v(b[2])`, `print v(b)`
in the control block — is refused with an explanation, because `b` no longer
exists (E-572, E-592).

## The two problems, and their common root

**Orientation is deterministic per deck but keyed to incidental properties.** The
port index is a property of how the model author listed the ports; two models
that describe the same physics with `(a, b)` and `(b, a)` orient an asymmetric
adapter opposite ways. The name order is a property of how the generator numbers
instances; renumber and the adapter turns around. A generator does not control
either in any meaningful sense, which is why the result looks non-deterministic
from its side. E-463's own rule — "a SPICE deck is order-independent" — is kept
by both rules, but order-independence is not the same as generator-independence.

**The net's name is destroyed.** Renaming both sides makes the split visible in
every place the net was used, and two enhancements exist only to explain the
absence.

Both come from the same decision: the split guesses at information only the
model author has — which port faces which way — and expresses the guess by
rewriting the net. The proposal removes the guess and moves the rewrite to the
port.

## 1. Orientation declared by the model

An adapter faces one way because a port has a convention: this port emits, that
one receives; this one speaks the model's bus, that one the adapter's. That is a
property of the model. It should be declared there, on the port:

```verilog
module chan(a, b);
    (* adapt="in"  *) inout [0:3] a;
    (* adapt="out" *) inout [0:3] b;
```

The compiler carries the attribute into the OSDI node descriptor. `OsdiNode`
already carries `units`, `residual_units` and the flow flag per node, so a
`role` string is a few lines in the compiler's metadata and one field in
ngspice's reader; the descriptor version bumps as it did for E-51 and E-54.

The rule then reads:

| declared on the two ports | result |
|---|---|
| one `out`, one `in` | `out` faces the adapter's first port |
| both `out`, both `in`, or neither | **refused**, naming both devices and the `.adapt b:n1` remedy |
| a `.adapt b:n1` member present | beats the declaration, as it beats everything today |

The port index and the name order are dropped. This is E-463's refusal-over-guess
philosophy applied to the one place it was not: an undeclared orientation is an
ambiguity, and the feature already refuses every other ambiguity rather than
resolve it.

**Interim, at no cost:** a generator knows its topology, so it can emit one
`.adapt b:n1` member per adapted node today. Nothing then depends on ordering or
naming, and the members become redundant, not wrong, once the attribute exists.

## 2. Split at the port, not the net

Rename only the adapted device's port token, in the spelling internal nodes
already use (`inst#port`, as `nm1#di` for a MOSFET's internal drain), and leave
the net alone:

```
N1 a b mymodel1                 N1 a n1#b mymodel1
N2 b c mymodel2       ->        N2 b c mymodel2
                                n_adapt1_ n1#b b amod
```

What this buys:

- `b` keeps its name and every other connection. `v(b)` means what it always
  meant; `.save`, `.ic`, `.nodeset`, `.probe` and the control block need no
  special case, and E-572's and E-592's explanations become unnecessary.
- The moved side is spelled as what it is: N1's port `b`, behind its adapter.
  `v(n1#b)` is the port-side voltage, as `v(nm1#di)` is the internal drain.
- The "exactly twice" rule can go. A resistor on `b` stays on `b`; only the
  adapted port moves. E-463 refused that case because renaming the net would
  have orphaned the resistor; with the net untouched there is nothing to orphan.
- The orientation question shrinks to "which instance's port takes the adapter",
  which section 1 answers, and the node names carry no forward/reverse
  vocabulary that could be read as a claim about the physics.

The adapter's own port order is still meaningful — its first port faces the
adapted device — so an asymmetric adapter behaves as it does today; only the
naming changes.

**Migration.** Decks that already refer to `b_f`/`b_r` by hand are written for
the hand-split form, which autoadapt never touches (an instance of the adapter
model is never a candidate, E-463). Decks that let the option split and then
refer to `b_f`/`b_r` in their control block would break; a transition can keep
`b_f`/`b_r` as aliases of `n1#b`/`b` for one release with a Note, or the suite
can simply be updated, since the project's own decks are the only known users.

## 3. Further, if the feature is to stop guessing altogether

If a port can declare its convention, it can declare its adapter:

```verilog
    (* adapter="phport_adapter" *) inout [0:3] b;
```

Then the simulator inserts an adapter wherever a port of one convention meets a
port of another, by type matching, and `.option autoadapt adapter=<model>` with
its whole-deck candidate search is no longer needed: the models say where
adapters go and which way they face. This is a larger change and a different
feature. It is mentioned because section 2 is its first half and would not have
to be redone.

## A note on the photonic flow

The chip deck's optical ports are scalar real and imaginary pairs
(`dev2_ph1_2`, `dev2_ph1_3`), and autoadapt adapts bus ports only — a shared
scalar node is never adapted (E-463). Nothing in that deck is adapted today. A
port-attribute design covers scalar pairs as naturally as buses, since the
attribute sits on the port whatever its width.

## Order of work

1. Now, no code: the generator emits `.adapt b:n1` per adapted node.
2. One enhancement: the port-side split (section 2). `INPadapt` rewrites one
   token instead of two and emits `n_adapt inst#port net`; E-572/E-592's
   reference checks retire; the `autoadapt`, `autobus` and hierarchy suites are
   updated for the new spelling and gain the resistor-on-the-net case.
3. One enhancement across compiler and simulator: the port attribute (section 1)
   and the refusal; the index and name rules retire, the Note with them.
4. Later, if wanted: adapters declared per port (section 3).
