# Enhancement-386 — the sensitivity queries returned the previous query's value

```
print @r1[resistance]   ->  1.00000000000000e+03
print @r1[sens_cplx]    ->  1.00000000000000e+03      <- echoed, not computed
print @r1[i]            ->  5.00000000000000e-04
print @c1[sens_cplx]    ->  4.99999616295099e-04      <- echoed again
print @r1[p]            ->  2.50000000000000e-04
print @r2[sens_cplx]    ->  2.49999808147550e-04      <- and again
```

Every `*_QUEST_SENS_*` case in every device's ask handler had this shape:

```c
case RES_QUEST_SENS_CPLX:
    if (ckt->CKTsenInfo) {
        value->cValue.real = ...;
        value->cValue.imag = ...;
    }
    return(OK);
```

`ckt->CKTsenInfo` is set only by the SENS2 analysis, which is not compiled in, so
on any ordinary run the handler wrote **nothing** and still returned `OK`. The
caller then read whatever was already in its `IFvalue`.

## Why it looked like uninitialised memory

It was first seen as denormal garbage — `2.12736e-314`, `2.14522e-314` — that
changed between runs. That is the same defect wearing a disguise. In the frontend
the `IFvalue` is a **`static`** reused by every query:

```c
static IFvalue pv;
...
pv.iValue = ind;    /* only this field is set */
err = ft_sim->askInstanceQuest(ckt, dev, opt->id, &pv, NULL);
```

so a query that wrote nothing handed back the previous query's bytes. `sens_cplx`
is `IF_COMPLEX`, so a preceding *real* query leaves the imaginary half stale — a
`double` read of bytes that were never a `double`, which is exactly what a
denormal like `2.1e-314` is. Interleaving the queries makes it far plainer: the
answer is simply the last thing you asked for.

## Why the fix belongs in the handlers

Two other callers pass an **uninitialised stack `IFvalue`**:

* `dctrcurv.c` — asks a parameter's value and then **saves it as the nominal to
  restore after a `.dc` sweep**;
* `cktsens.c`'s `sens_getp` — feeds `sgen` the value it will later write back.

Both are latent today, because they only ask for parameters whose handlers do
write. They are the reason this is fixed in the handlers rather than in any one
caller: a contract of "returns OK, may not have written anything" cannot be made
safe downstream.

All 60 cases — 10 device types (`res`, `cap`, `ind`, mutual, `dio`, `bjt`,
`vccs`, `vcvs`, `cccs`, `ccvs`) × six queries (`sens_dc`, `sens_real`,
`sens_imag`, `sens_mag`, `sens_ph`, `sens_cplx`) — now initialise their output
before the `if`.

Zero is the answer the surrounding code had already chosen: the `MAG` and `PH`
cases explicitly set `value->rValue = 0` when the response magnitude is zero.

`doask` was hardened too (`memset` before use, with `pv.iValue` set afterwards
because it is an *input*), so the channel itself is deterministic for any handler
that ever fails to write.

## Scope, measured

A sweep over **every** parameter of seven device types, querying each one
immediately after a known sentinel value:

```
   pre-fix : 44 parameters returned the sentinel
   fixed   :  2
```

The two survivors are `@r1[r]` and `@r1[ac]` — genuine aliases of `resistance`
that really are 1000, which the sentinel cannot distinguish from an echo. The 42
that changed are exactly the six sensitivity queries across the seven devices in
the deck.

## Verification

`examples/senscplx_examples` — 8 checks.

```
   fixed:     8/8
   pre-fix:   6/8
```

The two pre-fix failures are the defect: 42 queries echoing the preceding value,
and three reads of the same `sens_cplx` inside one session disagreeing
(`0`, `2.72158766165376e-04`, `7.40704126656055e-05`).

One check deliberately passes on **both** binaries and is worth keeping anyway:
querying the sensitivity parameters *first*, with no preceding query, already
returned 0 because the static starts zeroed. That is the case that made the
defect easy to miss — a probe that asks only the suspect parameter sees nothing
wrong.

The four accept checks pass on both. They pin ordinary parameters
(`resistance`, `capacitance`, `inductance`, and `gain` on **both** a VCCS and a
VCVS — keyed by instance, since a name-keyed check silently kept only the last),
operating-point readbacks asserted **self-consistently** as `p = i²R` rather than
against a literal copied from a simpler deck, `sens`'s own numbers against the
analytic derivative, and `show all : all`, which walks every parameter of every
device through this same path.

Regression 309/309 → 310/310.
