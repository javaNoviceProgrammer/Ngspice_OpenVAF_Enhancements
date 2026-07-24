# `.param` fast-sweep (Enhancement-320)

Sweeping a netlist `.param` normally forces a full circuit **reset** at every
point — re-source the deck, re-expand subcircuits, re-run `CKTsetup`, and
re-order the sparse matrix — because numparam folds the parameter into device
value literals at parse time and leaves no live binding to update.

Enhancement-320 adds a fast path to the `sweep` command: when a swept `.param`
feeds **only addressable top-level device/model values**, each dependent value
is re-evaluated against the retained numparam table and pushed straight into the
live circuit with an in-place set — **no reset**. On a large circuit where the
parameter feeds only a few devices this is **~10× faster**; even when it feeds
every device it wins (the reset path must rebuild them all anyway).

The path is conservative: if the swept parameter reaches into a subcircuit body,
a structural slot (a node name, an instance/model name, `.if`, `.temp`, an
analysis card, `.option`, `.ic`, `.nodeset`, or a subckt call), or a derived
`.param`, it **disarms and falls back to the exact reset path** — so results are
always identical to today's, never a miscompute.

## Files

- `divider.cir` — a voltage divider whose series resistor is `R1 = {rval}`, a
  top-level device value. Sweeping `rval` **arms** the fast path.
- `divider_subckt.cir` — the same resistor moved *inside* a subckt. The swept
  param now feeds a subckt-body value, so the fast path **disarms** and the
  sweep uses the reset path.
- `verify_paramfastsweep.py` — checks that (1) the top-level case arms the fast
  path, (2) its swept `out(rval)` equals the closed form `R2 / (rval + R2)`, and
  (3) the subckt case falls back yet produces the identical divider values.

## Run

```
python3 verify_paramfastsweep.py
```

When the fast path arms, ngspice prints, once per sweep:

```
sweep: fast .param path armed (N value bindings, no per-point reset)
```
