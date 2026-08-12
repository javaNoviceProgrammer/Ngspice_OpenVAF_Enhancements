# Enhancement-444 — `.option autobus`

A Verilog-A bus port

```verilog
module busdev(a, b);
    inout [0:4] a;
    electrical [0:4] a;
    inout b;
```

compiles to five OSDI terminals named `a[0]` … `a[4]`, so the netlist has always
had to spell all five out:

```
N1 a[0] a[1] a[2] a[3] a[4] b busdev
```

The model already knows its own shape. With the option set, one token per
**port** is enough:

```
.option autobus
N1 a b busdev        ->    N1 a[0] a[1] a[2] a[3] a[4] b busdev
```

and `a[2]` elsewhere in the deck binds to the same node, nodes being unified by
name. The token you write is what gets indexed — `N1 foo b` gives `foo[0]` …
`foo[4]`.

## The information was already in hand

`INP2N` resolves the model *before* it binds nodes, and `dev->termNames[]` holds
exactly `a[0] a[1] a[2] a[3] a[4] b`. Enhancement-402 was already reading that
table — but only to *report* which terminals a short line had left unconnected:

```
Warning: instance n1: 4 of the 6 terminals of model type 'busdev' are not connected.
         terminal 3 ('a[2]') is absent
```

This uses the same table to connect them instead. Terminals are grouped into
ports — consecutive `base[i]` sharing a base is one bus port, a bracket-free
name is a scalar port — and a line supplying one token per port is expanded.
`busdev` is 2 ports against 6 terminals.

**The indices come from the model, not from a count.** A port declared `[4:1]`
expands to `a[1]` … `a[4]`; the bracket text is copied from the model's own
terminal name rather than generated as `0..n-1`.

## Why it is opt-in

A short instance line already means something: it leaves trailing terminals
unconnected, which is the `$port_connected` idiom that BSIMSOI, BSIM-CMG/IMG/
BULK, BSIM6 and PSP-HV rely on. Without `.option autobus` nothing changes at
all.

Even with the option on, the two readings barely overlap: expansion needs the
token count to equal the *port* count, and a model whose ports are all scalar
has port count == terminal count, so a short line can never be mistaken for the
shorthand. The three-scalar-port model in the suite is checked to produce
byte-identical output with the option on and off.

The option name is registered with Enhancement-438's `.options` checker, so
`.option autobus` is not reported as an unknown option — with a control in the
suite proving that check still flags a name that genuinely is unknown.

## Where it happens, and what that costs

Expansion needs the model, so it happens at device-parse time rather than
netlist-read time. That is invisible in use, but it means the expansion does not
appear in `listing e` the way Enhancement-441's array instances do: the listing
shows the line as written. Node ranges in the netlist (E-221/E-443) are a
text-level rewrite and happen earlier; this one cannot be, because at that point
no model is bound.

## Verification

**`examples/autobus_examples` — 12/12, both solvers.** Every check that matters
is a differential, because "it ran" proves nothing here:

* `N1 a b` with the option reads **bit-identical** to the same circuit written
  out in full — on a ladder where all five bits sit at different voltages, so a
  mis-ordered or mis-indexed expansion cannot pass by coincidence (the suite
  asserts the five values are distinct).
* A bus declared `[4:1]` matches its explicit form, pinning that indices come
  from the model.
* Two bus ports on one device fill correctly against the explicit form.
* Without the option, a short line still produces E-402's under-connected
  warning naming `a[2]`.
* The `$port_connected` idiom gives identical results with the option on and
  off.
* A fully spelled-out line is unaffected by the option — no double expansion.

**Full regression 356/356**, both solvers.
