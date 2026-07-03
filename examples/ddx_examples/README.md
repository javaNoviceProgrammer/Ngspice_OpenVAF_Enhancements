# ddx_examples — DC / AC / transient demonstration of `ddx()`

Demonstrates the Verilog-AMS `ddx()` symbolic-derivative operator across all
three analysis types, using **version11's own** `openvaf-r` and `ngspice-46`.

`ddx_demo.va` is a nonlinear resistor `id = Gbase*V + Isat*tanh(V/Vo)` in
parallel with a capacitor `Cpar`. It uses `ddx()` to compute its own exact
small-signal conductance

```
g(V) = d(id)/dV = Gbase + (Isat/Vo)*(1 - tanh(V/Vo)^2)
```

and exports it (in mS) as the node voltage `V(g)`. The device is driven through
a series resistor `rs` so that `V(p,n)` is a genuine circuit unknown (a bare
ideal source would *fix* it, making the derivative w.r.t. a constant = 0).

## Files

| File | Purpose |
|---|---|
| `ddx_demo.va` | The nonlinear resistor that exports its `ddx`-computed conductance. |
| `plot_ddx.py` | Runs DC, AC and transient and writes the three PNGs. |
| `ddx_dc.png` / `ddx_tran.png` / `ddx_ac.png` | The plots (see below). |
| `_ddx.cir`, `*.txt` | Generated decks / `wrdata` output (artifacts). |

## Run

```
python3 plot_ddx.py
```

Expected:

```
DC   max |g_ddx - g_analytic| ~ 1e-3 mS
TRAN max |g_ddx - g_analytic| ~ 2e-3 mS
AC   sim vs analytic (from ddx g): match
```

## The plots

- **`ddx_dc.png`** — sweep the bias; the `ddx` conductance (markers) lands
  exactly on the closed-form `g(V)` (a bump: 2 mS at V=0, relaxing to the 1 mS
  floor `Gbase` as the tanh saturates). ddx = the exact derivative at every bias.
- **`ddx_tran.png`** — under a large-signal sine, the `ddx` conductance tracks
  `g(V(p,n)(t))` in time (it peaks each time `V(p,n)` crosses 0). ddx follows the
  moving operating point.
- **`ddx_ac.png`** — small-signal Bode of the nonlinear `R ∥ C` divider at three
  bias points. The low-frequency gain shifts because the DC conductance (= the
  `ddx` value shown in the legend: 2.00 / 1.78 / 1.17 mS) changes with bias;
  the analytic response computed *from* the `ddx` conductance (dashed) overlays
  the simulation (solid). ddx is exactly the conductance the AC linearisation
  uses.

## Notes

- `ddx(id, V(p,n))` uses the potential-difference form. OpenVAF fully supports
  it but flags it non-standard for portability; the module carries
  `(* openvaf_allow="non_standard_code" *)` to silence that lint.
- Every SPICE deck begins with a **title line** — SPICE treats the first line of
  a deck as the title/comment, so a component on line 1 (e.g. `vin ...`) would be
  silently dropped.
