# Enhancement-638: an assignment to a genvar inside its own loop is refused, and named

**Scope:** F4 of the
[2026-09-14 hunt](../docs/bug_hunts/2026-09-14_openvaf-r-parameters-arrays-and-hierarchy.md).
`for (i=0;i<3;i=i+1) begin i = i + 1; … end` was unrolled like any other use
of `i` and reported by the parser as `unexpected token integer` at `0 = 0 + 1`
in a generated copy, once per copy. Compiler: `openvaf/hir/src/elaborate.rs`
(`unroll_first_analog_genvar_loop`). New suite
[`genvarassign_examples`](../examples/genvarassign_examples/) (4 checks per
solver). **Compiler side.**

**Suites:** `genvarassign_examples` 4 of 4 per solver, both solvers;
`generate`, `legacygen`, `genhier`, `elabguard`, `genvarloop`,
`baregenerate` green; the `hir` crate tests green; full sweep 511 of 511.

## What was wrong

An analog genvar loop is not a run-time loop: the unroller substitutes the
genvar's value into a copy of the body per iteration (E-407). An assignment
to the genvar inside the body was substituted with everything else, so the
copies read `0 = 0 + 1;`, `1 = 1 + 1;`, `2 = 2 + 1;`, and the parser refused
each one:

```
error: unexpected token integer; expected ';', '@', 'begin', 'case', 'casex',
'casez', 'disable', 'for', 'if', 'integer', 'parameter', 'localparam', 'real', 'string', 'while',
'repeat', 'do', 'break', 'continue', 'return', identifier or system function identifier
    --> /g5.va__generated.va:135:82
```

— three times, in a file that does not exist, with a token list that offers
`casex` and `casez`, and never the word "genvar". A nested loop reusing the
genvar as its own loop variable (`for (i=…) for (i=…)`) went the same way.

## What changes

Before a loop is unrolled, its body's tokens are scanned for the genvar
followed by `=` (the assignment token; `==` is another token). One preceded
by `for (` is a nested loop reusing the genvar; any other is an assignment.
Both are refused where the header's errors are already reported, with the
statement quoted:

```
error: genvar for loop `i`: `i` is assigned inside its own loop body (`i = i + 1;`); a genvar
takes its values from the loop header only -- give a value that changes in the body to an
integer variable
error: genvar for loop `i`: a loop nested inside it uses `i` as its own loop variable; a
genvar names one loop at a time -- nest with a different genvar
```

A comparison on the genvar (`i == j`), an assignment *from* it (`k = i`), an
indexed assignment (`a[i] = i`) and a nested loop over a different genvar are
not assignments to the genvar and compile as before.

## Verification

| check | result |
|---|---|
| `i = i + 1;` in a begin/end body | refused, the statement quoted, no generated-copy parse error |
| `i = 7;` as the loop's single statement | refused the same way |
| `for (i=…) begin for (i=…) … end` | refused as reuse, with the advice |
| `i == j` over nested genvars, `k = i`, `a[i] = i` | compile and compute (3, 4, 3 mA) |
| `genvarassign_examples` | 4 / 4, both solvers |
| full sweep | 511 of 511 |
