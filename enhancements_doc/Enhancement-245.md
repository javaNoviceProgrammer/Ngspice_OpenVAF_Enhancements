# Enhancement-245 — crash-hardening round 3: `meas` + `altermod` parsers

Two crashes found by argument-fuzzing the `meas` and `altermod` commands. Unlike
E-244 (which hardened recently-added code), both of these live in **core (stock)
ngspice** command parsers; both reproduce on the shipped binary.

## 1. `meas` — stray `=` → NULL deref

`measure_parse_stdParams()` (in `com_measure2.c`) parses each trailing parameter
token by splitting on `'='`:

```c
pName  = strtok(p, "=");
pValue = strtok(NULL, "=");
if (pValue == NULL) {
    if (strcasecmp(pName, "LAST") == 0) {   /* pName may be NULL here */
```

When a token is a **lone `=`** (the whole string is the delimiter), `strtok`
returns `NULL` for `pName`. The code guarded `pValue == NULL` but then dereferenced
`pName` in `strcasecmp()` → NULL deref (SIGSEGV):

```
meas tran m1 find v(out) when v(out)=0.5 = x      -> SIGSEGV
meas ac   m2 find vdb(out) when vp(out)=-45 = val= -> SIGSEGV
```

Only the interactive `meas` command hits it (the `.meas` dot-card takes a different
pre-tokenizing path). `key=val`, `=val` and `val=` tokens are all fine — only a
*standalone* `=` produces the NULL.

**Fix:** treat a NULL `pName` (empty / all-`=` token) as a clean syntax error
before `strcasecmp()`.

## 2. `altermod` — NULL model parameter → NULL deref

`altermod nm c`, where the second token is a bare **device-type letter** (`c`, `e`,
`i`, …) or a **digit**, makes `com_altermod` treat that token as another *model* to
alter — with no `param=value` following. So `parmlookup()` (in `spiceif.c`) is
called with `param == NULL`. Its model-parameter loop passed that straight to
`eq()` / `strcmp()`:

```c
if (dev->numModelParms)
    for (i = 0; i < *(dev->numModelParms); i++)
        if (... && eq(dev->modelParms[i].keyword, param))   /* param == NULL */
```

→ `strcmp(keyword, NULL)` → NULL deref (SIGSEGV). The *instance*-parameter loop just
above already guarded `!param` (returning the principal parameter or skipping); the
model loop did not. Only tokens that resolve to a real device type crash (`c`, `e`,
`i`, `0`, `1`, `2` …); tokens that resolve to nothing (`x`, `zz`, …) are dropped
earlier, which is why the bug is input-dependent.

**Fix:** guard the model-parameter loop against a NULL `param` (and, defensively, a
NULL keyword), matching the instance loop.

## Verification

`examples/crashfix3_examples/verify_crashfix3.py` (12 checks, both solvers): the
stray-`=` `meas` forms and the `altermod nm <c|e|i|0|1|2>` forms exit gracefully
(no signal); a valid `max` measurement, `altermod nm vto=0.7`, and `alter R1=2k`
still work.

## Scope

ngspice only — two command-argument parsers (`com_measure2.c`, `spiceif.c`). No
solver, analysis, or numerical change; valid usage is unaffected. Full regression:
202/202.
