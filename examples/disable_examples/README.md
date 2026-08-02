# `disable` statement example (version10, Enhancement-9)

Demonstrates the Verilog-AMS **`disable <named_block>;`** statement, added to
OpenVAF in Enhancement-9. Verilog-A has no `break`/`continue` keywords —
`disable` is *the* early-exit mechanism, and both idioms are built from it.

## Semantics

`disable <name>;` terminates execution of the enclosing named block `name`
(`begin : name ... end`) and continues immediately after it.

- **break**: wrap a loop in a named block; `disable` that block to exit the loop
  (code after the block still runs).
- **continue**: name the *loop body* block; `disable` it to skip the rest of the
  current iteration (the loop proceeds to the next one).
- Disabling the whole `analog` block terminates it (everything after the
  `disable`, including `<+` contributions, is skipped).

## Models

- `break_demo.va`: a `while` loop inside `begin : loop_blk ... end`;
  `disable loop_blk` breaks the loop after `STOP` iterations, giving
  `Rtot = STOP * Rbase`.
- `continue_demo.va`: a `for` loop whose body is `begin : body ... end`;
  `disable body` skips the accumulation on alternate iterations, so 4 of 8
  iterations add (`Rtot = 4 * Rbase`).

## Running

```sh
../OpenVAF-master-20260610/target/opt/openvaf-r break_demo.va    -o break_demo.osdi
../OpenVAF-master-20260610/target/opt/openvaf-r continue_demo.va -o continue_demo.osdi
python3 verify_disable.py
```

Each device is the lower leg of a `1k`-over-`Rtot` divider driven by 1 V, so
`V(out) = Rtot/(Rtot+1k)` reports how many loop iterations contributed.

## Verified behaviour

```
break (disable a named block wrapping the loop -> loop breaks):
  STOP= 2 -> 2 iters  V(b)=0.66667  PASS
  STOP= 4 -> 4 iters  V(b)=0.80000  PASS
  STOP= 8 -> 8 iters  V(b)=0.88889  PASS
continue (disable the loop-body block -> skip iteration):
  8 iters, 4 add   V(b)=0.80000    PASS
```

`break` stops the loop at exactly `STOP` iterations (had it been a no-op the
loop would run to 1000); `continue` runs all 8 iterations but contributes on
only 4 — confirming the loop keeps going after each `disable`.
