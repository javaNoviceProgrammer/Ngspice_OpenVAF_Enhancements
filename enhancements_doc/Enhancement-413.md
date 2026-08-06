# Enhancement-413 — the current waveform that was registered and never filled

`.options savecurrents` on a four-terminal compact model produced this:

```
@nd1[i]   : current, real, 0 long
```

A vector that exists and holds nothing. No warning, no error. A built-in BJT in
the same deck, meanwhile, produced four filled waveforms — `@q1[ic]`,
`@q1[ie]`, `@q1[ib]`, `@q1[is]`.

## Why

`.options savecurrents` is expanded by `inp_savecurrents()`, a **textual
pre-pass over the deck**. It runs long before any `.osdi` is loaded, so it
cannot know a compact model's terminal names — it emits the same bare
`@dev[i]` that R, C and L use, and its own comment says so.

Enhancement-394 defines that bare `i` alias **only for two-terminal devices**
(where it is unambiguous). For anything wider, the save named a parameter that
does not exist, so the vector was registered and never written.

| device | before |
| --- | --- |
| built-in BJT (4 terminals) | `@q1[ib]`, `@q1[ic]`, `@q1[ie]`, `@q1[is]` — filled |
| OSDI, 2 terminals | `@nd1[i]` — filled |
| OSDI, 4 terminals | `@nd1[i]` — **0 long** |

## What was *not* wrong

The currents themselves. Read as scalars after an `op` they were always exact —
`i_d = 1.000e-3`, `i_g = 4.000e-3`, `i_b = 1.200e-2`, `i_s = -1.700e-2`,
summing to zero by KCL — and they scale correctly with the instance multiplier.
An explicit `.save @nd1[i_d]` always worked too, at every terminal count.

What was missing was the *waveform*, which is the one thing `savecurrents`
exists to provide.

## The fix: resolve the names later

The names cannot be known during a textual pre-pass, so the expansion moves to
where they can. `ft_getSaves()` runs at analysis start, with the circuit set up
and the descriptor available; a bare `@dev[i]` belonging to an OSDI instance
that does not define it is expanded there into one entry per terminal:

```
@nd1[i]  ->  @nd1[i_d]  @nd1[i_g]  @nd1[i_s]  @nd1[i_b]
```

A new `OSDIterminalNames()` (`osdi/osdiparam.c`) reports a device's terminal
names, or nothing if the instance is not OSDI.

**The two-terminal case is deliberately untouched.** `@dev[i]` is a real
parameter there, so it keeps working exactly as before — verified byte-identical
against the pre-413 binary. Built-in devices are not affected at all: the
expansion only fires when the name resolves to an OSDI instance whose terminal
count is not two.

## Verification

* **`examples/savecur_examples` 15/15**, and **7/15 on the pre-413 binary**.
* Four terminals now give four waveforms of equal length, and the saved values
  match the operating-point scalars exactly — `i_d = 0.001`, `i_g = 0.004`,
  `i_b = 0.012`, `i_s = -0.017`, summing to **0.000e+00**.
* A built-in BJT in the same deck still gets its own four; a two-terminal OSDI
  device still gets `@nd1[i]`; an explicit `.save @nd1[i_d]` is undisturbed.
* **Full regression 330/330.** The compiler is untouched.

## Found by

A bug hunt over OSDI. The tell was a vector reported as `0 long` — present in
the listing, empty in use — which is why `meas tran ... MAX @nd1[i_a]` had
quietly returned a scalar snapshot instead of a maximum over time.
