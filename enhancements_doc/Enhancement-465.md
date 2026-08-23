# Enhancement-465 — `sweep` stops tearing the circuit down for subcircuit params

`sweep` has two ways to move a `.param` knob. Enhancement-320's **fast path**
writes each point's values straight into the live circuit. The fallback stages
`alterparam` and issues a **`reset`**, which re-sources the whole deck once per
point.

| deck | reset path | fast path |
|---|---|---|
| 3000 elements, 201 points | 1.58 s | **0.50 s** |
| 800 subcircuit instances, 101 points | 0.54 s | **0.07 s** |

The gap widens with both deck size and point count, because the rebuild is
O(deck) per point.

## What used to fall off the fast path

Almost anything involving a subcircuit or a derived parameter — and **silently**:
there is a banner when the fast path arms and nothing at all when it does not.
One unused `.param b={rv*2}` anywhere in a deck was enough to turn a 0.50 s
sweep into 1.58 s with no indication why.

All of these now stay on it, each verified against an **analytic** value rather
than against the other code path — a divider `Rin=10` / `Rtop=R` reads `R/(R+10)`:

| case | effective R |
|---|---|
| a derived `.param` | 2·rv |
| a derived chain | 6·rv |
| passed on the X line | rv |
| two instances, different expressions | 0.8·rv |
| a nested X call | rv |
| a swept param in a `.subckt` header default | rv |
| a derived `.param` inside a subcircuit | 2·rv |
| a local shadow beside a real dependence | rv ‖ 2000 |

## How: resolve to global names once, not per point

The obstacle is that `X1 a 0 sub r={rv}` binds the local `r` **per instance**, so
the flattened devices `r.x1.r1` and `r.x2.r1` share one template — `{r}`, keyed
by source line — but need different values. A single global `nupa_eval_expr("r")`
cannot serve both.

So nothing is evaluated per instance at run time. Each captured expression is
rewritten **once, at build time**, into global names, by walking the instance's
scope chain outward exactly as numparam would: a subcircuit's own `.param`s
first (they may reference its formals), then the formals bound to that call's
actuals — or to the **header default** when the call omits them — then the
enclosing frame, and so on to the top level. `{r}` becomes `{(rv)}`; `{rl}` where
`.param rl={rv*2}` becomes `{((rv*2))}`. After that the ordinary global
evaluation is correct per bind and the point loop is untouched.

A local `.param` **shadowing** the swept name resolves to its own constant, which
is what makes the shadow case correct rather than merely refused.

**numparam has already rewritten the call.** By the time the original deck is
readable, `X1 a 0 sub r={rv}` has become the positional `x1 a 0 sub {rv}` — the
keyword is gone. The `.subckt` header therefore supplies the parameter *order*.
Enhancement-442 met the same rewrite from the other side, where it made a
subcircuit name unfindable by counting tokens.

Derived top-level `.param`s needed one more thing: the fast path matched device
lines against the swept names only, so a device carrying `{rd}` was never
captured. Matching now uses the transitive **closure** of names derived from the
swept ones. The values themselves were already refreshed — `nupa_recompute_params`
has done that since E-320 — so only the choice of which lines to capture was
missing.

## The other half: the reset path never put the knob back

Enhancement-385 closed this hole for the fast path and left it open for the
other. `alterparam` rewrites the **deck text**; on the fast path E-385 also
pushes the nominals into the live circuit, but on the reset path nothing
re-sourced the restored deck, so the devices kept the last point's values and
**every later analysis was quietly wrong**:

```
after `sweep rv 900 1100`, a fresh op read   v(a) = 0.99099099   @rtop = 1100
nominal rv = 1000 gives                      v(a) = 0.9900990099
```

The fix is a `reset` after the nominal `alterparam` — which the next comment in
that same function already assumed this path would do. The sweep's own results
are unaffected.

## What still falls back, deliberately

**Structural dot-cards** (`.if`, `.temp`, `.tran` referencing a swept param)
change the deck's shape or the analysis itself, which no amount of value
substitution can reproduce.

**An isolated local shadow** — a shadowed subcircuit with nothing else in the
deck depending on the sweep. It resolves correctly now, but with no device
depending on the knob there is nothing to push, and Enhancement-321 pinned that
fallback; reversing a pinned decision is a separate call. Pinned here as
still-falling-back so a future change has to be deliberate.

## Two name collisions, both hit while building this

The matching set grew from the swept names alone to the whole derived closure,
which widened the chance of a name meaning two things:

- a **device** called `Rd` lowercases to `rd` and collided with `.param rd`, so a
  line matched on its NAME and the capture scan then disarmed on a line carrying
  no value at all. Matching now skips the leading instance/model token;
- a deck **title** beginning with `X` was read as a subcircuit call, whose callee
  could not be found, disarming the whole sweep. The near-identical deck beside
  it passed only because its title began with "t". The first card is the title,
  not an element.

Both are pinned, as is a **node** named like a derived param.

## Verification

`examples/sweepsubfast_examples/verify_sweepsubfast.py` — **28/28**, both
solvers: the eight cases above against analytic values, the shadowed device held
at its own 2000, all three collisions, both deliberate fallbacks, and — on
**both** paths — that the sweep is still correct, `@rtop` is back at 1000, and a
later `op` uses the nominal rather than the last point.

Full regression **379/379**, both solvers. ngspice-only.
