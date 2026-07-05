# analogloop_examples — behavioral loops end-to-end (Enhancement-70)

Validates the **runtime loop statements** inside analog blocks — `for`,
`while`, `do`-`while`, `repeat(n)` — using the committed `openvaf-r` and
`ngspice-46`. The Enhancement-70 audit (14 probes) found the machinery
correct with **one diagnostic defect**, fixed: an analog operator inside
a loop *body* was rejected (correctly, per LRM 4.5.1) but reported as
"not allowed in **conditions**" — loops now have their own validation
context and the error names **loops**, cites LRM 4.5.1, and suggests
hoisting or `generate`.

Pinned as working (every value exact): all four loop statements, nesting,
loops over arrays, iterative algorithms (Newton `sqrt(16)` → exactly 4),
contributions accumulating inside loops, loops inside analog functions —
and **parameter-dependent trip counts that honor model-card overrides at
simulation time** (`n=25` → 25 mS), the precise complement of
Enhancement-67's generate restriction: *generated structure binds at
compile time; loop behavior binds at simulation time.*

## Run

```bash
python3 verify_analogloop.py    # 12 checks
```
