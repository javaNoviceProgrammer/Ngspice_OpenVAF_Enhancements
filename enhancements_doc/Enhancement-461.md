# Enhancement-461 — string-parameter set selection

Reported from the field:

```verilog
parameter string ty = "NMOS" from '{"NMOS", "PMOS"};
```

does not work — a legal member is rejected at setup with `Parameter ty is out of
bounds!`. Two independent defects were behind it, one in each code base, and
either alone reproduces the report.

## 1. Only the first member of the set was ever enforced

LRM 3.4.2 gives string parameters their own range form: *"The `from` keyword may
be used with a list of valid string values, or the `exclude` keyword may be used
with a list of invalid string values … the list is constructed using an
assignment pattern"*.

The parser reads the whole list — `expr(p)` followed by
`while p.eat(T![,]) { expr(p) }` — so every member lands in the syntax tree. The
AST accessor then threw the rest away:

```rust
// syntax/src/ast/node_ext.rs
Some(ConstraintValue::Val(self.expr()?))   // support::child -> the FIRST child
```

Measured, with `from '{"aaa","bbb","ccc"}`:

| value | before | after |
|---|---|---|
| `"aaa"` (first) | accepted | accepted |
| `"bbb"` | **out of bounds** | accepted |
| `"ccc"` | **out of bounds** | accepted |
| `"zzz"` (not a member) | refused | refused |

Writing the same set in a different order changed *which single value was
legal*. And `exclude` failed the dangerous way round: with
`exclude '{"aaa","bbb"}`, the value `"bbb"` — explicitly forbidden by the model —
was **silently accepted**. Nothing warned, because as far as the compiler was
concerned the set simply had one member.

This is Enhancement-429's shape: elements parsed, attached to the tree, and
dropped by the accessor, with the errors hiding in what was dropped.

**The fix is a set becoming one `ParamConstraint` per member**, which is exactly
what `check_param` already wanted. It walks the constraints of one kind and
`From` branches to the ok-exit on any match, calling `invalid` only on
fallthrough, while `Exclude` calls `invalid` on any match — so a correct set
falls out with no change to the checking logic at all. Numeric sets
(`from '{1,2,3}`) had the identical defect and are fixed by the same change.

## 2. The value was corrupted before the model saw it

Even a correct set check could not have matched, because the string never
arrived as written:

| netlist | model received |
|---|---|
| `ty="PMOS"` | `pmos` |
| `ty="File_Name.TBL"` | `file_name.tbl` |
| `ty="with space"` | `with` — and `unrecognized parameter (space)` |

Two causes on the ngspice side:

- The netlist reader lower-cases whole lines, with case retention wired only to
  Cider `.model` cards, `ic.file`, and a fixed list of XSPICE code models. An
  OSDI model card matched none of them, so it got the blanket fold. The existing
  helper also only preserves a line carrying *exactly one* pair of quotes, which
  a model card with two string parameters already exceeds.
- `inp_casefix` turns quotes into **spaces** unless the line is `.param`,
  `.subckt` or an X line — which is what cut the value at its first space.

A quoted value on a model card or a device instance line is **data** — a
selector compared with `==`, a file name, a `from` set member — not an
identifier SPICE may fold. Both paths now keep it verbatim, on the card, on its
`+` continuations, and on instance lines, gated on the line actually containing
`="` so nothing else changes.

### A trap inside the fix

Adding `.model` to `keepquotes` made the case *worse* before it made it better:
the quoted text came back lower-cased even though the quotes now survived. With
`keepquotes` set, the code never stepped **past** the opening quote, so the
skip-to-closing-quote loop exited immediately and the tail of the same loop
lower-cased the value one character at a time — keeping the quotes while losing
the case they exist to protect. The fix is one `else string++;`.

## Verification

`examples/strparam_examples/verify_strparam.py` — **33/33**, both solvers. It
checks the set semantics through a real simulation (every member accepted, a
non-member refused, order irrelevant, `exclude` refusing all of its members) and
separately checks the value the model receives, because either defect alone
reproduces the report. Numeric sets, `.model` continuation lines and instance
lines are all pinned, and the reported model is exercised end to end.

**Corpus: 107 compiled by both, 17 rejected by both, 0 rc differences, 0 byte
differences** against the Enhancement-460 binary. `cargo test` passes across 44
test binaries. Full regression **375/375**, both solvers — the check that
matters most here, since the ngspice change touches how every netlist line is
read.
