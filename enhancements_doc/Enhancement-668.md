# Enhancement-668: a corner that moves a parameter out of its range says so — the corner, the nominal it moved the parameter from, and for a paramset member the family, the member chosen at the nominal and the sibling that accepts the value

**Scope:** F10 of the
[bug hunt of 2026-09-18](../docs/bug_hunts/2026-09-18_openvaf-r-corners-and-run-control.md).
ngspice: `src/osdi/osdisetup.c` (`osdi_oob_corner_note`, called from
`handle_init_info`'s out-of-bounds branch), `src/osdi/osdiinit.c`
(`osdi_member_accepts`), `src/include/ngspice/osdiitf.h`.
`examples/vacorner_examples/` (four checks added, 31 per solver). Handbook
[§3.7](../docs/handbook/03-ngspice-workflows.md). **ngspice only.**

**Suites:** [`vacorner_examples`](../examples/vacorner_examples/) 31 of 31 per
solver, both solvers (3 of 31 fail on the E-666 binaries); `paramsetoverload`,
`cornerscmd`, `autocorner`, `hunt17diag`, `osdimc`, `hunt2diag`, `opvarmsg`,
`paramgiven`, `wcd`, `lrmcorner` unchanged; full sweep 530 of 530.

## What was wrong

Two `rs` paramsets over one module, members `l from (0:2u]` and
`l from (2u:inf)`, both with `(* corner="ss=+20%" *)` on `l`; the instance
gives `l=1.9u`. [E-644](Enhancement-644.md) binds the instance to the first
member when the card is materialised, from the instance's own parameters, at
the nominal. `.option corner=ss` then writes `l = 2.28u` on that member
([E-654](Enhancement-654.md)), and the temperature pass refuses it:

```
Parameter l of 'n1' is out of bounds (value 2.28e-06; range from (0:2u])!
doAnalyses: 1 errors occurred during initialization detected in routine "OSDI setup_instance (OSDItemp)"
```

[E-558](Enhancement-558.md)'s line names the parameter, the value and the
range, and nothing names the corner that moved it or the member whose range
it is; under the `corners` command the `ss` row was *(the analysis failed)*
with the same line above the table. A plain module whose corner moves a
parameter out of its own `from` range had the same silence about the corner.

## What changed

The selection cannot be re-judged at the corner: a member is a device type of
its own, chosen when the card is materialised, and a corner is a per-run
write. So the failure says what happened, on a second line under E-558's:

```
Parameter l of 'n1' is out of bounds (value 2.28e-06; range from (0:2u])!
  corner ss moved l of 'n1' there from its nominal 1.9e-06 (+20%); 'n1' was bound to member 'rs' of the paramset family 'rs' at the nominal (LRM 6.4.2); member 'rs__2' accepts 2.28e-06: give l on the instance inside the member the corner lands in, or name that member on the card
```

- **The corner part** is printed when the corner in force names the parameter
  and the refused value is not the entry's nominal: the corner, the nominal it
  moved the parameter from, and how (`+20%`, `+3 sigma`, `absolute`). A plain
  module gets this line alone.
- **The member part** is added when the descriptor belongs to a paramset
  family: the family, the member the instance was bound to at the nominal,
  and every sibling whose range for that parameter accepts the value
  (`osdi_member_accepts`, which judges one member's parameter by E-558's range
  text through E-644's parser), or *no member of the family accepts* it.
- No note when the corner stays inside the range, nor when a card value is
  out of range with no corner in force.

## Verification

| check | result |
|---|---|
| the two-member `rs` family, `l=1.9u`, `.option corner=ss`, `op` | E-558's line, then the second line above; the run refused |
| a plain module, `.model pm plain_va l=1.9u`, corner `ss=+20%` on `l from (0:2u]` | *corner ss moved l of 'pm' there from its nominal 1.9e-06 (+20%)*, no member part |
| the same at `l=1.5u`; and `l=2.5u` on the card with no corner | 1.8e-06 runs, no note; the E-558 line alone |
| `corners -output l=@n1[l]` on the family | the tt row 1.9e-06, the ss row *(the analysis failed)*, the note once |
| `l=2.5u` on the instance (bound to `rs__2`), corner ss | 3e-06 runs |
| the E-666 binaries on the suite | 3 of 31 fail |

Full sweep 530 of 530 on both solvers.

## What this does not do

- The member is not re-selected with the cornered value; the note says which
  member would take it and how to get there.
- An integer or string parameter has no corner, so only the real branch of
  the out-of-bounds message carries the note.
