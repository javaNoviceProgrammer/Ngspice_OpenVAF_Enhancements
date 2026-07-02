# `localparam` conformance example (version10, Enhancement-9)

Demonstrates the corrected **`localparam`** semantics added in Enhancement-9.

## Background

In the version10 baseline, `localparam` was parsed and worked as a constant,
but OpenVAF treated it **identically to `parameter`**: the `is_local` flag was
recorded and then never used, so a `localparam` was exposed to the simulator as
an externally-settable model/instance parameter and could be overridden from the
`.model` card — which the Verilog-AMS LRM forbids (a `localparam` is a local
constant that cannot be overridden).

Enhancement-9 makes `localparam` non-overridable: its resolved value is always
the declared default expression, regardless of any override the simulator
attempts. Crucially, a **derived** localparam (one whose default depends on a
real `parameter`, e.g. `localparam G = 1/R`) still recomputes correctly when the
underlying parameter is overridden.

## The model

`rdiv.va` is a linear conductance `GAIN*G = GAIN/R`:

```verilog
parameter  real R    = 1000.0 from (0:inf);   // overridable
localparam real G    = 1.0 / R;               // derived, NOT overridable
localparam real GAIN = 2.0;                   // literal,  NOT overridable
analog I(p, n) <+ GAIN * G * V(p, n);
```

## Running

```sh
../OpenVAF-master/target/release/openvaf-r rdiv.va -o rdiv.osdi
python3 verify_localparam.py
```

`verify_localparam.py` places the device as the lower leg of a `1k`-over-`rdiv`
voltage divider (V(out) = Rdev/(Rdev+1k), Rdev = R/GAIN) and checks V(out) for a
series of `.model` overrides against the LRM-correct expectation.

## Verified behaviour

```
  rdiv(                  ) V(out)=0.333333  expected=0.333333  PASS   defaults
  rdiv(R=2000            ) V(out)=0.500000  expected=0.500000  PASS   R overridable
  rdiv(R=500             ) V(out)=0.200000  expected=0.200000  PASS   R overridable
  rdiv(G=0.5             ) V(out)=0.333333  expected=0.333333  PASS   G override ignored
  rdiv(GAIN=10           ) V(out)=0.333333  expected=0.333333  PASS   GAIN override ignored
  rdiv(R=4000 G=9 GAIN=9 ) V(out)=0.666667  expected=0.666667  PASS   only R applies
```

- Overriding the `parameter R` takes effect, and the derived `localparam G=1/R`
  tracks it (e.g. `R=2000` → `V(out)=0.5`).
- Overriding either `localparam` (`G` or `GAIN`) is ignored — the declared /
  derived value is always used.
