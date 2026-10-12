# dynstable_examples — Enhancement-873

[E-873](../../enhancements_doc/Enhancement-873.md): F1 of the
[transient stress campaign of 2026-10-12](../../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

`dynorder` chooses the Gear or Adams order whose truncation estimate allows the largest step. The
estimate multiplied error constants meant for the derivative q⁽ᵏ⁺¹⁾ by the divided difference,
which is q⁽ᵏ⁺¹⁾/(k+1)!. SPICE's trtol of 7 makes up the 3! of order 2; at order k ≥ 3 the estimate
was still (k+1)!/3! too small. `dynorder` took the high orders for 20 to 840 times cheaper than
they were. On a nine-element RLC network that peaks at 0.919 V it reached 2.5e7 V at `maxord=4`
and 9e22 V at `maxord=6`, with status 0 and nothing said. The constant is now scaled by (k+1)!/3!
at orders 3 to 6; orders 1 and 2 are as SPICE has them.

The checks, on that network against a `reltol=1e-7` trap run:
- **[1]** `gear maxord=4`, `5` and `6` with `dynorder` agree in peak and end value.
- **[2]** `adams maxord=3` and `4` with `dynorder` agree.
- **[3]** `errpreset=conservative` with `gear maxord=4 dynorder`, and `gear maxord=6 dynorder` at
  `reltol=1e-5`, agree.
- **[4]** (control) `dynorder` still climbs to order 4 on a smooth LC, in fewer steps than the
  stock controller.
- **[5]** (control) An RC discharge under `gear maxord=4 dynorder` lands within 0.1 % of exp(−8).

Run: `python3 verify_dynstable.py` (5 checks per solver). On the E-872 binaries [1] to [3] fail
under both solvers.
