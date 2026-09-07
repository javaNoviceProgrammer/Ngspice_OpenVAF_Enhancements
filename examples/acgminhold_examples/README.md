# acgminhold_examples — Enhancement-571: a gmin-held node is held in AC too

`verify_acgminhold.py` pins, under **both** linear solvers, that a node the
operating point holds only by gmin — one nothing conducts to (Enhancements 566
and 569), or an open MOSFET gate with no capacitance — is held the same way in
the small-signal matrix, so `ac`, `noise` and `sp` run on the deck instead of
ending in "matrix is singular" right after a successful operating point.

`CKTacLoad` holds exactly the nodes whose AC row or column is all zero, with the
conductance the DC hold used (`gshunt` when set, else `gmin`), and nothing else.
The suite pins the held values (1/gmin for an AC-driven current-source node,
following `gshunt` when set), the analyses that now run, and two decks that must
not move at all: an RC low-pass at its corner and a node whose only element is a
capacitor.

Run it:

```
python3 verify_acgminhold.py
```
