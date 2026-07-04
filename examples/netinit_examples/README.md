# netinit_examples — net initialization + net attribute access (Enhancement-45)

Demonstrates **net nodeset initializers** (`electrical a = 5.0;`, LRM 3.6.3.2)
and **net/branch attribute access** (`net.potential.abstol`, LRM 5.5.3) —
using the committed `openvaf-r` and `ngspice-46`.

## What was broken

- `electrical m = 1.5;` was a parse error. Per the LRM the constant initializer
  is a **nodeset value** for the net's potential — an initial-guess hint that
  steers Newton-Raphson toward an operating point without constraining the
  converged solution.
- `a.potential.abstol` (and every other attribute-access spelling, including
  the branch form the machinery nominally supported) failed with "expected a
  scope but found node 'a'" — the module-body path resolver rejected non-scope
  qualifiers before the attribute arms could run.

E-45 implements both. The nodeset travels net declaration → OSDI node
descriptor (new `nodeset` field, NAN = none) → ngspice, which applies it as a
`.nodeset`-equivalent at instance setup for internal nodes and connected
terminals (an explicit netlist `.nodeset` wins). Because the `OsdiNode` array
stride changed, the **OSDI minor version is bumped to 0.5**: older `.osdi`
files are rejected with a clear "recompile with the matching openvaf-r"
message instead of being misread. Attribute access resolves net → discipline →
nature → attribute through Enhancement-39's inheritance-aware lookup and folds
to a constant; the LRM's `twocap` idiom (`ddt(V(a,b), a.potential.abstol)`)
compiles as written.

## Run

```
python3 verify_netinit.py
```

Checks (ALL PASS): a bistable `x = tanh(5x)` node (solutions 0, ±0.999909)
converges to 0 with no initializer, to +sol/−sol with `= 1.0`/`= -1.0` on the
internal net; a **port** initializer nodesets the connected terminal and an
explicit netlist `.nodeset` overrides it; a bus `'{0.5,-1.0,2.0}` initializer
applies per bit (weighted sum 90.99); an initializer inside a **flattened
submodule** instance survives elaboration; attribute access reads exactly
(1e6·`q.potential.abstol` + 1e12·`q.flow.abstol` + 1e6·`br.potential.abstol`
= 3.0); non-constant initializers and unknown attributes are clean named
diagnostics.
