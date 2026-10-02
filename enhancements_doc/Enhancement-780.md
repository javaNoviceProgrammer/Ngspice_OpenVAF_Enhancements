# Enhancement-780: a `case` with no `(expr)` stalled the parser for ten million steps — an item that consumes nothing now ends the item list

**Scope:** OpenVAF: `openvaf/parser/src/grammar/stmts.rs` (`case_stmt`, `vals_or_default`),
`openvaf/parser/src/grammar/items/module.rs` (`generate_case_tail`),
`openvaf/parser/src/parser.rs` (`Parser::pos`). From the macOS Intel CI sweep, where
vafcrash2's keyword salad was a HANG (over the suite's 25 s).

**Suites:** vafcrash2 (five new checks, 27 of 27; the shipped compiler fails four of them), and
the parser suites arraycase, baregenerate, casexz, crashfix, crashfix2, crashfix3, generate,
genhier, genvarassign, genvarloop, legacygen, parserfuzz, vafcaseloop, vafcrash, vafcrash3,
vafcrash4 and vafdegen.

## What was wrong

A `case` keyword with no `(expr)` before a token that belongs to an enclosing construct --
`analog begin case end end`, or the keyword salad of E-220 -- reached the item loop of
`case_stmt` with that token current. An item parsed at `end` reports its errors and consumes
nothing (`end` is in the expression's recovery set), and the loop, which ends only at
`endcase`, `endmodule` or the end of the file, parsed the same empty item again. Only the
stall guard ended it (E-220, E-711): ten million lookahead steps without a consumed token, and
2,857,143 errors on the way. That is 2.3 s on an Apple M-series machine, whatever the input's
length (`analog begin case end end endmodule` alone), and past 25 s on a macOS Intel runner
running four suites at once. The value list of an item (`vals_or_default`) had the same loop.

## The change

Each of the two loops, and the arm loop of a generate `case`, which has the same shape, compares
the parser's position before and after an iteration; an iteration that consumed nothing ends the
list, and the token is left to the construct it belongs to. `case end` is now 11 errors in
0.01 s, the keyword salad 202 errors in 0.12 s.

A fuzz of short keyword and punctuation sequences in four contexts (an analog block, a module
body, the top level, a bare `analog`) found seven stalls in 400 inputs before the change, every
one a `case` or `casex`, and none in 1,600 after it. The stall guard stays as the backstop.

## Limits

- Other grammar loops end only at their recovery sets as before; the fuzz found none that
  stalls, and the guard still bounds any that does.
