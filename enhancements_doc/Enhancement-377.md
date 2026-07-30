# Enhancement-377 — OSDI diagnostics were unreadable and had no severity

Found by the correctness campaign over all 94 `$`-prefixed system functions. I
passed `$simparam$str("analysis")` when the supported name is `"analysis_name"` —
my mistake — and got this back:

```
OSDI(debug) n1: unknown $simparam_stranalysisOSDI(debug) n1: unknown $simparam_str…
```

Four separate defects in one line.

## 1. No separator between the function and its argument

`concat("unknown $simparam_str", name)` joins with nothing, so `$simparam_str` and
`analysis` read as `$simparam_stranalysis` — you cannot see where the function name
ends and the argument begins. The numeric `$simparam` path had the same bug.

Now: `unknown $simparam$str "analysis"`.

## 2. No newline

`osdi_log` writes with `fprintf(dst, "%s", msg)` and no message carried a `\n`, so
consecutive reports concatenated into one line.

This also **hid the repetition**. The old output looked like two lines; the fixed
one shows 373. The same 373 reports were always there.

## 3. Wrong severity — for every message in the OSDI layer

This is the one with reach beyond `$simparam`. ngspice's `osdi.h` had:

```c
#define LOG_LVL_MASK 8
```

The level occupies the low **three** bits (`DEBUG 0` … `FATAL 5`), so the mask must
be **7**. `8` selects bit 3, which no level ever sets, so `lvl & LOG_LVL_MASK` was
`0` — `LOG_LVL_DEBUG` — for *every* level:

| level | value | `& 7` | `& 8` |
| --- | --- | --- | --- |
| DEBUG | 0 | 0 | 0 |
| DISPLAY | 1 | 1 | **0** |
| INFO | 2 | 2 | **0** |
| WARN | 3 | 3 | **0** |
| ERR | 4 | 4 | **0** |
| FATAL | 5 | 5 | **0** |

So `$display`, `$info`, `$warning`, `$error` and every fatal diagnostic alike were
labelled `OSDI(debug)` and written to **stdout**. Severity was invisible to the
user and to any log scraping, and `$error`/`$warning` never reached stderr.

OpenVAF's own copy of the header (`openvaf/osdi/header/osdi_0_4.h`) has always
said `7`, so the two sides of the ABI disagreed on how to decode the level.

Measured before and after:

```
before:  OSDI(debug) n1: SEV_DISPLAY / SEV_INFO / SEV_WARN / SEV_ERR   (all stdout)
after:   OSDI n1: SEV_DISPLAY        OSDI(info) n1: SEV_INFO           (stdout)
         OSDI(warn) n1: SEV_WARN     OSDI(err)  n1: SEV_ERR            (stderr)
```

## 4. A leak

The message was `malloc`ed and passed to `osdi_log`, and never freed — `free` was
not even declared in the runtime's `NO_STD` extern block. At 373 reports per
failing operating point that is 373 leaked allocations, not one. Both call sites
now go through one helper that frees.

## What is deliberately not fixed

The report still repeats 373 times. That is ngspice retrying the failing operating
point — gmin stepping, then source stepping — and re-evaluating the device each
time. Suppressing it is a change to the convergence path, not to the diagnostic,
and is out of scope here. It is now at least *visible* as 373 lines rather than
hidden inside one.

## Verification

`examples/simparamdiag_examples` — 12 checks.

```
   fixed:     12/12
   pre-fix:    1/12
```

The single pre-fix pass is the check that the *glued* spelling is absent from the
`$simparam$str` form — which passes for the wrong reason on the old binary, since
the old message uses the internal `$simparam_str` spelling instead. Every check
that asserts something positive fails pre-fix.

Regression 301/301 → 302/302.
