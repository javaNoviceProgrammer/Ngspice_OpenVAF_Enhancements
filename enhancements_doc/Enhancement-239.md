# Enhancement-239 — expression parser: fix a NULL-deref on a one-argument `min`/`max`/`pow`/`pwr`

A fifth find from the same memory-safety deep dive (after E-235 – E-238),
surfaced by fuzzing the behavioral-source expression parser and reproducible on
the shipped binary.

## The bug

The behavioral-source / `.param` expression evaluator (`PTeval`,
`spicelib/parser/ifeval.c`) evaluates the **two-argument** functions
`pow`/`pwr`/`min`/`max` by reading their operands as `tree->left->left` and
`tree->left->right` — it assumes the function's argument is a `PT_COMMA` pair:

```c
case PTF_POW: case PTF_PWR: case PTF_MIN: case PTF_MAX:
    err = PTeval(tree->left->left,  gmin, &r1, vals);
    err = PTeval(tree->left->right, gmin, &r2, vals);
    *res = PTbinary(tree->function)(r1, r2);
```

The function-node builder `PT_mkfnode` (`spicelib/parser/inpptree.c`) looks the
name up in the function table but **never validates argument count**. A
one-argument call such as `min(1)` therefore builds a node whose `left` is the
single scalar operand — a `PT_CONSTANT` whose `->left` is NULL. At load time
`PTeval` does `tree->left->left`, dereferences NULL, and **crashes (SIGSEGV)**:

```
b1 2 0 v=min(1)      →  ngspice -b  segfaults (EXC_BAD_ACCESS at 0x0)
                         PTeval ← IFeval ← ASRCload ← CKTload
```

It is reachable from any B-source, E/G source, or `.param` expression — a
one-line typo crashes the simulator during setup. The crash is specific to these
four functions and the one-argument (scalar, non-comma) form: `min()` is caught
by the existing `if (!arg)` guard, `min(1,2,3)` yields a `PT_COMMA` (no NULL
deref), and the single-argument forms of other functions (`hypot(1)`,
`atan2(1)`) fall through the single-argument `PTeval` path and error cleanly.

## The fix

Reject the wrong arity at parse time, in `PT_mkfnode`, right after the function
lookup succeeds:

```c
if ((funcs[i].number == PTF_POW || funcs[i].number == PTF_PWR ||
     funcs[i].number == PTF_MIN || funcs[i].number == PTF_MAX) &&
    arg->type != PT_COMMA) {
    fprintf(stderr, "Error: function '%s' requires two arguments "
        "at line %d\nfrom file\n  %s\n", buf, Current_parse_line, Sourcefile);
    controlled_exit(EXIT_BAD);
}
```

These four functions now require a comma pair; a one-argument call produces a
clean *"requires two arguments"* error (matching the file's existing parse-error
style — "no such function", "bogus ternary_fcn form", …) instead of a NULL
deref. Because the check is at parse time, the malformed node is never built, so
both evaluation and the derivative pass are protected. Well-formed calls are
unchanged, and the internal derivative constructions (which always build a
`PT_COMMA`) are unaffected.

## Verification (`examples/funcarity_examples`)

`verify_funcarity.py` (3 checks): one-argument `min(1)`/`max(1)`/`pow(2)`/`pwr(2)`
in a B-source no longer crash; the same misuse inside a `.param` expression no
longer crashes; and well-formed two-argument calls still compute the correct
value (min(3,7)=3, max(3,7)=7, pow(2,10)=1024, pwr(2,3)=8). The full B-source /
number-parser fuzz sweep is crash-free after the fix.

## Scope

ngspice expression parser only — one arity guard in
`spicelib/parser/inpptree.c`. No solver, analysis, device, or compiler change;
well-formed expressions are unchanged. Full regression: 197/197.
