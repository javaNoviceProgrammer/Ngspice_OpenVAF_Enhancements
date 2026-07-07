# partselect_examples — part-selects in instance connections (Enhancement-85, F6)

`inst (out[3:2], in);` — the LRM pages 163–164 idiom — used to be a parse
error. `bus_split.va` drives a 4-bit bus with V(v[k]) = k volts and wires
it to three instances by slicing; each output is 2·V(msb) + V(lsb), so
the DC values pin the exact per-bit routing:

| Form | Connection | Expected |
|---|---|---|
| positional | `p1 (o1, v[3:2])` | 8 V |
| named | `p2 (.o(o2), .i(v[1:0]))` | 2 V |
| width-1 onto scalar | `s1 (o3, v[2:2])` | 2 V |

A part-select in behavioral code is rejected with a dedicated diagnostic
(also checked). Run: `python3 verify_partselect.py` (5 checks).
