# pivrelone_examples — Enhancement-871

[E-871](../../enhancements_doc/Enhancement-871.md): D1 of the
[Sparse and KLU correctness campaign of 2026-10-11](../../docs/bug_hunts/2026-10-11_sparse-klu-correctness-campaign.md).

Sparse's whole-matrix pivot search accepts an element only if |a| > pivrel × (its column's
largest). With `pivrel=1` that strict test admits nothing. The search then takes the largest
element of the reduced matrix, and E-736 recorded every such step as a pivot below `pivtol`: "the
pivot for node neg … is 1e+12, below pivtol (1e-13)". Now only a pivot at or below the absolute
threshold is a small pivot. The pivot chosen is the same, so the answers are unchanged.

The warnings speak when the deck sets `pivtol`, as these decks do. The decks pin Sparse, whose
search this is.

The checks:
- **[1]** A follower, `pivrel=1 pivtol=1e-13`: no pivot is reported (E-869: 1e+12).
- **[2]** Teraohm dead ends, `pivrel=1 pivtol=1e-13`: every pivot reported is below 1e-13.
  E-869 reported 3370.9 and 1, and the first of those hid the real 3.2e-14.
- **[3]** (control) A pivot below `pivtol` is still reported: the follower with `pivtol=1e13`.
- **[4]** (control) The answers are unchanged: the follower's to the bit, and v(3) = v(1).

Run: `python3 verify_pivrelone.py` (4 checks per pass). On the E-869 binaries [1] and [2] fail.
