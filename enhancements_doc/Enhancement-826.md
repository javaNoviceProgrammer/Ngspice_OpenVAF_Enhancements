# Enhancement-826: `alter` of a binned instance's size moves it to the bin that covers the size, and refuses a size no bin covers

**Scope:** F10 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md),
with the built-in case found while fixing it.

ngspice:
- `frontend/device.c`: `alter <dev> l=`/`w=` re-bins any instance on a bin, not only an
  m-device, and does not apply a size no bin covers.
- `frontend/spiceif.c`:
  - `if_instance_binned` says whether an instance's card is `<base>.<digits>`.
  - `if_setparam_model` returns whether a bin was found, and prints `INPgetModBin`'s message
    naming the bins.
- `include/ngspice/fteext.h` and the `main.c` stub: the new signature.

`examples/rebinfinal_examples/` (new; section [1], six checks). **ngspice only.**

**Suites:** [`rebinfinal_examples`](../examples/rebinfinal_examples/) 15 of 15 per solver (4 of
the 6 checks in [1] fail on the E-825 binaries; the other two are controls: a built-in move,
which worked, and a model that is not binned). The full sweep, 545 of 545.

## What was wrong

```spice
.model nch.1 bm g=1m lmin=0  lmax=1u  wmin=0 wmax=10u
.model nch.2 bm g=3m lmin=1u lmax=10u wmin=0 wmax=10u
n1 1 0 nch l=0.5u w=1u      ; bound to nch.1
alter n1 l=5u
op                          ; still 1 mA: nch.1's g; show n1 -> model nch.1, l 5e-06
```

The instance ran with `nch.1`'s parameters at a size only `nch.2` covers, and nothing said so.
ngspice has re-bound an instance on `alter w`/`alter l` since 2003 (`if_setparam_model`), but
only for a device whose name starts with `m`. An OSDI card set bins by `lmin`/`lmax` too
(Enhancement-495), and its instances never reached that code.

There was a second fault on the m-device path. When no bin covered the new size, it printed
"no model available for w= … l= …" and then applied the size anyway. A built-in BSIM4 instance
was left on `nch.2` with `l` = 50 µm, outside that bin's range.

## The change

- **Which instances.** `alter` re-bins an instance when the parameter is `l` or `w` and either
  the device is an m-device (as before) or its card is a bin (`<base>.<digits>`). The move is
  the existing one: the instance goes to the bin `INPgetModBin` picks for the new size, with
  the existing "Notice: model has changed from nch.1 to nch.2". A bin left with no instance is
  freed and made again when an instance needs it.
- **No bin.** `if_setparam_model` returns 1 when no bin covers the size, and prints the message
  `INPgetModBin` already had (Enhancement-600), which names the bins and the size asked for.
  `alter` then does not apply the value. It says so, and counts it for the `sweep` command
  (Enhancement-815).

## The checks

`rebinfinal_examples` [1], an OSDI card set with two bins and two instances:
- `alter n1 l=5u`: `n1` moves to `nch.2`, said so, i(v1) = −3 mA; `n2` stays on `nch.1` (was
  −1 mA, no word).
- `alter n1 l=50u`: refused with the bins named; `l` stays 5 µm and the current 3 mA (was
  applied).
- Back to 0.5 µm: `nch.1` again, −1 mA. Both instances to 5 µm: `nch.1` is left empty, and both
  read −3 mA.
- Built-in BSIM4 bins: `alter m1 l=5u` moves `m1` (control), and `alter m1 l=50u` is refused
  (was applied).
- A model that is not binned (control): `alter n1 l=5u` applies, with no notice.

## Limits

- Re-binning reads both `l` and `w` from the instance, as the parse does. A module whose bins
  key on `l` alone but which has no `w` parameter is not re-binned, as before.
