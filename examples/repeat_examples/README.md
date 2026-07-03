# `repeat` loop example (version10, Enhancement-9)

Demonstrates the Verilog-AMS **`repeat (count) statement`** loop, added to
OpenVAF in Enhancement-9 (it was previously unsupported — `repeat` was not a
recognized keyword).

## Semantics

`repeat (count) statement` evaluates `count` **once**, converts it to an integer
using the standard Verilog-AMS real→integer rule (**round to nearest**, half
away from zero), and executes `statement` that many times (0 times if the count
is ≤ 0).

## The model

`repeat_demo.va` uses a `repeat` loop to sum `count` copies of `Rbase` into a
series resistance `Rtot = round(count) * Rbase`, and presents that resistance
between its terminals.

## Running

```sh
../OpenVAF-master/target/release/openvaf-r repeat_demo.va -o repeat_demo.osdi
python3 verify_repeat.py
```

`verify_repeat.py` places the device as the lower leg of a `1k`-over-`Rtot`
divider driven by 1 V, so `V(out) = Rtot/(Rtot+1k)` directly reports how many
times the loop body ran.

## Verified behaviour

```
  count=0     -> round= 0 iters  V(b)=1.00000  PASS   (0 iterations, open)
  count=1     -> round= 1 iters  V(b)=0.50000  PASS
  count=2     -> round= 2 iters  V(b)=0.66667  PASS
  count=4     -> round= 4 iters  V(b)=0.80000  PASS
  count=3.4   -> round= 3 iters  V(b)=0.75000  PASS   (round down)
  count=3.6   -> round= 4 iters  V(b)=0.80000  PASS   (round up)
  count=2.5   -> round= 3 iters  V(b)=0.75000  PASS   (half away from zero)
  count=10    -> round=10 iters  V(b)=0.90909  PASS
```

Integer counts run exactly, real counts round to nearest (LRM-conformant), the
zero-count case runs the body zero times, and nested `repeat` loops multiply
(`repeat(P) repeat(Q)` runs the innermost body `P*Q` times — also verified).
