# Enhancement-272 — ngspice: `alter`/`sweep` no longer deref a NULL parameter for an m-named device

The ASan/UBSan command-parser fuzz that produced Enhancement-270/-271 also crashed on
`sweep mag(v(b)) 0 1k 5k 1k`. The root cause is in the `alter` machinery
(`com_alter_common`, `src/frontend/device.c`), reachable both directly and through the
`sweep` command's knob path.

## The bug

`com_alter_common` supports altering a device's **principal** value with no named
parameter — `alter r1 = 2k` — in which case the parsed `param` is `NULL`. Just before
applying the value it runs a binned-MOSFET guard:

```c
if ((dev[0] == 'm') && (eq(param, "w") || eq(param, "l")))
    if_set_binned_model(ft_curckt->ci_ckt, dev, param, dv);
```

`eq(a, b)` is `!strcmp(a, b)`. When the device name begins with `m` **and** `param` is
`NULL`, this evaluates `strcmp(NULL, "w")` and the process **SEGV-crashes** — on the
shipped build, not merely under a sanitizer. It is reached by:

- a direct `alter mfoo = 5` (any `m`-named target altered with no parameter), and
- the `sweep` command: `sw_run_cmd` synthesizes an `alter` call for the swept knob,
  and a knob with no bracketed parameter produces exactly this `NULL`-`param` call
  (the fuzz input `sweep mag(v(b)) 0 1k 5k 1k` takes `mag(v(b))` — which starts with
  `m` — as the knob).

## Fix

`src/frontend/device.c`: test `param` before dereferencing it —

```c
if (param && (dev[0] == 'm') && (eq(param, "w") || eq(param, "l")))
    if_set_binned_model(ft_curckt->ci_ckt, dev, param, dv);
```

A `NULL` `param` simply skips the bin check, which needs a `w`/`l` parameter anyway.
The change is purely additive: when `param` is non-`NULL` (every ordinary
`alter m1 w=2u`) the condition is identical to before, so valid MOS binning is
unaffected.

This is a pre-existing defect (the guard and the `NULL`-`param` parse both predate the
recent wildcard work, and the crashing inputs use no `@*` wildcard), surfaced by
fuzzing the `sweep`→`alter` path.

## Verification

`examples/alternull_examples/verify_alternull.py` (4 checks): `alter mfoo = 5` and the
`sweep mag(v(b)) …` fuzz input each error cleanly with no crash where they previously
SEGV'd; a valid principal-value `alter r1 = 2k` (with `param` NULL) still changes the
result (`i(v1)` −5e-4 → −3.33e-4); and the non-`NULL`-`param` m-device branch
(`alter mfoo w=2u`) stays crash-safe. Full dual-solver example regression passes.

## Scope

One source file (`src/frontend/device.c`), a one-line NULL guard. No change to any
valid `alter` or `sweep`.
