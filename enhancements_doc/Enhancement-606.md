# Enhancement-606: `showmod` finds a subcircuit's model by its hierarchical name

**Scope:** `src/frontend/gens.c` (`dgen_hier_model_match`, consulted in `dgen_next`
beside E-410's instance match), `examples/showmodhier_examples/` (new, 8 checks per
solver). **ngspice only; built-in and OSDI models alike.** Finding N1 of the 2026-09-10
integration hunt
([`docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md`](../docs/bug_hunts/2026-09-10_ngspice-osdi-integration-second-hunt.md)),
a stock ngspice defect.

**Suites:** [`showmodhier_examples`](../examples/showmodhier_examples/) 8 of 8 per
solver, both solvers; `namelookup`, `showwidth`, `instdep`, `carddefault`, `multimod` unchanged;
full sweep 502 of 502 (one sweep, Enhancements 604–608 folded together).

## What was wrong

Subcircuit expansion renames a model card inside `x1` to `x1:rm` (nested:
`x1.x2:rm`). `altermod x1.rm r=3k` and `altermod x1:rm r=3k` both reach it, and
`showmod x1.r1` shows it through the instance — but `showmod x1.rm` and `showmod x1:rm`
answered "No matching instances or models". The device generator's grammar could
express neither: Enhancement-493's retry compares `#x1.rm` whole against `x1:rm`, and
in `#x1:rm` the ':' is the grammar's subcircuit delimiter, which leaves a **device**
named `rm` in subcircuit `#x1`.

## What changed

As Enhancement-410 did for instances, a whole-word match is consulted alongside that
grammar and can only add a match: the query, with or without the model marker `#`,
equal to the model's name with '.' standing for ':' (either way round, so `x1:x2:rm`
finds `x1.x2:rm`). It applies to model queries only — `show x1.rm`, an instance walk,
finds nothing as before — and needs a '.' or ':' in the query, so a bare `showmod rm`
keeps its top-level meaning.

## Verification

| check | result |
|---|---|
| `showmod x1.x2.rm`, `x1:x2:rm`, `x1.x2:rm` | the model `x1.x2:rm`, r = 2000 |
| `showmod x1.cm`, `x1:cm` | the capacitor model `x1:cm` |
| `showmod x1.x2.rm : r` | the one parameter |
| `altermod x1.x2.rm r=3k`, then `showmod x1:x2:rm : r` | 3000; v(out) follows (0.25) |
| `show x1.x2.rm`; `showmod rm`; `showmod x1.x2.r1` | nothing; nothing; the model through the instance — unchanged |
| an OSDI model inside a subcircuit, `showmod x1.om` and `x1:om : r` | found |

Full sweep 502 of 502 on both solvers.
