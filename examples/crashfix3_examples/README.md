# Crash-hardening round 3 (Enhancement-245)

Two crashes found by argument-fuzzing the `meas` and `altermod` commands — both in
**core (stock) ngspice** parsers (not a recent enhancement), both reproduce on the
shipped binary:

- **`meas`** (`frontend/com_measure2.c`) — `measure_parse_stdParams()` splits each
  token on `'='` with `strtok`. A token that is a lone `=` (a stray one, e.g.
  `meas ... find v(x) when v(x)=0.5 = y`) makes `strtok` return **NULL** for the
  name, which was then passed to `strcasecmp()` → NULL deref (SIGSEGV). Fixed by
  rejecting a NULL name as a clean syntax error.

- **`altermod`** (`frontend/spiceif.c`, `parmlookup`) — `altermod nm c`, where the
  second token is a bare device-type letter (`c`/`e`/`i`/…) or a digit, makes
  `com_altermod` treat it as another model to alter with no `param=value`, so
  `parmlookup()` is called with a **NULL** `param`. The model-parameter loop passed
  it straight to `eq()`/`strcmp()` (the instance-parameter loop above already
  guarded `!param`) → NULL deref (SIGSEGV). Fixed by guarding the model loop against
  a NULL `param` (and a NULL keyword).

`verify_crashfix3.py` drives each repro and asserts it now exits gracefully (no
signal), while valid `meas` / `alter` / `altermod` still work — under both solvers.

```
python3 verify_crashfix3.py
```
