# alternull_examples — Enhancement-272

`com_alter_common` (`src/frontend/device.c`) crashed on `alter <m-device> = <value>`
and on the `sweep` knob path that synthesizes the same call. Altering a device's
**principal** value with no named parameter (`alter r1 = 2k`) leaves `param` NULL, but
a binned-MOSFET guard ran first:

```c
if ((dev[0] == 'm') && (eq(param, "w") || eq(param, "l"))) ...
```

`eq` is `!strcmp(...)`, so for an `m`-named device with a NULL `param` this evaluated
`strcmp(NULL, "w")` → **SEGV** (on the shipped build, not just under ASan). The
`sweep` command reached it too: `sweep mag(v(b)) 0 1k 5k 1k` takes `mag(v(b))` — which
starts with `m` — as the knob and alters it with no parameter.

Fix (`src/frontend/device.c`): guard `param` first — `param && (dev[0] == 'm') && …`.
A NULL `param` skips the bin check (which needs a `w`/`l` parameter anyway); the
non-NULL path is unchanged, so valid MOS binning still works.

## Verify

```
python3 verify_alternull.py
```

Four checks: `alter mfoo = 5` and `sweep mag(v(b)) 0 1k 5k 1k` each error cleanly with
no crash; a valid `alter r1 = 2k` still changes the result; and `alter mfoo w=2u`
(non-NULL param, m-device branch) stays crash-safe.
