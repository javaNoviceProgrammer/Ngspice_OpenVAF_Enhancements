# Enhancement-747: the native `nport` device has a pole-zero load — a `pz` analysis through an imported block finds the block's poles and zeros instead of giving up with "pz simulation(s) aborted"

**Scope:** F7 of the
[Touchstone-import hunt](../docs/bug_hunts/2026-09-26_touchstone-import.md).
`src/spicelib/devices/nport/nportpzld.c` (new: `NPORTpzLoad`),
`nportinit.c` (the table entry), `nportext.h`, `Makefile.am` (and the
regenerated `Makefile.in`), `examples/nport_native_examples/` (three checks).
**ngspice only.** The AC, DC and transient loads, the fit and both
`pre_snp` backends are untouched.

**Suites:** [`nport_native_examples`](../examples/nport_native_examples/) 12
of 12 per solver, both solvers (9 of 12 on the E-746 binary); `klupz`,
`pzeig`, `pzklu`, `pzhb`, `crashfix2`, `presnp` unchanged; full sweep
532 of 532.

## What was wrong

E-242's device table set `DEVpzSetup` (its ordinary setup) but left
`DEVpzLoad` NULL. The pole-zero analysis loads every device that has a pz
load and no other, so the matrix it searched never held the block: the
output node hung on whatever else touched it, and on the hunt's RC two-port
driven at one port with a 1 GΩ load on the other the run said

```
pz simulation(s) aborted
```

and nothing else. The OSDI route through the same file worked (its compiled
model carries a pz load), finding the RC pole at −1.00001e7 rad/s plus the
fit's own far pole–zero pair.

## What changed

`NPORTpzLoad` is the AC load with the analysis's complex frequency in place
of jω. `NPORTadmittance` already evaluates `Y_ij(s) = d + s·e + Σ res/(s −
p)` at any complex `s`, so the pz stamp is the same four-corner admittance
stamp — `(i, j)`, `(i, ref)`, `(ref, j)`, `(ref, ref)` — into the real and
imaginary slots the analysis reads, the `(ptr, ptr+1)` convention of the
built-in RLC pz loads. Under KLU the complex binding the device already has
for AC serves the pz analysis too.

## Verification

Three checks in `verify_nport_native.py`, no compiler, both solvers, each
against a closed form:

| network | expected | found |
|---|---|---|
| the RC one-port (Y = 1e-3 + s·1e-9) behind 1 kΩ | one pole at −(1/R + G)/C = −2e6 rad/s, no zero; the built-in R‖C twin the same | both at −2000000 |
| the RLC one-port (a conjugate pole pair in the fit) behind 1 kΩ | poles at the roots of s² + (R + 1k)/L·s + 1/LC; no zeros reported (below) | poles to 1e-6 |
| the Pi two-port (off-diagonal coupling), g to p2 through 1 kΩ and 4 kΩ | two poles at the roots of det(Y(s) + diag(Gs, Gl)), no zero | to 1e-6 |

No run says *aborted*. On the E-746 binary the three fail, the analysis
giving up as before. The hunt's own probe now reports the RC pole at
−1.00001e7 rad/s through the native block, the OSDI route's number. The pz
suites (`klupz`, `pzeig`, `pzklu`, `pzhb`), `crashfix2` and `presnp` are
unchanged.

## What this does not do

* **Zeros at the fit's poles are not reported.** A transfer zero that sits
  where the block's admittance goes to infinity — the RLC one-port's
  resonance shorting its node — is a pole of the stamped `Y(s)`, not a root
  of a determinant, and the pole-zero search finds roots. A direct admittance
  stamp has no internal states to turn `res/(s − p)` into a polynomial row,
  so such zeros are absent from the native device's answer; the OSDI route,
  whose `laplace_nd` states do exactly that, reports them beside a
  cancelling pole pair. The poles of the transfer are exact either way. The
  suite pins the RLC one-port's poles and its empty zero list.
* A rational fit brings its own far poles; a `pz` through an imported block
  reports them along with the physical ones. The fit's error (E-745) bounds
  how close the physical ones are.
* The device still has no noise, distortion or sensitivity load (the hunt's
  F9 covers noise).
* The bare *pz simulation(s) aborted* for any other device without a pz
  load, or for a singular pz matrix, is not made more informative here.
