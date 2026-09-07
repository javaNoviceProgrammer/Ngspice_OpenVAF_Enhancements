# arrayscale_examples — negative zero through the constant folder, and compile time linear in an array's length

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
