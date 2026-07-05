# preproc_examples — preprocessor audit + macro-recursion guard (Enhancement-65)

A systematic audit of the Verilog-A compiler directives — the preprocessor
predates every enhancement in this series and had never been probed — using
the committed `openvaf-r` and `ngspice-46`.

## The audit (22 probe forms, one defect)

Everything works, verified **numerically exact** at runtime (compiling
proves nothing about correct expansion): `define` with arguments,
macros-using-macros, macro calls as macro *arguments*, `ifdef`/`ifndef`/
`elsif` chains and nesting (including inside module bodies), `undef` +
redefinition, `resetall`, backslash-continued definitions, trailing
comments, multi-line macro calls, nested `include` chains, and clean
located errors for undefined macros / unbalanced `ifdef`.

**The defect: recursive macro expansion crashed the compiler** with a
stack overflow — both `` `define LOOP (`LOOP + 1) `` and the mutual
`` `A `` ↔ `` `B `` form. The `MacroRecursion` diagnostic *already
existed* in the preprocessor's enum with a rendered message, but nothing
ever emitted it (`call_macro` carried a literal `// TODO track recursion`)
and its report builder was a literal `todo!()`. The fix pushes an
expansion stack **around the macro body only, after arguments are
built** — a nested call of the same macro inside an *argument*
(`` `define QUAD(x) (`TWICE(`TWICE(x))) ``) is finite and legal, and a
naive guard rejects exactly that.

## Files

| file | purpose |
|---|---|
| `preproc_demo.va` | 8-way self-checking macro tour — every feature contributes 1 mS, total exactly 8 mS, with a dead `ifdef` branch that would add 100 S if it leaked |
| `incchain_demo.va` + `_inc_mid.vams` + `_inc_leaf.vams` | two-deep `include` chain |
| `_rec_direct.va`, `_rec_mutual.va` | negative tests (clean recursion errors, no crash) |

## Run

```bash
python3 verify_preproc.py    # 5 checks
```
