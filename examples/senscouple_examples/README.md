# senscouple_examples — Enhancement-870

[E-870](../../enhancements_doc/Enhancement-870.md): F4 of the
[Sparse and KLU correctness campaign of 2026-10-11](../../docs/bug_hunts/2026-10-11_sparse-klu-correctness-campaign.md).

A K element's mutual inductance is M = k√(L1L2), and it belongs to a device of its own. When
`sens … ac` perturbed an inductance it re-evaluated only the inductor, so the sensitivity to a
coupled L1 held M at its nominal value. The deck names k, and `alter l1` moves M with L1. On a
transformer `sens` gave 2528 − 977j and `alter` 5087 + 9448j. The couplings are now set up,
recomputed and loaded together with the inductor they couple.

The reference is the exact complex MNA of the deck (numpy), differentiated by a central
difference with Richardson extrapolation.

The checks:
- **[1]** d v(3)/d l1, the coupled primary, to 1e-6 of the exact value.
- **[2]** d v(3)/d l2, the coupled secondary, to 1e-6.
- **[3]** `sens` d/dl1 agrees with a central difference of two `alter`ed ac runs, to 1e-5.
- **[4]** (control) d/dk1, right before, to 1e-6.
- **[5]** (control) An uncoupled l3 and a resistor r1, right before, to 1e-6.

Run: `python3 verify_senscouple.py` (5 checks per solver; needs numpy). On the E-869 binaries
[1], [2] and [3] fail under both solvers.
