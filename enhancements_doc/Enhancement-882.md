# Enhancement-882: `ordfix` and `reltol` say when a value has no reading — ordfix=-1 and ordfix=100 were taken without a word, and so was reltol=10

**Scope:** D2 of the
[transient stress campaign of 2026-10-12](../docs/bug_hunts/2026-10-12_transient-sparse-klu-stress-campaign.md).

ngspice:
- `spicelib/analysis/cktsopt.c`, `CKTsetOpt`: `OPT_ORDFIX` refuses a negative value and caps one
  above 6, with a warning; `OPT_RELTOL` refuses 1 and more.
- `spicelib/analysis/dctran.c`: a note when `ordfix` is above the order the method and `maxord`
  allow.

`examples/transopts_examples/` (new, shared with [E-881](Enhancement-881.md) and
[E-883](Enhancement-883.md)). **ngspice only.**

**Suites:**
- [`transopts_examples`](../examples/transopts_examples/): [3], [4], [5] and [7] are this
  enhancement's, 7 of 7 per solver. On the E-875 binaries [3] to [5] fail; [7] is a control.
- `inputguard` (107 of 107) and `corenum` pass.
- The full sweep: 585 of 585.

## What was wrong

- **`ordfix`** ([Enhancement-181](Enhancement-181.md)) pins the integration order: 0 is off, 1 to
  6 an order. `ordfix=-1` was taken as off. `ordfix=7`, `100` and `1e9` were cut to the order
  ceiling. Neither said anything.
- **The ceiling** ([Enhancement-853](Enhancement-853.md)) is `maxord`, or 2 under trap. So
  `method=gear ordfix=4` at the default `maxord=2` ran at order 2, also without a word.
- **`reltol`:** `reltol=1` and `reltol=10` were taken. A relative tolerance of 100 % or more has no
  reading. [Enhancement-426](Enhancement-426.md) refused only `reltol <= 0`.

## The change

- `ordfix` below 0 is refused. Above 6 it is set to 6, as `maxord` is:

  ```
  Warning -- Option ordfix = 7 is above 6, the highest integration order; 6 is used
  ```

- At the start of a transient, an `ordfix` above the ceiling says so:

  ```
  Note: ordfix=4 is above the highest order allowed here (2, from maxord); the order is pinned at 2.
  ```

- `reltol` of 1 or more is refused and the run keeps its value:

  ```
  Warning -- Option reltol = 10 must be less than 1; ignored, keeping 0.001
  ```

  `reltol <= 0` keeps its "must be greater than zero".

## The checks

`transopts_examples`:
- **[3]** `ordfix=-1` is refused; `ordfix=7` and `ordfix=1e9` warn that 6 is used.
- **[4]** `reltol=1` and `reltol=10` are refused, and the run is the default run.
- **[5]** Gear with `ordfix=4` at the default `maxord=2` says the order is pinned at 2; at
  `maxord=4` it says nothing.
- **[7]** (control) `reltol=0` is refused as "must be greater than zero", as before.


**Update ([E-888](Enhancement-888.md)).** Every `ordfix` run now prints a note of its own, so
[5]'s "at `maxord=4` it says nothing" reads: no note that the order is pinned at a ceiling. The
check looks for E-882's note by its text.
