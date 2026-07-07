# blockparam_examples — block-scoped parameters (Enhancement-87)

`parameter`/`localparam` declared inside a named `begin: label` block
(LRM 6.3, page 112). They are compile-time constants local to the block,
read hierarchically (`label.name`), and derivable from the enclosing
module's parameters — so a model-card override of a **module** parameter
flows into the block-scoped parameters that depend on it.

`blockparam.va`: `vout = gain² + 1 + offset·10`.

| Model card | Expected |
|---|---|
| defaults (gain=2, offset=0.5) | 10 V |
| `gain=3 offset=0.2` | 12 V (override flows into block params) |
| `nested.va` (outer→inner block param) | 7 V |

The verify script also checks that an instance override of a block-scoped
parameter (`#(.s.g2(9))` — the LRM's page-112 `// error` case) is rejected
with a targeted diagnostic, not a parser cascade.

Run: `python3 verify_blockparam.py` (6 checks).
