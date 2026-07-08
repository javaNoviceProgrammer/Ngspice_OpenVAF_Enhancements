# Enhancement-41 — implicit nets in instance connections

This document describes the change made to **OpenVAF-r** in the `version11/`
directory to support **implicit nets**: a plain identifier used in a
module-instance port connection that names nothing declared in the enclosing
module is implicitly declared as a scalar net. One-file change in the
Enhancement-5 elaboration pass (`hir/src/elaborate.rs`); no OSDI/ngspice change.

## Semantics (and the Verilog-A subtlety)

Per the LRM's structural-connection semantics, undeclared interconnect names in
instance connections are implicit nets — the idiom every netlist-style module
relies on:

```verilog
module top(in, out);
  inout in, out;  electrical in, out;
  res2 r1(in, mid);        // `mid` never declared -> implicit net
  res2 r2(mid, out);
endmodule
```

In full Verilog-AMS the implicit net's discipline comes from the
`` `default_discipline`` directive — but the Verilog-A appendix **excludes that
directive** ("not supported in Verilog-A"; every net's discipline must be
defined). The two statements reconcile through discipline resolution: the
implicit net takes its discipline **from the connected port** — exactly what
resolution produces for the common case of joining compatible ports. That is
what Enhancement-41 implements:

- the implicit net's discipline = the discipline of the target module's port it
  is connected to (fallback `electrical` if the port has none);
- two connections implying **conflicting** disciplines for the same implicit net
  are a hard error (`implicit net 'mid' is connected to ports of conflicting
  disciplines 'electrical' and 'thermal' — declare it explicitly`);
- `` `default_discipline`` remains ignored (the preprocessor has always parsed
  and discarded it), per the appendix;
- implicit declaration is **structural-only**: an undeclared identifier inside
  `V()`/`I()` access functions remains a clean scope error.

Before this change, every internal wiring node had to be declared manually —
`error: 'mid' was not found in the current scope`.

## Implementation

Implicit nets are synthesised in the module-instantiation **elaboration pass**
(Enhancement-5's compile-time flattening, `hir/src/elaborate.rs`):

- while binding an instantiation's port connections, a `PortBinding::Scalar`
  whose text is a plain identifier (`as_plain_ident`) naming nothing in the
  parent module's declarations (`declared_names`: net/port base names,
  bus/array base names, parameters, variables, branches, functions, instance
  names) is recognised as implicit;
- the net becomes a **local of the parent module**, so it takes the parent's
  instance prefix like every other local — two flattened instances of the same
  submodule therefore keep their internal implicit nets **distinct** (no
  accidental cross-instance shorts);
- its declaration (`electrical top__mid; // implicit net`) is emitted exactly
  once, prepended to the parent's rendered body so it precedes every use;
- discipline conflicts collect into a hard `anyhow` error at the end of
  elaboration.

Both positional (`r1(in, mid)`) and named (`.n(mid)`) connection forms work;
the same implicit net may appear in any number of connections.

## Verification — `implicitnet_examples/`

`implicitnet_demo.va` chains two `ser2k` submodules — each with its **own
implicit internal net `w`** — through an implicit top-level `mid`, mixing
positional and named forms. `verify_implicitnet.py` (ALL PASS):

1. it **compiles** (used to error);
2. the DC resistance is exactly **4 kΩ** — proving `mid` joined the instances
   *and* the two nested `w` nets stayed distinct after flattening (a
   cross-instance short would read 2 kΩ);
3. conflicting-discipline connections are rejected with a clear message;
4. an undeclared identifier inside `V()` access remains an error.

Regressions: all **37** version11 example verify suites ALL PASS, all **79**
example models recompile, and the `instantiation`/`generate` decks (the heavy
users of the elaboration pass) run unchanged.
