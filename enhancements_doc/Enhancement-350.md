# Enhancement-350 — a sweep puts its `.param` back when it finishes

```
.param rload = 3k
sweep rload lin 3 1k 5k  -analysis op -output v(out)
sweep rload lin 3 2k 10k -analysis op -output v(out)
reset
op            ->  v(out) = 0.909      (rload still 10k; the deck says 3k)
```

One sweep, and `reset` restored the parameter. Two, and it could not — the deck
itself had been rewritten.

---

## Two paths that disagreed about the state they leave behind

Sweeping a `.param` has two implementations, and Enhancement-320's guarantee is
that you cannot tell which one ran:

> the fast path ... keeps the guarantee that a sweep can only get faster, never
> change its result.

It held for the numbers. It did not hold for what was left behind afterwards.

- **The reset path** drives each point with `alterparam`, which edits the
  parameter **permanently**. A later `reset` re-sources that same deck, so it
  faithfully reproduces the last swept value.
- **The fast path** never touches the deck — it pushes values into the live
  circuit — so a later `reset` restored the deck's own value.

Same command, same netlist, different circuit afterwards, decided only by which
path happened to arm.

## Why the second sweep was the one that broke

Arming self-checks every captured expression against the value numparam baked
into the flattened card at nominal:

```c
v = nupa_eval_expr(b->expr, &ok);
if (fabs(v - b->flat_value) > 1e-6 * (fabs(b->flat_value) + 1e-30))
    goto disarm;
```

That check exists to catch a subckt-local shadow. But the first sweep left the
numparam dico holding its *last swept value* while the flattened card still
carried the nominal one, so on the next sweep the check could not pass for an
honest reason — and disarmed.

So the second sweep of a parameter silently fell back to the reset path. No
error, no banner; the `fast .param path armed` line simply stopped appearing.
And the reset path is the one that edits the deck permanently, which is why the
damage needed exactly two sweeps to show up.

Both symptoms are the same root cause: **the sweep never put the parameter back.**

## The fix

Capture each swept `.param`'s value before the first point, and restore it at
cleanup — deck text *and* numparam dico:

```c
for (j = 0; j < ndeck_fp; j++)
    sw_set_deck(deck_fp_names[j], deck_fp_nominal[j]);   /* the deck reset re-sources */
if (ft_curckt && ft_curckt->ci_dicos)
    nupa_set_dicoslist(ft_curckt->ci_dicos);
for (j = 0; j < ndeck_fp; j++)
    nupa_add_param(deck_fp_names[j], deck_fp_nominal[j]); /* what the NEXT sweep reads */
nupa_recompute_params(deck_fp_names, ndeck_fp);
```

Both halves are needed, and the first attempt shipped only the first one. With
the deck restored but the dico still dirty, the *second* sweep read the first
sweep's last value as its own "nominal" and dutifully restored **that** — so
`reset` gave 0.833 instead of 0.909. Better, and still wrong. The dico is what
the next sweep reads and what arming self-checks against, so leaving it stale
just moves the bug one sweep along.

The capture is all-or-nothing: if any swept name cannot be read back,
`ndeck_fp_nominal` is zeroed and nothing is restored, rather than putting some
parameters back and not others.

**Restoring is the direction that makes the two paths agree.** The alternative —
making the fast path permanent too — would have satisfied the letter of E-320's
invariant while leaving `reset` unable to undo a sweep and every repeat sweep
disarmed. It also matches how ngspice already treats a swept source in `.dc`,
which does not leave it parked at the last step.

## What deliberately did *not* change

The **live circuit** still holds the last swept point after the sweep, so a bare
`op` afterwards answers with that value. That was true of both paths before this
change and is unchanged by it; only the deck and the dico return to nominal, so
`reset` means something again. Making the live circuit revert as well is a wider
behavioural change than the defect warrants and is not part of this fix.

## Verification

| | |
|---|---|
| `reset` after 1 / 2 / 3 / mixed-spec sweeps | **0.75 every time** (was 0.909 from the 2nd on) |
| sweeps that arm the fast path | **3 of 3** (was 1 of 3) |
| derived param, subckt-internal value | restore exactly |
| 12 sweep batteries vs the shipped binary | **every printed number identical** |
| regression | 282/282 |

The numeric comparison spans plain/list/dec sweeps, repeated sweeps, derived
params, subckt-internal values, model params, Monte Carlo random draws (twice
over, to catch RNG-stream drift) and a two-knob family — 5–11 numbers compared
per case, none of them vacuous. Nothing a sweep computes moved.

`examples/sweeprestore_examples/` is a proven trigger, not decoration: on the
pre-fix binary **4 of its 5 checks fail**, and the one that passes is precisely
the invariant that must hold on both — that the swept values are unchanged.
