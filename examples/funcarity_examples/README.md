# Two-argument function arity crash fix (Enhancement-239)

A fifth find from the memory-safety deep dive (after
[E-235](../../enhancements_doc/Enhancement-235.md)–[E-238](../../enhancements_doc/Enhancement-238.md)),
surfaced by fuzzing the behavioral-source expression parser.

The B-source / `.param` expression evaluator (`PTeval` in
[ifeval.c](../../ngspice-46/src/spicelib/parser/ifeval.c)) evaluates the
**two-argument** functions `pow`/`pwr`/`min`/`max` by reading their operands as
`tree->left->left` and `tree->left->right` — i.e. it assumes the argument is a
`PT_COMMA` pair:

```c
case PTF_POW: case PTF_PWR: case PTF_MIN: case PTF_MAX:
    err = PTeval(tree->left->left,  gmin, &r1, vals);   /* <-- */
    err = PTeval(tree->left->right, gmin, &r2, vals);
```

A **one-argument** call like `min(1)` makes the argument a scalar node whose
`->left` is NULL, so `PTeval` dereferenced NULL and **crashed (SIGSEGV)** at
circuit-load time — reachable from any B-source, E/G source, or `.param`
expression. (`min()`, `min(1,2,3)`, and the single-arg forms of the *other*
functions like `hypot(1)` all failed cleanly; only these four crashed.)

The parser (`PT_mkfnode`, [inpptree.c](../../ngspice-46/src/spicelib/parser/inpptree.c))
never validated argument count. E-239 adds an arity check: `pow`/`pwr`/`min`/`max`
now require a comma pair and otherwise emit a clean *"requires two arguments"*
parse error instead of crashing.

## Verify

```sh
python3 verify_funcarity.py
```

Three checks: one-argument `min(1)`/`max(1)`/`pow(2)`/`pwr(2)` in a B-source no
longer crash; the same misuse inside a `.param` expression no longer crashes; and
well-formed two-argument calls still compute the correct value (min(3,7)=3,
max(3,7)=7, pow(2,10)=1024, pwr(2,3)=8).
