# Native n-port device + `pre_snp -native` (Enhancement-242)

A built-in ngspice device that realizes an arbitrary-port linear block **directly**
from a pole/residue (vector-fitted) Y-parameter model — stamped into the sparse
matrix for DC, AC, **and** transient — and, since E-747, pole-zero — with **no
Verilog-A / OpenVAF compile step**:

```
Y_ij(s) = d_ij + s*e_ij + sum_k  res_ijk / (s - p_k)        (shared poles)
```

It rides the generic `N` dispatcher, driven by a compact `.nport` fit file:

```
N1  p1 p2 ... pN  ref   mymodel
.model mymodel nport(file="mymodel.nport")
```

Port nodes are `p1..pN`; `ref` is an explicit reference terminal (connect it to `0`
for a ground-referenced Touchstone model — the extra terminal makes floating /
differential blocks expressible too).

## `pre_snp -native`

`pre_snp` gained a backend flag:

- `pre_snp -osdi  <file.sNp>` — *(default)* Touchstone → Verilog-A → `openvaf-r` →
  `<file>.osdi`, loaded with `pre_osdi`.
- `pre_snp -native <file.sNp>` — Touchstone → `<file>.nport` for this device. Same
  vector fit, **no compiler**, so it scales past the `~24–32`-port OpenVAF compile
  wall that limits the VA→OSDI route. The device stamp itself is a multi-terminal
  admittance (no per-port branch unknowns), so it scales to hundreds of ports —
  a 100-port block solves in tens of milliseconds.

As of E-243 the `-osdi` Verilog-A carries the same explicit `ref` terminal, so the
instance line `N1 p1 … pN ref model` is **identical** for both backends.

The pole companion for transient is trapezoidal: `d` is a conductance, `s*e` a
capacitor, and each `res/(s−p)` a first-order state `dx/dt = p·x + u` (complex
poles handled as conjugate pairs, so the summed current is real).

## What `verify_nport_native.py` checks

Every check is against a **closed-form oracle** (no `openvaf-r` needed), under
**both** linear solvers (KLU + Sparse 1.3):

1. **RC one-port** — the `e`-term (capacitor): AC `V = 1/Y`, and the transient
   `0.5·(1−e^{−t/τ})` exponential.
2. **RLC one-port** — a complex conjugate pole pair, AC through resonance.
3. **Pi two-port** — off-diagonal `d`/`e` cross-coupling vs an analytic MNA solve.
4. **`pre_snp -native`** — fit a known 2-port `.s2p`, reload the emitted `.nport`,
   and reproduce the known Y-matrix.
5. **Scaling (N=20)** — a 6-pole, full-rank model: the full N-port stamp vs an
   analytic linear solve.

Run it directly:

```
python3 verify_nport_native.py
```

## Enhancement-746 — no terminal flood

The device declares 512 terminals as a maximum, and E-481's unconnected-terminal
warning compared an instance line's node count with that number: every
`N1 p1 p2 0 mm` listed terminals 4 to 512 as absent (510 lines on the RC deck
above), and `.option silentports=ground` bound the phantoms to node 0. The
device now carries `DEV_VARTERMS`, the dispatcher names and grounds nothing
above the line's count, and a line that is really short gets the device's own
message with both counts. Three checks pin it: the RC line silent with its point
unchanged, the short line's message, and `silentports=ground` leaving the point
unchanged. 9 checks per solver.

## Enhancement-747 — pole-zero analysis

The device had a pz setup but no pz load, so a `pz` on a circuit with a
native n-port never held the block and gave up with "pz simulation(s)
aborted" and nothing else. `NPORTpzLoad` is the AC stamp with the analysis's
complex `s` in place of jω. Three closed-form checks: the RC one-port's pole
at −2e6 rad/s (the built-in R‖C twin agrees), the RLC one-port's transfer
poles at the roots of its quadratic (its zeros, at the fit's own poles, are
not reported: see below), and the Pi two-port's two poles at the roots of det(Y(s) + diag(Gs, Gl)).
The RLC check also pins a limit: its transfer zeros sit at the fit's own
poles, which are poles of the stamped admittance rather than roots of a
determinant, so a direct admittance stamp cannot report them (the OSDI route,
with internal states, does). 12 checks per solver.
