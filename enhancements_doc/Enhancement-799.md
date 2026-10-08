# Enhancement-799: a value out of a paramset member's range names the member that takes it — for any write, not only a corner's

**Scope:** D4 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `osdi/osdisetup.c`: new `osdi_oob_member_note`, printed after E-558's range line when
  E-668's corner note does not apply.

`examples/osdislips_examples/` (section [4], five checks). **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 56 of 56 per solver (3 of the 5
in [4] fail on the E-795 binaries); the full sweep, 538 of 538.

## What was wrong

A paramset family: member `rs` takes `l` in [1:10), member `rs__2` (the second `rs`) takes
[10:100]. The netlist's `.model rsm rs l=2` binds n1 to `rs`, as LRM 6.4.2 chooses (E-644).
Then:

```
altermod rsm l=20        (or: alter n1 l=20)
op
Parameter l of 'n1' is out of bounds (value 20; range from [1:10))!
```

and the op is refused. The line names the range of the member n1 is bound to. It did not say that
a sibling takes 20, or that the member is chosen when the netlist is read and not again. E-668
gives exactly that second line when a *corner* moves a value out of the member's range, and only
then.

The hunt page suggested that a `reset` re-binds. It does not help here: `reset` reloads the
netlist, and with it the netlist's `l=2`, so the `altermod` is undone rather than re-bound.

## The change

When a real scalar is out of bounds and no corner is the cause, `osdi_oob_member_note` checks
whether the device type is a member of a paramset family. If it is, it adds:

```
  'n1' was bound to member 'rs' of the paramset family 'rs' when the netlist was read (LRM 6.4.2), and a member is not chosen again after that; member 'rs__2' accepts 20: write l=20 in the netlist (the instance line, or the card) and load it again to bind there
```

or, when no member accepts the value, `; no member of the family accepts 200`. The acceptance
test is E-668's `osdi_member_accepts`. The corner case keeps its own wording.

## The checks

osdislips [4]:

- `altermod rsm l=20`, then `op`: the range line, then the member line naming `rs__2`;
- `alter n1 l=20`: the same;
- `alter n1 l=200`: "no member of the family accepts 200";
- an ordinary ranged parameter (no paramset) gets the range line alone;
- `l=20` written in the netlist binds `rs__2` (50 µA): the remedy the line gives.

## Limits

- The member is still not re-chosen at run time; that would move the instance to another device
  type. The line says how to get there.
- Integer and string parameters out of a member's range get the range line alone. Paramset
  bindings are on real parameters in every case seen.
