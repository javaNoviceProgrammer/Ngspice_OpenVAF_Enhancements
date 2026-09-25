# Enhancement-718: an expression may be 32 768 levels deep, not 1000 — a flat sum of a thousand terms was refused as "nesting too deeply" although the parser reads a chain iteratively and only the passes after it recurse over the left-leaning tree; the front end runs on a 512 MB thread, the diagnostic says what it counts, and it stands alone — an over-deep call argument no longer draws "invalid argument count" after it

**Scope:** F4 of the
[correctness campaign of 2026-09-25](../docs/bug_hunts/2026-09-25_openvaf-r-correctness-campaign.md).
**Compiler only.** `parser/src/grammar/expressions.rs` (`MAX_EXPR_DEPTH`, `expr_too_deep`),
`parser/src/lib.rs`, `parser/src/grammar.rs`, `parser/src/parser.rs` (the bound exported),
`syntax/src/lib.rs`, `syntax/src/error.rs`, `basedb/src/diagnostics/syntax_error.rs` (the
diagnostic), `openvaf/src/lib.rs` (the front-end thread), `hir_def/src/body/lower.rs` (call
arguments).
[`examples/robustness_examples/`](../examples/robustness_examples/) (E-148's suite, 39 checks,
14 of them new), [`examples/vafdefine_examples/`](../examples/vafdefine_examples/) (17,
section [2] re-pinned), [`examples/hunt17diag_examples/`](../examples/hunt17diag_examples/)
(24 per solver, check [k] re-pinned). The hunt page and the handbook.

**Suites:** `robustness` 39 of 39 (26 of 39 on the E-714 binaries), `vafdefine` 17 of 17
(14 of 17), `hunt17diag` 24 of 24 per solver (22 of 24); `diagslips` 46 of 46 per solver,
`vafice` 11 of 11, `langguard` 132 of 132, `vafcrash2` 22 of 22, `vafcrash4` 3 of 3,
`arrayscale` 38 of 38, `filterforms` 100 of 100, `lrmexpr` 25 of 25 per solver and
`probebus` 11 of 11 per solver unchanged; the compiler workspace tests green apart from
the three pre-existing sourcegen drift failures (221 passed), no build warnings; full
sweep, run alone (`rtdomain`'s timing check [9] flaked under the load and passed 16 of 16
alone, as it does).

## What was wrong

`analog r = 1.0/1 + 1.0/2 + … + 1.0/N;` (`cc/K/sumN.va`), on E-714:

| N | result |
|---|---|
| 800 | compiles, and folds to the Python value to the last bit |
| 999 | `error: expression nests too deeply` |
| 1 000, 1 200, 1 500 | the same |

The same for a product of N factors; the same 1 500 terms in thirty parenthesised groups
compiled, and so did 1 500 statements `s = s + 1.0/k;`. The help note said "openvaf limits
expression nesting (and operator-chain length) to 1000 to avoid overflowing the parser".

The parser does not overflow on a chain. Its Pratt loop (`expr_bp_inner`) reads
`a + b + c + …` iteratively, two frames deep however long the line; E-148's counter adds
one per operator all the same, because the tree the chain builds is left-leaning — as deep
as the chain is long — and the passes after the parser recurse over it once per node:
`hir_def`'s body collection, `hir_ty`'s inference and validation, `hir_lower`. Those ran
on the main thread's 8 MB stack. With the guard lifted, that stack takes:

| shape, 8 MB main thread | compiles | overflows |
|---|---|---|
| flat chain `a + a + …` | 7 000 terms | 8 000 |
| nested parentheses | 16 000 | 32 000 |
| stacked unary minus | 8 000 | 16 000 |
| nested calls `sin(sin(…))` | 4 000 | 8 000 |
| nested `?:` | 4 000 | 8 000 |
| Horner polynomial `((c·x + c)·x + c)…` | 2 000 | 4 000 |

so E-148's 1000 was the right bound for that stack, a factor of four under the worst
shape. It was the stack that was small: a generated model — a polynomial fit, a table
written out as a sum of products — carries a thousand terms on one line without a thought,
and the LRM has no limit. E-264 met the same recursion in the codegen (a deep fan-in
chain differentiated recursively) and gave those workers a 256 MB stack; the front end
had stayed on the default one.

## What changed

**The front end runs on a 512 MB thread** (`openvaf::compile`, `FRONTEND_STACK_SIZE`):
`compile` spawns a scoped thread with that stack for the whole of the front end — parse,
HIR, MIR, `sim_back` — and joins it, resuming a panic on the main thread so the crash
report is what it was. A thread's stack is reserved, not committed; a run's resident size
is unchanged (0.3 GB at 32 000 voltage terms is the model). With the guard lifted, on a
256 MB stack:

| shape, 256 MB thread | compiles | overflows |
|---|---|---|
| flat chain | 128 000 terms | 256 000 |
| nested parentheses | 512 000 | — |
| stacked unary minus | 256 000 | 512 000 |
| nested calls | 128 000 | 256 000 |
| nested `?:` | 128 000 | 256 000 |
| Horner polynomial | 64 000 levels | 128 000 |

**The bound is 32 768 levels** (`parser::MAX_EXPR_DEPTH`, exported through `syntax` so the
diagnostics read the same number), one counter for both kinds as before — an operator in a
chain and a nesting level each cost the later passes one frame — a factor of four under
the worst shape at 256 MB and eight at 512 MB. A chain of 32 700 terms compiles in
0.2 s; 32 800 is refused. The counter is a lower bound on the tree's depth: the operators
that wrap a nested operand are counted after that operand was parsed, so a Horner
polynomial of degree d passes with a tree 3d deep, which is why the stack is sized to the
Horner row above rather than to the chain.

**The diagnostic says what it counts:**

```
error: expression is deeper than 32768 levels: an operator chain counts one level per operator, and so does each nesting
  --> sum.va:3:382108
  |
3 | analog begin r = 1.0/1 + 1.0/2 + 1.0/3 + …
  |                                          ^ level 32769 is here
  |
  = help: openvaf bounds the depth of an expression at 32768 levels so that no legal file can overflow the compiler's stack: a chain `a + b + c + ...` is as deep as it is long (one level per operator), and a parenthesis, a call, a prefix operator or a `?:` adds one nesting level; split the expression across intermediate variables or statements
```

**And it stands alone.** E-665 made the recovery skip to the end of the expression so the
statement parser saw none of it; inside a call it still cascaded. `sin(sin(…))` past the
bound read "invalid argument count: expected 1 arguments but found 0" after the depth
error, because the ERROR node the recovery leaves is not an expression and the call
collected no argument; `pow(a + a + …, 2.0)` read "found 1", the recovery having run
past the comma and swallowed the second argument. Three small changes: the recovery also
stops at a `,` at bracket depth zero (Verilog-A has no comma expression, E-423, so the
comma is the enclosing list's); `expr_too_deep` hands the ERROR node back as the
expression's node instead of `None`, so an argument list, a declaration list or a
parenthesis that would give up on `None` — and let `, b)` fall to the enclosing call,
which read it as arguments of its own — carries on at the token the recovery stopped at;
and `hir_def` records an ERROR node at the start of an argument as a missing argument
(one that follows an argument is that argument's tail). The innermost, the first, a middle
and the last argument of a call, a declaration list, a statement, an `if` condition, a
parenthesis and an array literal each draw the one error; two over-deep expressions in
one module draw two.

## Verification

`robustness`: the five 40 000-deep shapes of E-148 (unary, binary, parentheses, calls,
ternary) still fail cleanly, and now each with the one error naming the bound; a chain
of 32 800 terms is refused and one of 32 700 compiles; a 5 000-term sum, a 2 000-deep
nested ternary, 2 000 nested calls and a Horner polynomial of degree 2 000 compile
(E-714 refuses all four); the campaign's 1 500-term harmonic sum compiles and, through
ngspice with 17 digits, evaluates to Python's left-to-right sum 7.8907693482881305 bit
for bit. `vafdefine` [2]: the 1 200-term chain it used to refuse compiles and reads
1.2; a 40 000-term one says how deep an expression may be and what counts, and the note
names the bound. `hunt17diag` [k]: the 999-parameter flat sum compiles; a chain past the
bound draws the depth error once and nothing about the parameters after it.

By hand: the campaign's K probes (`s999`, `sum1000`, `sum1200`, `sum1500`, `prod1000`,
`prod1500`, `grp1500`, `stm1500`) compile and `prod1500` telescopes to 1501; the twelve
over-deep contexts above; the capacity tables (one compile at a time under the memory
watchdog); the thirteen suites; the workspace tests; the sweep.

## What this does not do

- The passes after the parser still recurse once per node; the bound is where a legal
  file stays clear of the stack, not a flatter tree. A file that is deeper still is
  refused as before, with the new message.
- The counter is not the exact tree depth (above); the stack is sized for the
  under-count, and the message is true whenever it is shown.
- E-264's codegen pool keeps its 256 MB workers; nothing in the codegen changed.
- E-148's other two caps (include depth 64, array elements about a million) are as they
  were; E-148, E-387 and E-388 describe the 1000-level bound as it was.
