# Enhancement-90 — multi-bit input bus port bit reads

This document describes Enhancement-90, a compiler fix for reading an
individual bit of a **multi-bit input bus port** declared in the non-ANSI
(Verilog-2001) header style. It is the follow-up to the terminal-mapping
oddity noted while finishing Enhancement-89.

## The symptom

A module that reads one bit of a multi-bit *input* bus port returned the
wrong value (often 0) when the bus was not the last port in the header:

```verilog
module m(in, y);
   input  [0:2] in;      // 3-bit input bus, declared in the body
   electrical [0:2] in;
   output y; electrical y;
   analog V(y) <+ V(in[1]);   // reads the middle bit
endmodule
```

Driving the three bus terminals with 1 V, 2 V and 3 V, `V(y)` did not read
2 V. A scalar input port worked, and the Enhancement-89 *name-then-range*
spelling (`input in[0:2];`) behaved identically to the *range-then-name*
spelling — so this was not an E-89 regression but an older defect in E-3
territory (vectored ports).

## Root cause — scrambled terminal order

The bug was purely in **node ordering**, not the physics. The DAE for the
module above is correct: four unknowns, with the residual at `y` depending
on `V(in[1])`. But the OSDI descriptor presented the terminals out of
order.

OpenVAF builds a module's node list in two steps for a non-ANSI header:

1. the header (`module m(in, y);`) creates one placeholder node per port
   name, in header order: `in`, then `y`;
2. the body declarations fill in each port's direction, discipline and
   width. Expanding the bus `input [0:2] in` renamed the `in` placeholder
   to `in[0]` (its first bit) but **appended** the remaining bits `in[1]`,
   `in[2]` at the end of the node list — *after* the `y` placeholder.

The resulting node order was therefore

```
[ in[0], y, in[1], in[2] ]      // wrong
```

instead of the header-port order

```
[ in[0], in[1], in[2], y ]      // right
```

Because the OSDI ABI maps a netlist instance's terminals **positionally**
to the first `num_terminals` nodes, this scramble mis-wired the bus bits:
netlist terminal 2 landed on `y`, terminal 3 on `in[1]`, and so on. The
scramble only appeared when a multi-bit bus port was *not* the last port
(when it is last, the appended bits happen to fall in the right place),
which is why it had gone unnoticed. A true ANSI header
(`module m(inout [0:2] in, inout y);`) was already correct, because there
the bus is expanded in place while the header is processed.

## The fix

`hir_def/src/item_tree/lower.rs` now pre-scans the body port declarations
for each port's width *before* creating the header placeholders
(`prescan_body_port_widths`). When `lower_module_ports` meets a non-ANSI
header port name that a body declaration gives a width to, it expands the
bus into its bits *there*, in header-port order, so the bits stay
contiguous:

```
[ in[0], in[1], in[2], y ]
```

The `BusDecl` itself is still registered by the body declaration, so bit
selects resolve exactly as before; only the node-creation order changes.
Buses that are already the last port produce the identical node list, so
existing models (the E-3 `bus_buffer`, scalar-in/bus-out shapes) are
unaffected. Fixing the order at node creation means the DAE unknowns, the
Jacobian, and the OSDI terminal array all follow correctly with no
downstream changes.

## Verification

- `busport_examples` (6/6, ngspice runtime pins): a bus-first model reads
  each bit distinctly (`o0=in[0]=1 V`, `o1=in[1]=2 V`, `o2=in[2]=3 V`); a
  model with the bus in the *middle* of the header reads its bits correctly
  (`q = V(in[2]) − V(in[0]) + V(p) = 2.5 V`); and the E-89 name-then-range
  spelling of the same bus reads identically.
- A permanent DAE snapshot regression guard (`sim_back` `bus_input_port_order`)
  pins the header-order node layout for a bus-not-last module.
- Full regression: 81/81 verify suites, 28/28 integration tests, and the
  parser/hir/sim_back snapshot suites all green.

## Gotcha recorded

- The scramble is invisible when the bus is the last port and invisible in
  a true ANSI header — it only bites a non-ANSI header where a multi-bit
  bus port is followed by another port. Diagnosing it required dumping the
  OSDI node array order, not just the DAE physics (which was correct).
