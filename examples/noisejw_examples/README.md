# noisejw_examples — correct + node-free noise factors (Enhancement-54)

Demonstrates **Enhancement-54**: two silent-noise-loss defect fixes plus the
elimination of the extra internal unknown that op-dependent noise factors and
`ddt(noise)` used to cost, using the committed `openvaf-r` and
`ngspice-46`.

## What was broken

- **Implicit-equation noise was silently dropped** — `build_implicit_equation`
  never called `add_noise`, so any source on the extra-unknown Equation path
  (op-dependent factors, `ddt(noise)`, correlation networks) never reached
  the OSDI descriptor: the simulator reported **no noise at all** for it.
- **The late-created react optbarrier was unregistered** — when the topology
  pass moves a `ddt()` into the reactive dimension it creates/rewrites the
  react optbarrier without registering it in the contribution map, so
  `prune_small_signal` dropped the noise wave's coupling twin: a hole in the
  Jacobian, zero transferred noise (PSP103's `react_small_signal` couplings
  were affected).
- **Extra internal unknowns** — `gm * white_noise(...)` and
  `ddt(cc * white_noise(...))` each synthesized an internal node. Now both
  stay linear: an op-dependent factor is just a per-instance value evaluated
  at the operating point, and one `ddt()` becomes the **j·ω component of a
  complex factor** (`fac = re + jω·im`). `load_noise()` fills
  `[flat, react]` signed power pairs per source (**OSDI 0.7**, stride 2) and
  ngspice's grouping sums complex amplitudes `(a + jω·b)·T` — exact for
  single sources and for coherent same-named groups (LRM 4.6.4), including
  anti-phase cancellation. This retires the old
  "TODO: complex noise power" in `lineralize.rs`, and makes the manual
  internal-node workaround real models use for induced gate noise (e.g.
  HiSIM2's `I(n) <+ V(n) + white_noise(...)` network) unnecessary.

## Run

```
python3 verify_noisejw.py
```

Checks (18, ALL PASS, exact vs closed-form analytics; the surrounding
resistors' own noise floor is measured with noiseless twin modules): plain
thermal control; `gm*white_noise` node-free + exact; `ddt(cc*white_noise)`
node-free + exact ω²-shaped spectrum; `ddt(k*flicker_noise)` composes
ω²·kf/f^ef; same-named flat+ddt parts sum coherently (x² + ω²τ²);
anti-phase pairs cancel to exactly the measured floor; one wave into two
branches (the formerly-lost correlation network) sums coherently across
branches; and `m=4` scales the jω case exactly.
