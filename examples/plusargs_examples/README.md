# plusargs_examples — Enhancement-215: `$test$plusargs` / `$value$plusargs`

Command-line **plusargs** let a Verilog-A model read `+name[=value]` arguments
passed to ngspice, so a corner or a feature flag is chosen at **run time without
editing the deck**:

```sh
ngspice -b deck.cir +corner=ff      # $value$plusargs("corner=%s", c)  -> c = "ff"
ngspice -b deck.cir +gain=25        # $value$plusargs("gain=%d", n)    -> n = 25
ngspice -b deck.cir +boost          # $test$plusargs("boost")          -> true
```

Before E-215 these were the constant fallbacks of [Enhancement-12](../../enhancements_doc/Enhancement-12.md):
`$test$plusargs` always returned false and `$value$plusargs` never wrote its
output. They are now served through the OSDI **simparam channel** — ngspice
collects each `+`-argument and a compiled model looks it up — with no OSDI ABI
change.

## How it works

- **ngspice** (`main.c`, `osdiload.c`): each `+name[=value]` on the command line is
  registered and exposed as namespaced simparams — `$test$plusargs$name` (present),
  `$valset$plusargs$name` (given in `name=value` form), `$valnum$plusargs$name` (the
  value as a number) and `$value$plusargs$name` (the value as a string).
- **openvaf-r** lowers `$test$plusargs("name")` to a presence lookup and
  `$value$plusargs("name=%fmt", var)` to a value lookup by the target's type
  (number or string), writing `var` and returning whether a value was matched.

`$value$plusargs` matches only the `name=value` form (a bare `+gain` is *not* a
value match), exactly as the LRM specifies.

## Files

| File | What it is |
|---|---|
| `plusargs_demo.va` | A conductance set from plusargs — presence (`+boost`), integer (`+gain=n`), real (`+scale=x`) and string (`+corner=ff\|ss`) — observable as a DC current. |
| `verify_plusargs.py` | 12 checks (compile + the full plusarg matrix), both solvers. |

## Run

```sh
python3 verify_plusargs.py
```
