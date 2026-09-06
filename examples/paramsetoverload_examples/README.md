# paramsetoverload_examples — paramset overloading, LRM 6.4.2 (Enhancement-565)

The last paramset gap of the
[coverage audit of *A Practical Guide to Verilog-A*](../../docs/audits/2026-09-05_practical-guide-verilog-a-coverage.md)
§3.3, closed on both routes and pinned through **the committed** `openvaf-r` and
`ngspice-46`, both solvers.

## What was missing

"Paramset identifiers need not be unique" (LRM 6.4.2): several paramsets may
share a name, and the simulator picks one for each instance by the clause's
rules — the chapter the book explains at length. A second `paramset nch …` was
*'nch' was already declared in this scope*, so the rules had nothing to act on.

## What the model shows

`nch_ps.va` is the LRM's own example: four paramsets named `nch` (default,
mismatch, short-channel, long-channel) over a conductance stand-in for `nmos3`
whose current and output variable `uu` reveal the member chosen.

| route | instance or card | selected | why |
|---|---|---|---|
| module | `nch #(.l(1u), .w(5u), .mm(1)) m1` | mismatch | the only member with `mm` |
| module | `nch #(.l(1u), .w(10u)) m3` | default | the mismatch member's `mm` default is outside `(0:1]`; the long-channel member has two un-overridden parameters |
| module | `nch #(.l(3u), .w(5u), .ad(1.2p), .as(1.3p)) m4` | long-channel | `l = 3u` is outside the short-channel `[0.25u:1u)` |
| `.model` | `nch mm=1` | `nch__2` | as m1 |
| `.model` | `nch l=1u w=10u` | `nch` | as m3 |
| `.model` | `nch l=3u w=5u ad=1.2p as=1.3p` | `nch__4` | as m4 |
| `.model` | `nch l=0.5u ad=1p` | `nch__3` | `ad` rules out the default member |
| `.model` | `nch__4` | `nch__4` | a member named directly is taken as written |
| `.model` | `nch zz=1`, `nch l=0.1u` | error | no member applies; each member's reason is listed |
| `refused/` | two identical members; a value outside every member's range | error | ambiguous; none applies |

The compiler emits the family as the twins `nch`, `nch__2`, `nch__3`, `nch__4`
(declaration order), each carrying the family name and the literal default of
every parameter beside the declared ranges. Inside a module the compiler selects
at elaboration; on a `.model` card ngspice selects when the card is
materialised, and announces the member it chose.

## Run

```
python3 verify_paramsetoverload.py
```

14 checks per solver, all PASS.
