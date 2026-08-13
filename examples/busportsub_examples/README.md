# A Verilog-A bus port driven through a subcircuit

A worked example of connecting a Verilog-A **bus port** by one name, including
from inside a `.subckt` — [Enhancement-444](../../enhancements_doc/Enhancement-444.md)
and [Enhancement-449](../../enhancements_doc/Enhancement-449.md).

`va_res.va` is an ordinary two-terminal resistor whose pins are declared as a
single bus port:

```verilog
inout [0:1] p ;
electrical [0:1] p ;
V(p[0], p[1]) <+ R_ohm * I(p[0], p[1]) ;
```

so the compiled model has the terminals `p[0]` and `p[1]`. With
`.option autobus`, one node name on the instance line stands for the whole bus.

## The two decks

Both build the same divider — two 1 kΩ instances in series from `V1` to ground —
so `v(b)` is exactly half of `v(a)` at every sweep point.

| deck | subcircuit | `.subckt` line |
|---|---|---|
| `mycircuit.cir` | `mysub.subckt` | `.subckt mysub q[0] q[1]` |
| `mycircuit2.cir` | `mysub2.subckt` | `.subckt mysub2 q[0:1]` |

They are the same interface spelled two ways — per-bit ports, and a range — and
produce bit-identical results. `q[0:1]` is the tidier form. In both, the device
line inside the subcircuit connects the whole bus by its base name:

```
N1 q va_res
```

## The rule worth remembering

**The bare-name shorthand is for the device line, not for the `.subckt` port
list.** A `.subckt` line is parsed long before any model is known, so nothing
there can tell that `q` is two bits wide:

```
.subckt mysub2 q          <- ONE scalar port
X1 a b mysub2             -> Too many parameters for subcircuit type "mysub2"
```

Give the ports their width (`q[0:1]` or `q[0] q[1]`) and let the device line
inside bind the bus by name.

A scalar port is still useful for a different shape: passing the bus **base
name** through, so the bits appear in the caller's scope as `z[0]`, `z[1]`:

```
.subckt s q               X1 z s        ->  p[0] = z[0],  p[1] = z[1]
N1 q va_res
.ends
```

Both shapes are pinned by `verify_busportsub.py`, along with the control that
without `.option autobus` the bus is not bound by name at all and the
unconnected terminals are reported.

## Running it

```
python3 verify_busportsub.py
```

Exhaustive checks of the underlying mechanism — bit order, descending
declarations, nesting, multiple bus ports, what must not change — live in
[`subbus_examples`](../subbus_examples/). This directory is the end-user shape.
