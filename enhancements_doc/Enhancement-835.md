# Enhancement-835: in `ac` and `sp` an OSDI device's terminal currents are its small-signal currents, not the bias current

**Scope:** F19 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).

ngspice:
- `osdi/osdiparam.c`: `OSDIask` answers a terminal current in an `ac` or `sp` analysis from the
  Jacobian and the complex solution (`osdi_ask_ac_current`).
- `include/ngspice/osdiitf.h`: `osdi_ask_complex`.
- `frontend/outitf.c`:
  - `getSpecial` records such an answer as complex;
  - `.options savecurrents` keeps an OSDI device's currents in `ac` and `sp`, revising
    Enhancement-808.

`examples/seedac_examples/` (section [4], seven checks); `osdislips_examples` [14] follows the
change. **ngspice only.**

**Suites:**
- [`seedac_examples`](../examples/seedac_examples/): 20 of 20 per solver. 5 of the 7 checks in
  [4] fail on the E-831 binaries; the other two are `@n1[i_b]` = −`@n1[i_a]`, which the bias
  also satisfied, and the `op` control.
- [`osdislips_examples`](../examples/osdislips_examples/): 93 of 93, with its [14] updated.
- The full sweep: 547 of 547.

## What was wrong

```spice
v1 1 0 dc 2 ac 1
n1 1 0 rr2m        ; r1 = r2 = 1k, c = 1n from the internal node
r9 1 0 1k
.save @n1[i_a]
ac lin 3 1k 1meg
```

| f | `@n1[i_a]` | true small-signal current (`-i(v1)` − 1 mA) |
|---|---|---|
| 1 kHz | 1.000e-3 + 0j | 0.500e-3 + 0.0016e-3j |
| 500 kHz | 1.000e-3 + 0j | 0.856e-3 + 0.226e-3j |
| 1 MHz | 1.000e-3 + 0j | 0.954e-3 + 0.145e-3j |

The complex vectors `@n1[i_a]`, `@n1[i_b]` and `@n1[i]` held the DC operating-point current
(2 V / 2 kΩ) at every frequency, and with `dc 0` they were all zero. They looked like ac data
and were not. `sp` was the same (`@n1[i_a]` = 0.9756 mA flat).

Enhancement-394's read of a terminal current sums the resistive residual the device left in
the instance. In an `ac` analysis that residual is the bias point's. Enhancement-808 had
already kept `.options savecurrents` from putting these vectors into every ac plot. An
explicit `.save` still recorded them, and its write-up named this as F19, open.

## The change

**The answer.** In an `ac` or `sp` analysis (`DOING_AC`), the solution holds the complex
small-signal response, and the ac load stamps the Jacobian the bias point left in the
instance, G + jωC. The small-signal current into terminal *t* is computed from them:

> Σ over the Jacobian entries whose row is in *t*'s collapse group: (G + jωC) · (v<sub>r</sub> + j v<sub>i</sub>) of the entry's column node

plus what an active `ac_stim()` source of the device injects at those nodes, by the rule the
ac load applies. That is exactly what the ac load puts into the group's KCL row. The values
come from `write_jacobian_array_resist` and `write_jacobian_array_react`, which read the same
stored entries the loads do, so `m` is included. Their index is a running count of the entries
with a resistive (or reactive) part, as in Enhancement-359's numeric distortion.

**The output.** The parameter is declared real, so `outitf.c` cannot learn the type from it.
`OSDIask` raises `osdi_ask_complex` when it answers this way, and `getSpecial` records such an
answer as complex in a complex plot.

**`.options savecurrents`.** In `ac` and `sp` it now keeps an OSDI device's currents, which
are right. It still leaves out a built-in device's, which answers no current there, with
Enhancement-808's note in new words:

```
Note: .options savecurrents saves device currents in op, dc and tran analyses; this AC analysis leaves its 1 out (they would hold nothing: a built-in device answers no current there). For a small-signal current, use `.probe i(<device>)`.
```

`noise` is unchanged: its currents are the bias, left out as before. `op`, `dc` and `tran` are
unchanged.

## The checks

`seedac_examples` [4], the module above:
- `ac`: `@n1[i_a]` + `i(v1)` + `v(1)`/1k = 0 at every frequency, to 1e-12; non-zero imaginary
  part (was the 1 mA bias).
- `@n1[i_b]` = −`@n1[i_a]`, and the bare `@n1[i]` is `@n1[i_a]`.
- `m=2`: the current doubles, and KCL holds.
- An `ac_stim("ac", 1m)` source in the device: 1 mA into a node held at 0 V (= −`i(v1)`), and
  KCL against a 1k resistor.
- `.options savecurrents` in `ac`: the OSDI device's vectors kept and right; `@r9[i]` left out,
  with the note.
- `sp`: `@n1[i_a]` + `v1#branch` = 0, the device being all the port drives (was the 0.98 mA
  bias).
- `op` (control): the 1 mA bias.

`osdislips_examples` [14] (E-808): ac keeps the OSDI device's three vectors and leaves out the
built-in three, with the note's new words.

## Limits

- A built-in device still answers no current in `ac` (`E_ASKCURRENT`). `.probe i(<device>)` is
  the way to get one.
- `print @n1[i_a]` of a vector that was not saved reads the device after the analysis, which
  answers the bias current, as a built-in device does.
- In a `noise` analysis an OSDI device's current is the bias, as a built-in device's is.
