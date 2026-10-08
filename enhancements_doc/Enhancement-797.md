# Enhancement-797: `.save @n1[opvar]` no longer warns — the deck is correct and the vector is recorded per point

**Scope:** D2 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `frontend/outitf.c`: the save probe in `beginPlot` says nothing when the ask of a resolved name
  fails because no operating point has been computed yet.

`examples/osdislips_examples/` (section [2], three checks); `savemiss_examples` [1] and
`scanfmt_examples` updated. **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 56 of 56 per solver (1 of the 3
in [2] fails on the E-795 binaries); `savemiss` 11 of 11 and `scanfmt` per solver; the full sweep,
538 of 538.

## What was wrong

```
.save @n1[iop] @n1[pw] v(1)
.tran 10u 1m
```

printed, at every load, one line per saved operating-point variable:

```
Warning: save '@n1[iop]': 'iop' has no value yet -- it is an operating-point variable and no analysis has computed one. It is recorded per point once an analysis runs.
```

The deck is correct. The vectors are recorded per point, and `.meas` and `print` read them. The
message described what was about to happen as though it were a problem. `beginPlot` checks a
saved `@dev[param]` by asking the device for it, and before the first analysis an opvar has no
value. E-418 turned the old "device has no parameter" into this sentence, and E-600 cut two lines
to one. A built-in device in the same state, `.save @r1[i]` or `@d1[id]`, never said anything.

## The change

When the name resolves and only the value is missing, the save is accepted silently. The two
warnings that mean something stay:

- "no such device, so this vector will stay empty";
- "device has no parameter 'x', so this vector will stay empty".

## The checks

osdislips [2]:

- `.save @n1[iop] @n1[pw]` before a `tran`: no warning;
- the vector is recorded, iop = v/1k at the sampled point;
- a parameter the device lacks and a device that does not exist still warn.

savemiss [1] (E-600's "one warning per item") and scanfmt's opvar save now check that nothing is
said.
