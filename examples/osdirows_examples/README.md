# osdirows_examples — Enhancements 836 to 838

F1 of the
[2026-10-10 robustness and correctness campaign](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md):
14 of the corpus's 92 compact models no longer reached an operating point. This suite covers
the three things behind it.

- **[1] [E-836](../../enhancements_doc/Enhancement-836.md).** An OSDI instance's internal rows
  carry the name, the kind (voltage or current) and the nodeset of the node they stand for.
  With `r1 = 0`, `rth.va` collapses `a1` into `p`. Before the fix:
  - the midpoint row was named `n1#a1` and held `a2`'s 0.5 V;
  - the 0 V branch of terminal `t` was a voltage node named `n1#a2`.

  Now the vectors are `n1#a2` = 0.5 V and the current `n1#flow(t)`, and `save v(n1#a1)` names
  `p`. With no collapse, `a1` and `a2` read 2/3 and 1/3 (control).
- **[2] [E-837](../../enhancements_doc/Enhancement-837.md).** `rth.va` ties terminal `t` to
  ground itself (`V(t) <+ 0`, the shape of a self-heating model with the heating off).
  - Two or three instances on one thermal net converge: the duplicate shorts are dropped, and
    one branch carries the net's current.
  - `sens`, a `dc` sweep and an `ac` keep the decision.
  - A 0 V source on the net is still refused, but the warning now names the source and the
    terminal.
  - `t` on ground is the control.
- **[3] [E-838](../../enhancements_doc/Enhancement-838.md).** `dead.va` writes its internal node
  `x` only when `mode = 1`, so with `mode = 0` its row holds no value.
  - It is named and held with 1e-12 S, and the `op` takes 3 iterations; every homotopy used to
    fail.
  - `ac` and `tran` run.
  - `dcpath=warn` and `dcpath=error` name it without a hold; `dcpath=off` stays silent.
  - `mode = 1` and `gshunt` are controls.

Run: `python3 verify_osdirows.py` (20 checks per solver, two of them the compiles; 13 fail on the
E-835 binaries).
