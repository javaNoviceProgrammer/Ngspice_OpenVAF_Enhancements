# portconnected_examples — `$port_connected` against LRM 9.19 and 6.5.6

A compliance pin, written on 2026-09-06 after re-reading the clause and probing every
rule in it on the committed `openvaf-r` and `ngspice-46`, both solvers. Nothing had to
change; this suite keeps it that way.

| file | what it pins |
|---|---|
| `lrm_p251_clocks.va` | the clause's own `myclk` / `twoclk` / `top` example: a clock's `vout_q` is connected at its own instantiation line and `vout_qbar` is not, even though the top leaves `vout_q2` open; the `transition` filter under a false guard is dropped and the connected clock toggles |
| `netlist_terminals.va` | the netlist route: a trailing terminal the instance line omits reads 0 (with E-402's warning), a dangling node reads 1 ("a net that has no other connections … shall still return one"), ground reads 1; under `.option silentports=ground` the omitted terminal is grounded by the option and reads 1 (E-482) |
| `bus_bits.va` | bits of a vector port by bit-select and through a `genvar` loop, on the netlist route (trailing bit omitted) and through positional and named `{x, y}` connections |
| `nested_open.va` | two levels down: an open named connection `.q()` reads 0, a dangling internal net of the parent reads 1 |
| `instance_array.va` | `leaf u[0:1] (…, .q())` reads 0 on each element |
| `refused/` | a whole vector port, an internal net, an expression, a call inside an analog function (the port is not in scope), a parameter default or `localparam` (not a constant expression, Table 9-16) |

The value is fixed at elaboration: a flattened instance's call is resolved to a
literal by the elaborator, a top-level module's from the instance line's terminal
count at setup, and neither moves during a simulation.

## Run

```
python3 verify_portconnected.py
```

23 checks per solver, all PASS.
