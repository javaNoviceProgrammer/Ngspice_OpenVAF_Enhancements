# sweepbus_examples — Enhancement-267

The `sweep` command stored array/bus-node outputs under **mangled names**: a node
named `ph[0]` (Enhancement-221) was recorded as `ph_0_`, `ph[1]` as `ph_1_`, …. The
sweep plot listed `ph_0_`, `ph_1_`, … instead of `ph[0]`, `ph[1]`, ….

`sweep` builds a result-vector name from the output plus an appended
`_<knob>_<value>` segment; the value carries a float (`.`/`-`) that is illegal in a
nutmeg name, so the whole name was sanitized (non-alphanumeric → `_`) — which also
clobbered the user's base name. The sanitization now applies **only to the appended
suffix**, leaving the base intact, so bus nodes keep their brackets. And a bare
`-output ph[0:3]` now expands to `ph[0] ph[1] ph[2] ph[3]` (like the netlist bus
expansion). Values are unchanged.

`bus_divider.cir`: four dividers whose taps are `ph[0..3]`, swept over the top
resistance. The sweep plot now lists `ph[0]`, `ph[1]`, `ph[2]`, `ph[3]`.

## Verify

```
python3 verify_sweepbus.py
```

Four checks: `-output ph[0:3]` records `ph[0]`..`ph[3]` (range expanded, natural
names); the mangled `ph_0_`… names are gone; recorded values are the correct
divider ratios; a plain `-output vo=v(out)` is unaffected.
