# Enhancement-221 — array/bus node ranges in the netlist

ngspice has no bus/array node syntax: a node is an opaque string, and a range
like `a[0:1]` is read as a single literal node name (so `R1 a[0:1] r=2k` gives
`R1` only one node token and then misparses `r=2k`). E-221 adds a netlist
pre-processing pass that expands a **range token** `base[lo:hi]` into the scalar
node sequence it denotes, so buses can be written compactly:

```
R1 a[0:1] r=2k          ->  R1 a[0] a[1] r=2k          ; a 2-terminal R
X1 n[0:3] mysub         ->  X1 n[0] n[1] n[2] n[3] mysub
.subckt mysub p[3:0]    ->  .subckt mysub p[3] p[2] p[1] p[0]
```

The range supplies node tokens **positionally** — the "two terminals" reading:
`R1 a[0:1]` is a single resistor from `a[0]` to `a[1]`, not an array of
resistors. Multi-terminal instances, subcircuit calls, and `.subckt` port lists
expand the same way.

## Semantics

- **`base[lo:hi]`** expands to `base[lo] base[lo±1] … base[hi]`. The sequence
  **descends when `lo > hi`** (the Verilog convention: `d[3:0]` → `d[3] d[2]
  d[1] d[0]`); `a[0:0]` is a single element.
- The scalar names use the same bracket form, so a bus `a[0:1]` and an explicit
  `a[0]` denote the **same node** — the two forms interoperate freely.
- Only a **whole whitespace-delimited token** that is exactly `base[int:int]` is
  expanded. Already-scalar names (`a[0]`), non-integer ranges (`a[x:y]`),
  malformed ones (`a[1:2:3]`), device values, model names, and XSPICE
  `%vd[…]` port groups are all left untouched.
- `.control … .endc` blocks are skipped entirely, and only element lines and
  `.subckt` lines are processed (`.model`/`.param`/other dot cards are ignored).
- A range wider than 8192 elements is left literal (the device parser then
  reports it) rather than expanded, so a typo like `a[0:1000000000]` cannot
  exhaust memory.

## Implementation

One pass, `inp_expand_buses`, in `frontend/inpcom.c`, run in `inp_readall` right
after whitespace normalisation and **before** subcircuit expansion and device
parsing — so every downstream consumer (numparam, `.subckt` expansion, the
device parser, OSDI) sees the already-scalar node list and needs no changes.
Continuation lines are stitched earlier in `inp_read`, so each logical line is
processed whole. The token test parses `base` (a plain node name), then
`[<int>:<int>]` filling the rest of the token, and emits the element list with
`DSTRING`; a non-match copies the token verbatim.

## Verification (`examples/busnodes_examples`)

`verify_busnodes.py` (6 checks, both solvers) drives `busnodes_demo.cir` and
confirms the expansion from node voltages / branch currents alone (so it is
solver-independent):

1. `R1 a[0:1] r=2k` connects `a[0]`–`a[1]`: `I(R1) = (1-3)/2k = -1 mA`;
2. the scalar `R2 a[0]` addresses the **same** node as the bus element
   (`I = +0.25 mA`, only correct if `a[0]` is one shared node);
3. a subcircuit with a **descending** port bus `p[1:0]`, called with
   `X1 n[0:1]`, connects positionally (`I(Rs) = -5 mA`);
4. non-integer (`b[x:y]`), malformed (`c[1:2:3]`) and scalar tokens are left as
   literal node names, and a `.control` `let w = a[0:1]` is **not** rewritten.

Full regression: 180/180.

## Scope

ngspice only, one file (`frontend/inpcom.c`). Purely a netlist-text
pre-processing pass; no device, solver, or OSDI change. A deck with no
`base[lo:hi]` token is untouched (a fast path skips any line without `[`).
