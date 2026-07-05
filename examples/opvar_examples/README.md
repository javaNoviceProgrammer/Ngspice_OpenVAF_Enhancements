# opvar_examples — operating-point variables end-to-end (Enhancement-69)

Validates **operating-point-variable (opvar) access** — Verilog-A module
variables carrying a `(* desc="..." *)` attribute, exposed through the
OSDI descriptor — across every ngspice access path, using the committed
`openvaf-r` and `ngspice-46`. The audit found the surface **fully
working**; like Enhancements 57/60/66, the deliverable is the validation
itself (no source changes).

| path | verdict |
|---|---|
| `.op` + `print @inst[var]` | real and integer opvars exact; a variable *without* a desc attribute is correctly not exposed (clean error) |
| `.save @inst[var]` in `.tran` | per-point vectors for real **and integer** opvars (the E-32 outitf fix, finally pinned) |
| `.dc` sweeps | per-point, exact values, integer flag steps at the right sweep point |
| `.ac` | op-value recorded per frequency point; two instances stay distinct |
| `.meas` | MAX/MIN/AVG on opvar vectors, and `WHEN ... RISE` verified against the analytic crossing time asin(0.5)/2π |
| string opvars | display via `show <inst>`; the vector path is inherently numeric and fails with a clear message (pinned), not a crash |

## Run

```bash
python3 verify_opvar.py    # 11 checks
```
