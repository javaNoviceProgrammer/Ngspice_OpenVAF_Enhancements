# Enhancement-339 — `v()` with three or more node names SIGSEGV'd ngspice

Found by fuzzing the `pyplot` command family. The defect is not in pyplot: it is
in the shared expression parser, and `print` and `let` crash identically.

```
print  v(in,out,0)   ->  SIGSEGV
let q = v(in,out,0)  ->  SIGSEGV
pyplot v(in,out,0)   ->  SIGSEGV
plot   v(in,out,0)   ->  survives
```

`plot` surviving is why this was easy to miss — the obvious spot-check passes.

## Root cause — two paths with different ownership

`v()` takes at most two node names: `v(a)`, or the differential `v(a,b)`. A third
was never rejected. `PP_mkfnode` handles the comma form by recursing:

```c
if (!f->fu_func && arg->pn_op && arg->pn_op->op_num == PT_OP_COMMA) {
    p = PP_mkbnode(PT_OP_MINUS, PP_mkfnode(func, arg->pn_left),
                                PP_mkfnode(func, arg->pn_right));
    free_pnode(arg);            /* <- this branch CONSUMES its argument */
    return p;
}
...
p->pn_left = arg;
p->pn_left->pn_use++;           /* <- the normal path BORROWS it */
```

The two paths disagree about ownership, and `free_pnode` recurses into children
guarded by `pn_use`:

- **Two names** — the children are plain nodes, so each recursive call takes the
  *borrow* path and bumps `pn_use` to 2. The outer `free_pnode(arg)` then merely
  decrements. Safe.
- **Three or more** — one child is *itself a comma node*, so the recursive call
  takes the *consume* path and frees it. The outer `free_pnode(arg)` then walks
  into that already-freed child. Double free.

Node existence is irrelevant: all-present `v(in,out,0)`, all-missing `v(a,b,c)`
and mixed `v(in,out,zz)` crash alike. It is purely the arity.

## The fix

Reject the invalid arity where it is detected, rather than relying on the
inconsistent ownership:

```
Error: v() takes at most two node names.
```

Repairing the ownership mismatch instead would mean changing `PP_mkfnode`'s
contract for every caller, to make a syntactically invalid expression work — the
arity is not legal in the first place, so rejecting it is both smaller and more
honest. The mismatch itself is recorded here as the underlying hazard.

## Fuzz campaign

**122 pyplot invocations, 0 crashes, hangs or unexpected writes** after the fix.
The corpus crosses the eight mode flags (`-eye -hist -contour -smith -fft -bode
-nyquist -polar`) against missing, extra, repeated and conflicting arguments,
plus hostile signal lists (unclosed `v(`, empty `v()`, 8000-character names,
control characters, 200 signals) and hostile output base names (3000 characters,
spaces, quotes, shell metacharacters, unicode, leading `-`).

One thing the fuzz flagged that is **not** a defect: `pyplot ../name` and
`pyplot /abs/path` write outside the working directory. That is the documented
contract — `pyplot [file] plotargs` — and ngspice's other writers (`wrdata`,
`write`) behave the same. The user supplied the path; the fuzz policy was wrong,
not the command.

## Files

- `ngspice-46/src/frontend/parse.c` — reject three or more node names in the
  comma branch of `PP_mkfnode`.
- `examples/vfuncarity_examples/` — three and four names are a clean error across
  `print`/`let`/`pyplot`, and one and two still work
  (`verify_vfuncarity.py`, 5 checks).
