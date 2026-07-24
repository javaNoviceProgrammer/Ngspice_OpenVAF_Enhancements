# Enhancement-321 — `.param` fast-sweep, subcircuit tier

Enhancement-320 gave the `sweep` command a fast path that re-evaluates a swept
`.param`'s dependent device values and pushes them into the live circuit in
place, skipping the full per-point `reset`. It was limited to **top-level**
device/model values: a param feeding a device *inside a subcircuit* disarmed and
fell back to reset, because numparam freezes each `{expr}` into a literal during
subcircuit flattening and the pre-substitution text was thought lost.

E-321 lifts that limit.

## Recovering the frozen expression

The expression is *not* lost. A flattened instance card — `r.x1.r1 in out 1e3` —
carries `card->linenum` pointing back to its subcircuit-**definition** body line
(`R1 a b {rval}`). That definition line is a top-level template, so numparam
retains its original text, `{rval}` intact, in `dicoS->dynrefptr[linenum]`. Two
instances of the same subcircuit share the same `linenum`, so one template
serves all of them.

So the capture now walks the **flattened** deck (`ci_deck`): for each device
card, `nupa_get_dynref(card->linenum)` gives the original expression, and the
card's own first token is the full hierarchical instance name
(`r.x1.r1`). Top-level and subcircuit-internal instances are captured by the
exact same mechanism — no hierarchical-name reconstruction. (Confirmed empirically:
the key is `card->linenum`, not `card->linenum_orig`, which uses a different
counter and is off by one.)

## Staying correct across subcircuit scope

A subcircuit can locally **shadow** a swept global (`.param rval=500` inside the
body), **derive** from it, or receive it **passed through a formal parameter**
(`X1 … res P={rval}`). Re-evaluating the captured expression against the *global*
dico would then compute the wrong value. Three guards make the path safe:

1. **Structural / pass-through disarms** (scan of the original deck, now
   including subcircuit bodies): a swept param in a subckt header default, a
   subckt-call (`X`) argument, a subckt-body `.param` that shadows (swept LHS) or
   derives from (swept RHS) a swept name, or any structural slot (node/name,
   `.if`, `.temp`, analysis card, `.option`, `.ic`, `.nodeset`) disarms.
2. **Arm-time self-check** (the backstop): each captured expression is
   re-evaluated against the global dico at the nominal param values and **must
   reproduce the value numparam already baked into the flattened card**. Any
   mismatch — a shadow or pass-through that slipped past guard 1 — disarms the
   whole path. The baked value is read straight off the flattened card, so no
   device-ask API is involved.
3. A disarm always falls back to the exact reset path, so results are unchanged.

## Verification

A 10-deck safety battery (5 that must arm, 5 that must disarm — top-level,
direct subckt use, multi-instance, nested subckt, scaled expression; vs local
`.param` shadow, formal-param shadow, formal pass-through, subckt-local derived,
top-level derived) confirms **every deck's fast-path output equals the reset
path bit-for-bit**, and the arm/disarm decision matches expectation in all ten.
The subcircuit fast path also matches the closed-form divider `R2/(rval+R2)` to
`9e-10` and the reset path to `1.9e-9` (numparam value-string formatting only).

## Measured speedup

| Case | reset | fast | speedup |
|------|------:|-----:|--------:|
| param feeds one device in a subckt, in a large circuit | 2.92 s | 0.24 s | **12.0×** |
| param feeds every device (400 subckt instances × 8 R) | 2.50 s | 1.64 s | 1.5× |

As with E-320, the win scales with how narrowly the parameter fans out.

## Scope

The `sweep` command; subcircuit-internal **instance** values take the fast direct
set, model values use the textual `altermod` fallback. The optimizer /
Monte-Carlo `.param` reset sites remain on the reset path (future work).

## Files

- `ngspice-46/src/frontend/com_sweep.c` — three-pass build (disarm-scan the
  original deck, capture from the flattened deck via `dynref`, self-check each
  bind), plus the self-check machinery.
- `ngspice-46/src/frontend/numparam/{spicenum.c,numpaif.h}` — `nupa_get_dynref`
  (original text of a deck line, by line number).
- `examples/paramfastsweep_examples/` — top-level arm, subckt-internal arm, and
  local-shadow fallback, all vs closed form (`verify_paramfastsweep.py`).
