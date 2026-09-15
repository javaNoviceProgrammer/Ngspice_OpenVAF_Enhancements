# busorder_examples — Enhancement-637

A bus actual on an instance port connects positionally, in its declared or
written order, whichever way either side is declared. A whole bus `.a(p)` and
a part-select `.a(p[3:0])` were laid onto the port by index value (ascending
onto ascending) while a concatenation `.a({p})` connected positionally, so
`.a(p)` and `.a({p})` differed when the declarations ran opposite ways, and
the reversed part-select `p[3:0]` of a `[0:3]` bus silently meant `p[0:3]`
while `{p[3],p[2],p[1],p[0]}` reversed. Now every form puts the actual's
leftmost bit on the port's msb.

The child puts (k+1) mA per volt on its bit `a[k]`; the current at each parent
bit says which child bit it reached. Same-direction connections are
unchanged; E-85's own routing (`v[3:2]`, `.i(v[1:0])`) holds.

Run: `python3 verify_busorder.py` (8 checks per solver, both solvers).
