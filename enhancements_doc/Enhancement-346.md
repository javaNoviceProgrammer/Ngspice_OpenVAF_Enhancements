# Enhancement-346 — random draws on the fast `.param` path, and the Monte Carlo tier

Enhancement-320 recorded Monte Carlo as the one tier that could not join the fast
`.param` path, on the grounds that it "needs a re-draw of process variation, not
a deterministic value push — a different mechanism." Investigating that turned up
something else first.

**The fast path was already getting random draws wrong.**

---

## The bug

The fast `.param` sweep only re-evaluates brace expressions that **mention the
swept name**. That is fine for deterministic values. It is not fine once numparam
gets involved, because a `.param`'s expression is **inlined into the device line**
during preprocessing:

```
.param rv = agauss(1000, 300, 3)      source deck
R2 a b {rv}
                                       ->  what the fast path actually sees:
NUPA_CAT[9]='B' ref=r2 a b {(agauss(1000,300,3))}
```

There is no `.param rv` line left — which also means `nupa_recompute_params()`,
added in E-320 to "refresh the derived-param closure," replayed **zero lines** on
such a deck. And the device line now carries the random call but *not* the swept
name, so pass 2 skipped it and its value was never touched again.

Measured on a 5-point sweep, backing the resistance out of the node voltage:

| | per-point value of `rv` |
|---|---|
| reset path | 1097.7, 1015.2, 952.5, 988.7, 969.2 |
| fast path | **1161.1, 1161.1, 1161.1, 1161.1, 1161.1** |

Frozen. E-320's guarantee — "results never change, only speed" — did not hold for
any deck with a random `.param`, and had not since it shipped.

## The fix, and why it also *is* the Monte Carlo tier

Capture brace expressions that draw from the RNG (`agauss`, `gauss`, `unif`,
`aunif`, `limit`, `mvnorm`) even when no swept name appears in them, and
re-evaluate them per point. Once that exists, Monte Carlo needs nothing further:
a sample is a re-draw plus an in-place push, and `montecarlo` arms the same
machinery with **no swept knob at all** (`sw_fp_build(NULL, 0)`).

Being *bit-identical* to the reset path rests on consuming the RNG stream exactly
as re-sourcing did. Three things were needed, and each was found by a test that
failed first:

1. **Deck order.** Binds are otherwise sorted by expression text so each distinct
   one is evaluated once. Random binds sort ahead of the rest, ordered by capture
   index. Only they consume the RNG, so evaluating exactly those in deck order
   reproduces the stream regardless of how the deterministic ones are grouped.

2. **No caching.** A random bind is never served from the by-expression-text
   cache. Two devices carrying identical text must draw **independently** —
   verified directly: two `{agauss(1000,300,3)}` resistors come out at 1113.1 and
   1099.5 on the reset path, not equal.

3. **The sample boundary.** A deck re-copy signals one Monte Carlo sample via
   `nupa_signal(NUPADECKCOPY)` → `mc_sample_advance()`, which rewinds the
   per-sample dimension counter and steps the Latin-Hypercube sampler to its next
   stratified point. Skipping the re-source skipped that signal. This is why
   plain random draws matched the reset path exactly while `-lhs` did not:

   | | fast | reset |
   |---|---|---|
   | plain | 240/400 | 240/400 |
   | `-warm` | 240/400 | 240/400 |
   | `-lhs` | **239/400** | 258/400 |
   | `-lhs -warm` | **252/400** | 258/400 |

   Raising the same boundary in the apply path fixed it: all four now agree.

The arm-time self-check (E-321) is skipped for random binds — re-evaluating one
draws a *new* value, so it could never reproduce the baked one, and the draw
would perturb the very stream that has to match. Their safety rests on the
structural disarms instead, which were extended so that a random gets the same
scrutiny a swept name gets: a random reaching a `.temp`, a subcircuit call or any
other structural slot disarms the whole path.

---

## Verification

**Against an independent oracle, not a golden number.** The same experiment
written by hand in the control language as a `reset` loop — the path being
replaced — with the same seed:

```
montecarlo 200 ... -seed 7   ->  124 / 200 pass
hand-rolled reset loop       ->  ORACLE 124
```

**Battery, 12 cases**, each run on both paths and compared, with discriminating
yields (60.3%, 57.7%, 27.7%, 84.0%, 89.7%, 90.8% …): plain, `-lhs`, `-warm`,
`gauss`, `aunif`, `limit`, two independent randoms, the same expression text
twice, a random model parameter, two specs, a derived random `.param` (correctly
disarms), and a random in a structural slot (correctly disarms). **All 12
identical.**

**The `.param` sweep**, which is where the bug lived: bit-identical to the reset
path including the exact RNG sequence — `1097.7, 1015.2, 952.5, 988.7, 969.2` on
both.

**The Monte Carlo family of examples** — `warmstart` (5/5, including the `-lhs`
composition check that caught defect 3 above), `yield`, `dcenter`, `lhs`,
`highsigma`, `wcd` — all pass, as do `paramfastsweep`, `modelparamset`,
`optimize` (43/43) and `sweepscale`.

**Speed.** 1.8× at 20 devices, 2.3× at 200, 2.4× at 1000, over 200–400 samples.
Smaller than the sweep tiers, because an MC sample re-draws and re-pushes *every*
random value rather than one knob — the saving is the re-source, not the pushes.

**Regression:** 278/278 OK.

**Example:** `examples/mcfastpath_examples/` — 7 checks.

---

## What this changes for existing decks

A sweep over a deck containing a random `.param` now re-draws it at every point,
where it previously stayed frozen. That is a **visible change in results** — and
it is the change that makes the fast path agree with the reset path again, which
is the behaviour the feature always promised.

With Monte Carlo done, every tier E-320 listed is on the fast path.
