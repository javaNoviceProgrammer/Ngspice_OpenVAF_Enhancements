# Enhancement-817: `alterparam cell rr=100` on a parameter of the `.subckt` line changes the default, not the instances that gave their own value

**Scope:** F1 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `include/ngspice/inpdefs.h`: a new `struct card` field, `xgiven`.
- `frontend/inpcom.c`: `inp_fix_inst_calls_for_numparam` records the parameters each X line
  gives itself, before it makes them positional. `insert_new_line` clears the field.
- `frontend/subckt.c`: the three deck copies carry it. `frontend/inp.c`: `line_free_x`
  frees it.
- `frontend/inp.c`: `com_alterparam` keeps an instance's own value, moves the default on the
  `.subckt` line, and adds a Note.

`examples/subcktedit_examples/` (new; section [1], five checks). **ngspice only.**

**Suites:** [`subcktedit_examples`](../examples/subcktedit_examples/) 16 of 16 per solver (all
five checks in [1] fail on the E-816 binaries); `sweep`, `sweeprestore`, `sweepsubfast`,
`nestedsweep` and `optimize`, which use `alterparam`, are unchanged within the full sweep, 542 of
542.

## What was wrong

```spice
.subckt cell a b rr=1k
r1 a b {rr}
.ends
xa 1 0 cell rr=1k
xb 1 0 cell rr=500
xc 1 0 cell
...
alterparam cell rr=100
reset
```

After the reset every instance had 100 Ω, and i(v1) went from 4 mA to 30 mA. Only `xc`, which
took the default, should have moved: 13 mA. An OSDI card inside the subcircuit reading the
parameter (`.model gm gres g={gg}`) behaved the same, and so did a built-in resistor.

`alterparam` edits the stored deck, which `reset` re-reads. By then inpcom has rewritten each
subcircuit call (`inp_fix_inst_line`) to carry a value for every parameter, in order: the
instance's own value where it gave one, a copy of the default where it did not. The `params:`
list on the `.subckt` line also holds the inner `.param`s, which inpcom moved there. To change
a parameter, `alterparam` replaced its value on every call. That is right for an inner
`.param`, which no call gives, and is the form the manual documents (13.5.5). For a parameter
of the `.subckt` line it overwrote the instances' own values as well, and nothing could tell
the two apart any more.

## The change

- While inpcom rewrites a call, it records on the X card the names the instance gave itself
  (`card->xgiven`, e.g. `" rr "`).
- The record travels with the card through the deck copies (`inp_deckcopy`,
  `inp_deckcopy_oc`, `inp_deckcopy_ln`). So it is there in the stored deck after any number
  of resets.
- `alterparam <subckt> p=v` leaves a call that gave `p` itself alone. It replaces the value
  on the others, and moves the default on the `.subckt` line to `v`, so the stored deck says
  what it does.
- When an instance kept its own value, a Note says so:

```
Note: alterparam cell rr=100 sets the default of .subckt cell; xa, xb give rr on the
instance line and keep it.
```

An inner `.param` is never given on a call, so it still changes in every instance, as before.
The global form, `alterparam name=value`, which the `sweep` and `optimize` commands use, is
untouched.

## The checks

`subcktedit_examples` [1]:
- `xa rr=1k`, `xb rr=500` and `xc` with the default: 4 mA becomes 13 mA, and the Note names
  `xa` and `xb`.
- An inner `.param` and the line's parameter side by side: the inner one changes everywhere
  (5.5 → 10 mA), then the line's parameter moves twice (19 mA, then 14 mA).
- A call inside another subcircuit (`xin ... rr=250` in `pair`) keeps its value: 6 → 24 mA.
- An OSDI card inside the subcircuit reading the parameter: 5 → 14 mA (it was 30 mA).
