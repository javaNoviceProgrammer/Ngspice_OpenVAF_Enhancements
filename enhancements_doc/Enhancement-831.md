# Enhancement-831: `.option saveused` saves the `@dev[param]` vectors a deck's `.meas` cards read, also when it otherwise stands aside

**Scope:** F15 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

ngspice:
- `frontend/dotcards.c`: when `ft_saveused` stands aside, it still registers `save all` and
  the `@`-references it collected.

`examples/limfinal_examples/` (section [3], three checks). **ngspice only.**

**Suites:** [`limfinal_examples`](../examples/limfinal_examples/) 14 of 14 per solver (1 of the
3 checks in [3] fails on the E-828 binaries; the other two are controls).
[`saveused_examples`](../examples/saveused_examples/) is unchanged. The full sweep, 546 of 546.

## What was wrong

```spice
.option saveused
.meas tran p_max max @n2[pw]     ; OSDI opvar -> "holds 1 point(s) but the analysis produced 2018"
.meas tran i_max max @r1[i]      ; built-in, the same
.control
tran 1n 2u
.endc
```

Enhancement-469's option saves what the control block reads, and Enhancement-572 added the
references the deck's own `.meas`, `.print`, `.plot` and `.four` cards make. Those include the
`@dev[param]` form. But the option acts only when the control block has an output command.
This block only runs `tran`, so it stood aside, and "standing aside" means ngspice's default
save set. That set never holds an `@device[param]` vector, so the cards' references, collected
correctly, were thrown away. With a `print` in the block, the same cards worked.

## The change

When the option is on, but stands aside (no output command, or one that names `all`), the
`@`-references it collected are still registered: `save all` and those vectors. That is
exactly what the error message advises a user to write. Plain node and branch names are in the
default set already. The save is marked as the option's own, as its inferred saves are
(Enhancement-496). Without the option, nothing changes: the stock rule stands that an
`@dev[param]` needs a `.save`.

## The checks

`limfinal_examples` [3], a built-in resistor and an OSDI module with a power opvar:
- `saveused`, a block that only runs `tran`: `max @r1[i]` = 2 mA and `max @n2[pw]` = 4 mW
  (both failed with "holds 1 point(s)").
- With an output command in the block (control): the same values.
- Without `saveused` (control): the stock rule stands.
