# floatnode_examples — Enhancement-569: a node a device only reads is held and named

`verify_floatnode.py` pins, under **both** linear solvers, that a node touched only
by something that *reads* it — a B-source expression `v=2*v(x)`, an XSPICE input
port — gets the same treatment Enhancement-566 gave a node nothing conducts to: a
zero diagonal so gmin can hold it, and the warning "node 'x' is connected to
nothing that conducts; it is held only by gmin".

Before, E-566 judged a node by its matrix **column**. A read-only node has a column
entry (the reader's derivative) and an empty **row** (no equation), so it passed as
connected and the operating point failed on both solvers after 374 iterations,
Sparse blaming `x` and KLU the reader's branch. A node is now floating when its
row *or* its column is empty.

Run it:

```
python3 verify_floatnode.py
```

A compiled Verilog-A module has the same shape: `va_vcvs.va` (`V(out) <+ gain*V(in)`,
compiled by the suite) only probes its `in` port, and with `in` on an untouched node
it failed the same way; it now converges, named, on both solvers. A BSIM4 (OSDI) with
an open gate is pinned too: it goes through the ladder to optran, both solvers agreeing.

Beside the two read-only cases it keeps E-566's empty-column cases (a current
source's only load, a CCCS output), three ordinary shapes that must not warn (a
node both read and driven, a node held by a voltage source, a node between two
inductors), the open-gate and refused-E-control cases that are unchanged, and the
`.option rshunt` workaround for comparison.
