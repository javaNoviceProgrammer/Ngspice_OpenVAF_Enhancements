# arrayscale_examples — negative zero through the constant folder, and compile time linear in an array's length

(Section [5], nine checks, is Enhancement-713's — the robustness campaign's F7, see the end of this page.)

Two findings of the 2026-09-07 compiler hunt
([write-up](../../docs/bug_hunts/2026-09-07_openvaf-r-language-semantics.md), F3 and
F4), fixed by Enhancement-579. Run `python3 verify_arrayscale.py`; 29 checks. The suite
compiles two 10,000-entry arrays, so it takes about 20 s.

| check | what it pins |
|---|---|
| [1] F3 | `1.0/(-0.0)` as a parameter default, `1.0/(0.0 * -1.0)`, an inline `1.0/(-0.0)` and `atan2(0.0, -0.0)` fold to −inf, −inf, −inf and π, the values the run-time path always gave; the MIR constant table no longer aliases −0.0 onto +0.0 |
| [2] F4, shapes | a 2,000-entry array parameter read by a dynamic index compiles to a one-block model setup and a one-block evaluation function (one `select` per element, no `if` diamonds); a 2,000-element local array written in a loop leaves only the loop's blocks; the OSDI access function is 72 IR lines and the given-query function 59, and both are the same size for a two-parameter module (table-driven, not a switch with a case per parameter) |
| [3] F4, wall clock | a 10,000-entry model array parameter compiles in under 30 s (was 72 s), a 10,000-entry instance array parameter in under 40 s (was 375 s), and four times the elements cost under twelve times the time (it was sixteen) |
| [4] semantics | a 2,000-entry model array and a 1,500-entry instance array with per-element overrides on the model card and the instance line, `$param_given` per element, a dependent default following its model-card value, a bounded instance parameter (the `if`-diamond path that remains), a dynamic write landing on the indexed element only, an out-of-range dynamic read yielding element 0 (Enhancement-489), `alter` of an instance-array element and `altermod` of a model-array element, and a `select` feeding a contribution whose AC conductance is the selected element |

The wall-clock bounds are generous on purpose: the point is the shape, which [2]
pins exactly. What stays superlinear is LLVM's own work on a 10,000-phi loop when a
local array of that size is rewritten on every evaluation (26 s, from 68 s), which is
the evaluation function and cannot be compiled at a lower level.

## [5] Enhancement-713 — F7 of the 2026-09-23 robustness campaign

The campaign's F7 table ("compile time grows quadratically with the size of a table,
array or coefficient list") turned out to be five separate quadratic walks, fixed by
[Enhancement-713](../../enhancements_doc/Enhancement-713.md); 38 checks in all now.

| check | what it pins |
|---|---|
| array literal | a 20 000-element `localparam` array literal compiles in under 8 s (0.8 s; 15.5 s before: every element re-flattened the whole literal in the front end) |
| given flags | the descriptor's `given_flag_model` and `given_flag_instance` are under 40 IR lines for 2 000 parameters (31 and 18) and the same size for a two-parameter module — a bitfield read, where a `switch` with a case per parameter was 79 000 lines for 10 000 |
| noise table | a 2 000-pair `noise_table` loads through a loop of under 80 IR lines (44) and the same size as a five-pair table — the table is data, the search a loop, where a chain of selects took LLVM's instruction combiner a minute at 5 000 pairs |
| cross events | 300 `@(cross)` events leave at most three blocks per event in the evaluation MIR (601; ten per event before) and compile in under 10 s (0.3 s; 17 s before in LLVM's list scheduler on the one giant block — the eval is emitted through the fast instruction selector above 12 288 SelectionDAG nodes) |
| variables | 50 000 real variables compile in under 20 s (2.7 s; 47 s before: a linear scan of the item map per lookup and a re-walk of the declaration's attributes per variable) |
| loop fill | the 10 000-element array filled in a loop compiles in under 40 s (10.5 s; 25 s before) — the "cannot be compiled at a lower level" of the paragraph above is answered by emitting the giant-block eval through the fast instruction selector after its middle-end passes ran at -O3 |

```
OPENVAF_BIN=/path/to/E-712/openvaf-r python3 verify_arrayscale.py   # 32/38, exit 1
```

