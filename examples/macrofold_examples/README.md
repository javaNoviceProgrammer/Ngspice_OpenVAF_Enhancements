# macrofold_examples — Enhancement-641

Macro text survives the paramset fold's re-rendering. A paramset's
`module.localparam` references (E-563) are folded by re-rendering the
expanded token stream and re-parsing it, and three things the preprocessor
did to macro text broke that text: a `//` comment at the end of a `` `define ``
body was kept as macro text (IEEE 1364-2005 19.3.1 says it is not) and
commented out the rest of the rendered line; the white space after an
argument reference and after a macro call was dropped (`blkAreal`, `endI(`);
the line break after an `` `include `` was dropped, so an included file that
ends without a newline ran into the next line. Every IHP SG13G2 paramset over
r3_cmc or PSP103 died on the first of these.

`macrofold.va` has all three (a trailing-comment macro, a multi-line macro
with an argument before a continuation, an include ending in `else` with no
newline) under two paramsets that read `consts.rsh` and `consts.scale`; the
checks compile it, read 1/7 + 1/14 A through the fold, and pin the expansion
text itself.

Run: `python3 verify_macrofold.py` (4 checks per solver, both solvers).
