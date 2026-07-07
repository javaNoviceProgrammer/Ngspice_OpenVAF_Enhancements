# paramwidth_examples — multi-name name-then-range + parameter-dependent widths (Enhancement-91)

Two declaration features, both textual pre-passes reusing the existing bus
(E-3) and array (E-14) machinery.

**Multi-name name-then-range** (`multiname.va`): a comma list with per-name
ranges, `input a[0:1], b[0:3], c;`, is split into one range-then-name
declaration per name — completing the single-name form of Enhancement-89.

**Parameter-dependent widths** (`paramwidth.va`): a declaration range whose
bounds reference a parameter, `electrical [0:N-1] out;` / `real w[0:N-1];`,
is folded to a literal range using the parameter's elaboration-time default
(a structural parameter — the width is fixed at the default, since OSDI has
one node count per module). Shown with a param-sized array + runtime loop and
a param-width node bus at two different default widths.

Run: `python3 verify_paramwidth.py` (11 checks).
