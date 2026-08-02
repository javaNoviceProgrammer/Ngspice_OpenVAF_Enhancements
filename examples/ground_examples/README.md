# `ground` net-type example (version10, Enhancement-9)

Demonstrates the Verilog-A **`ground`** net declaration, and the Enhancement-9
parser fix that makes all four natural declaration orderings work.

## Background

`ground` declares a node as the **global reference** (V = 0); OpenVAF collapses
such a node into the circuit's ground node. It was already supported, but the
parser only accepted the net-type *before* the discipline (`ground electrical
gnd;`); the equally-valid discipline-first form (`electrical ground gnd;`) failed
with `unexpected token NET_TYPE; expected identifier`. Enhancement-9 fixes the
net-declaration parser to accept an optional net-type after the discipline
(mirroring how `port_decl` already behaved), so all four orderings parse to an
identical device:

```verilog
ground electrical gnd;        // net-type first
electrical ground gnd;        // discipline first   (fixed in Enhancement-9)
electrical gnd; ground gnd;   // two-step
ground gnd; electrical gnd;   // two-step, reversed
```

(A `ground` net still requires a discipline — a bare `ground gnd;` remains an
error, `no discipline for net 'gnd'`, which is correct.)

## The model

`rgnd.va` is a one-terminal resistor from terminal `a` to an internal `ground`
node — i.e. a resistor to ground.

## Running

```sh
../OpenVAF-master-20260610/target/opt/openvaf-r rgnd.va -o rgnd.osdi
python3 verify_ground.py
```

`verify_ground.py` compiles the model in each of the four declaration orderings
and places it as the lower leg of a `1k`-over-`R` divider driven by 1 V, checking
`V(out) = R/(R+1k)` — which only holds if `gnd` is correctly collapsed to the
0 V global reference.

## Verified behaviour

```
  ground electrical gnd;         a=1.0  b=0.6666667  PASS
  electrical ground gnd;         a=1.0  b=0.6666667  PASS
  electrical gnd; ground gnd;    a=1.0  b=0.6666667  PASS
  ground gnd; electrical gnd;    a=1.0  b=0.6666667  PASS
```

All four orderings produce the same device, and the internal `ground` node
correctly acts as the V = 0 reference (`V(b) = 2000/3000 = 0.6667`).
