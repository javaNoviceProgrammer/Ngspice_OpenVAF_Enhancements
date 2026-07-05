# multianalog_examples — multiple analog blocks (Enhancement-60)

Validates **multiple `analog` / `analog initial` blocks per module**
(Verilog-AMS LRM 6.2: several blocks behave as if concatenated into a
single block in source order) — using the committed `openvaf-r` and
`ngspice-46`.

## The finding

The Enhancement-60 probe battery found this feature **fully supported by
construction** — hir_def's body collection iterates *every* analog block of
a module into `entry_stmts` in document order, which is literally the LRM's
as-if-concatenated semantics; every downstream compiler stage consumes that
list. Nine corners probed, **zero defects** — so, like Enhancement-57, the
deliverable is the validation itself. No compiler or ngspice source changes.

## Files

| file | pins |
|---|---|
| `multianalog_demo.va` | three blocks accumulating 3 mS; variable written in block 1 read in block 3; `analog function` declared between blocks; parameter declared after first use; `cross` event in the middle block + `final_step` strobe in the last; `ddt()` of a charge computed in an earlier block |
| `order_demo.va` | strobes print in source order; two `analog initial` blocks compose in order (`g = 1m; g = g + 1m` → exactly 2 mS) |
| `hier_demo.va` | a multi-block module survives instance flattening (E-5 elaboration re-render) — series current exact to 12 digits |
| `_dup_named.va` | negative: duplicate named child blocks (`begin : work` in two analog blocks) are a clean duplicate-declaration error |

## Run

```bash
python3 verify_multianalog.py
```

6 checks, ALL PASS.
