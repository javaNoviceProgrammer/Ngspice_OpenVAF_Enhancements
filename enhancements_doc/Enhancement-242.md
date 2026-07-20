# Enhancement-242 — native C n-port device + `pre_snp -native`

A built-in ngspice device that realizes an arbitrary-port linear block **directly**
from a pole/residue (vector-fitted) Y-parameter model, stamped into the sparse
matrix for DC, AC, **and** transient — with **no Verilog-A / OpenVAF compile step**.
It removes the compiler wall that limits the existing `pre_snp` (Touchstone → VA →
OSDI) route at high port counts.

## Background — the compiler wall

`pre_snp` (E-200/201/205) converts a Touchstone `.sNp` file to a Verilog-A n-port
via a shared-pole vector fit, then invokes `openvaf-r` to compile it to `.osdi`.
That works well up to `~24–32` ports, at which point the emitted Verilog-A —
`O(N·Np)` `laplace_nd` filter sections, or `O(N²)` terms for a full-rank residue
coupling — hits the OpenVAF compile time/size wall. The fit is cheap; the
**compile** is the bottleneck.

## The model

The device evaluates the same rational model the vector fit produces:

```
Y_ij(s) = d_ij + s·e_ij + sum_k  res_ijk / (s - p_k)          (shared poles)
```

Port current leaving node *i* is `I_i = sum_j Y_ij(s)·(V_j − V_ref)`, stamped as a
**multi-terminal admittance** (a four-corner conductance per `(i,j)`; no per-port
branch-current unknowns), so an N-port adds `N` equations, not `2N`. This is what
lets it scale to hundreds of ports.

* **DC / .op / .dc** — the static conductance `Y(0)`.
* **AC** — the complex `Y(jω)` into the `(real, imag)` matrix slots.
* **Transient** — a trapezoidal companion: `d` is a conductance, `s·e` a capacitor
  `I = e·dU/dt`, and each `res/(s−p)` a first-order state `dx/dt = p·x + u` with
  `I += res·x`. The shared pole states `x_jk` (one per input `j`, pole `k`) are
  advanced once per load and parked in `CKTstate0`; the stamp phase recovers the
  history `B = x_{n+1} − a·u_j` from that parked value, so no per-instance scratch
  is needed even at large N. Complex poles arrive as conjugate pairs, so the summed
  current is real by construction.

The device rides the generic `N` dispatcher (`inp2n.c`, broadened from OSDI-only to
also accept the `nport` device), driven by a compact `.nport` fit file:

```
N1  p1 p2 ... pN  ref   mymodel
.model mymodel nport(file="mymodel.nport")
```

`ref` is an **explicit** reference terminal (connect it to `0` for a
ground-referenced Touchstone model) — the more general form, so floating /
differential blocks are expressible too.

> **Update (E-243):** `pre_snp -osdi` was originally emitted with `N` terminals and
> an implicit ground reference, so the two backends took *different* instance lines.
> [Enhancement-243](Enhancement-243.md) gives the `-osdi` Verilog-A the same explicit
> `ref` terminal, so the instance line — `N1 p1 … pN ref model` — is now **identical**
> for both `-osdi` and `-native`.

KLU is supported: `nportbindCSC.c` binds each stamped element to its CSC slot
(real, complex, and complex→real), so the device runs identically under both the
default Sparse 1.3 and `.option klu`.

## `pre_snp -native`

`pre_snp` gained a backend flag; `snp2va.c` was refactored so the shared
parse + vector-fit lives in one `snp_fit()`, feeding two emitters:

* `pre_snp -osdi  <file.sNp>` — *(default)* the existing Touchstone → Verilog-A →
  `openvaf-r` → `<file>.osdi` route.
* `pre_snp -native <file.sNp>` — the **same fit**, written as `<file>.nport` for
  this device. No compiler, no `.osdi`.

## Verification

Every check compares the device against a closed-form oracle (no `openvaf-r`
needed), under **both** linear solvers:

* **Correctness** (`examples/nport_native_examples/verify_nport_native.py`, 6
  checks × 2 solvers): an RC one-port `e`-term matches AC `1/Y` and the transient
  exponential; an RLC one-port exercises a complex conjugate pole pair through
  resonance; a Pi two-port checks off-diagonal `d`/`e` cross-coupling vs an
  analytic MNA solve; `pre_snp -native` fits a known 2-port `.s2p` and reproduces
  its Y; and a 20-port, 6-pole, full-rank model matches an analytic linear solve.
* **`-native` ≡ `-osdi`**: on `examples/sp/137mhz_bpf.s2p` (4 poles), the native
  device reproduces the VA→OSDI backend to **1e-11** across a 400-point AC sweep,
  and to ~1e-5 in transient (the residual is the trapezoidal companion vs
  `laplace_nd`, not an error).
* **Scaling**: a 100-port block (6 poles) solves an AC point in **~90 ms** with a
  4.85e-10 match to the analytic solve; `pre_snp -native` writes its `.nport` in
  well under a second where `pre_snp -osdi` needs a multi-second-and-growing
  `openvaf-r` compile (`~74×` at 8 ports, heading to the wall by ~20). KLU and
  Sparse agree bit-for-bit.

## Scope

ngspice only, additive. New device directory `src/spicelib/devices/nport/`
(registered in `dev.c`, wired through `configure.ac` / the device `Makefile.am`s);
`inp2n.c` broadened to dispatch the `nport` model; `snp2va.c` refactored into a
shared `snp_fit()` with a new `.nport` emitter, and `com_presnp.c` gained the
`-osdi` / `-native` flags (default `-osdi`, so existing decks are unchanged). No
solver, analysis, or compiler change; no existing behavior altered. Full
regression: 200/200.
