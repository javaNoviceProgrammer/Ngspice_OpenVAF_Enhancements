# alias_examples — Enhancement-12: probe / alias / plusargs functions

End-to-end verification of the final group of Verilog-AMS system functions
implemented in Enhancement-12, using **version11's own** `openvaf-r` and
`ngspice-46`:

- `$simprobe`
- `$analog_node_alias`, `$analog_port_alias`
- `$test$plusargs`, `$value$plusargs`

These have no underlying mechanism in the OSDI/ngspice target (no command-line
plusargs, no generic simulator probe, no runtime hierarchical node aliasing), so
each returns its LRM "mechanism-unavailable" fallback: a well-defined constant.
They now compile and run predictably rather than being rejected. See
`../Enhancement-12.md`.

## Files

| File | Purpose |
|---|---|
| `alias_demo.va` | Calls all five (with and without a `$simprobe` default) and writes the results to `alias_out.txt`. |
| `verify_alias.py` | Runs a `.op` and checks the results. |
| `alias_out.txt`, `_alias.cir`, `*.osdi` | Artifacts. |

## Run

```
python3 verify_alias.py
```

Expected tail:

```
ALL PASS (6/6)
```

## Expected results (`alias_out.txt`)

```
test_plusargs=0        # $test$plusargs  -> false (no plusarg present)
value_plusargs=0       # $value$plusargs -> false
node_alias=0           # $analog_node_alias -> 0 (no alias created)
port_alias=0           # $analog_port_alias -> 0
simprobe=0             # $simprobe(inst, quant) -> 0.0 (probe unavailable)
simprobe_default=3.5   # $simprobe(inst, quant, 3.5) -> the supplied default
```

Note the IEEE `$`-separated spelling `$test$plusargs` / `$value$plusargs` in the
Verilog-A source (not underscores).
