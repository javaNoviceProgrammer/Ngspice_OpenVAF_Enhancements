# paramarray_examples — name-then-range array parameters (Enhancement-102)

Verilog-AMS lets an array dimension be written before the name (type-then-range,
`parameter real [0:2] c`) or after it (name-then-range, `parameter real
c[0:2]`). openvaf-r accepted both for local variables, nets, and ports
(E-18/89/91) but only the type-then-range form for **parameters** — the
name-then-range form errored with `unexpected token '['`. Enhancement-102 closes
that gap.

`paramarray_demo.va` declares single-name, multi-name (mixed widths),
multi-dimensional, and integer-`localparam` name-then-range parameter arrays,
exposing element values as operating-point variables. The verify checks that the
file compiles, every element default resolves to its initializer value, a
per-element `.model` override (`c[1]=99`) changes only that element (the OSDI
per-element parameters from E-14 are intact), and the type-then-range form still
compiles. Run: `python3 verify_paramarray.py` (11 checks).
