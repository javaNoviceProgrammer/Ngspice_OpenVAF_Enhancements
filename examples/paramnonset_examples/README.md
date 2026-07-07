# paramnonset_examples — warn when a fixed (localparam) parameter is set (Enhancement-93)

A Verilog-A `localparam` (including a structural width parameter frozen by
Enhancement-92) is now flagged non-settable in the OSDI parameter descriptor
(`PARA_FLAG_FIXED`). ngspice warns — instead of silently swallowing the value —
when a netlist tries to set one. Requires both the Enhancement-93 openvaf (sets
the flag) and ngspice (checks it, warns).

`paramnonset.va` — overriding the frozen width parameter `N` (`.model ws wsum
N=8`) now prints `Warning: parameter 'N' is a fixed (localparam) value ...
ignored` and keeps the default; a hand-written localparam warns too; an
ordinary parameter (`gain`) is unaffected and still takes effect. Run:
`python3 verify_paramnonset.py` (7 checks).
