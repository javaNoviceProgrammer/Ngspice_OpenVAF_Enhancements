# `.sp` S-parameter port-count scalability (Enhancement-202)

ngspice's RFSPICE `.sp` analysis builds the port S-matrix at every frequency by
inverting `N x N` complex matrices (`CKTspCalcSMatrix`, for the S, Y and Z matrices).
That inverse used to be computed by the **adjugate / determinant** method (Cramer's
rule), and the determinant (`cdet`) is a **recursive cofactor expansion — O(N!)**.
The adjugate does `N²` of those, so each inverse was `O(N·N!)` and the whole `.sp`
cost blew up by roughly a factor of **N per added port**:

| ports | old `.sp` time | new `.sp` time |
|------:|---------------:|---------------:|
| 8     | ~13 s          | 0.3 s          |
| 10    | ~18 min        | 0.02 s         |
| 12    | minutes        | 0.02 s         |
| 32    | (infeasible)   | 0.1 s          |

Replacing the inverse with **Gauss-Jordan elimination with partial pivoting** makes it
`O(N³)`, so extraction is essentially instant for any realistic port count. The same
inverse is used by the periodic S-parameter path (`.psp` / PSS), which speeds up too.

## Verification

`verify_spscale.py` — a **12-port** R-L-C ladder (port → 30 Ω → node with 150 Ω ‖ 2 pF
shunt, adjacent nodes coupled by 8 nH) is run through `.sp` + `wrsnp`. Two checks: the
extraction **completes in a fraction of a second** (it took minutes at this port count
before), and **every entry** of the extracted 12×12 S-matrix matches the closed-form
network across the sweep (max abs error ~2×10⁻⁷) — so the fast inverse is exact, not
just fast.

## Running

```sh
python3 verify_spscale.py
```
