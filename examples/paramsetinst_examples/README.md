# paramsetinst_examples — Enhancement-644

A paramset's own parameters are instance parameters, and an instance selects
its member (IHP hunt C1); a bound parameter's case-twin and a model's own `i`
no longer draw the collision warning (C2). A paramset's own parameters were
model-card-only, so `n1 a b rsil l=0.5u w=0.5u mm_ok=0` — what every SPICE
device library writes — was refused; in the LRM's world they are what an
instance of the paramset sets, so they are instance parameters now (the card
gives the instances' defaults; `(* type="model" *)` keeps one on the card),
and LRM 6.4.2's per-instance selection follows: the first `n` line binds the
card to its member, an instance needing another member gets a clone of the
card, `<card>.<member>`, made once and shared.

Run: `python3 verify_paramsetinst.py` (14 checks per solver, both solvers; 7
fail on the E-643 binaries).
