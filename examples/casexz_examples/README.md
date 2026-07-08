# casexz_examples — `casex` / `casez` don't-care case statements (Enhancement-78)

`casex` and `casez` are the don't-care variants of the `case` statement. When a
based literal with `x`/`X`, `z`/`Z`, or `?` digits is written directly as a case
item, those digits form a **comparison mask**: the arm matches when the
discriminant equals the item on every *care* bit. `casex` treats `x`, `z` and
`?` as don't-cares; `casez` treats only `z` and `?` as don't-cares (an `x` digit
in a `casez` item is an error). Enhancement-78 lowers these to care-mask
comparisons (`iand` + `Ieq`) threaded through a `CaseKind`/`CaseMask` in the
pipeline; plain `case` is unchanged.

## What's here

| file | what it demonstrates |
|---|---|
| `casexz_probe.va` | 8-way self-checking bitmask probe (the E-37 audit technique): each correct don't-care decision adds a power of two to a `score` exposed as DC conductance, so any wrong semantics shows as a specific missing/extra bit — expected score **63/63** |
| `priority_enc.va` | the classic idiom — a `casex` priority encoder whose 4-bit request word `sel` comes from the model card; the highest set bit wins (`4'b1xxx`→8, `4'b01xx`→4, …), including the all-zero `default` |
| `d1.va`, `d2.va`, `d3.va` | negative cases: a don't-care literal used outside a `casex`/`casez` item, an `x` digit in a `casez` item, and a non-integer (real) `casex` discriminant — each must be a clean, located compile error |
| `_p1.cir`, `_p2.cir` | ngspice decks driving the probe / encoder |

## Verify

```
python3 verify_casexz.py
```

Compiles each model with the committed `openvaf-r`, runs it in the committed
ngspice, and checks: the 63/63 bitmask semantics (casex `x`/`z`/`?` masking,
casez `z`/`?`-only, fully-specified mismatch → default, first-match-wins arm
order, plain `case` unchanged), the priority encoder's output at every input
value, and that the three illegal constructs are rejected with their pinned
diagnostics. See [`../../enhancements_doc/Enhancement-78.md`](../../enhancements_doc/Enhancement-78.md)
for the full write-up.
