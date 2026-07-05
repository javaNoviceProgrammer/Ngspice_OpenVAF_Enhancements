# lrmcorner_examples — LRM-corner probe follow-up (Enhancement-59)

Demonstrates the four gaps found (and fixed) by a 16-corner probe battery
over never-exercised Verilog-A (LRM Annex C) constructs, plus a regression
pin for the 12 corners the battery validated as already correct — using the
committed `openvaf-r` and `ngspice-46`.

## What was broken

1. **Event OR lists** (`@(cross(...) or cross(...))`,
   `@(initial_step or timer(t))` — LRM 5.10.3): parse error at `or`.
2. **`$realtime`** (LRM 9.7.2): unknown system function.
3. **Net concatenation in port connections** (`u1({a,c})` — LRM 6.5): the
   whole `{a,c}` text was bound to *every* bit of the vectored port,
   surfacing as `expected value but found net reference`.
4. **Analog-function recursion**: a direct self-call produced the puzzling
   `expected a function but found variable 'fact'` (inside a function its
   own name resolves to the return variable); **mutual** recursion
   (`f1→f2→f1`) crashed the compiler with a stack overflow in the
   recursive inliner.

## What now works

- **`or` event lists**: new `OR_KW` keyword, looped event grammar, an
  `Event::Or` HIR variant, and a `bool_or` (select-based) fold of the
  members' fired flags at lowering — a raw `ior` instruction would ICE
  const-eval, which has no Bool arm for `ior`. Any mix of `initial_step`/
  `final_step` (with phase lists), `cross`, `above`, `timer` members.
- **`$realtime`**: lowered to the same `Abstime` parameter as `$abstime`
  (in the continuous-time analog context they are identical).
- **Port concat**: expanded bit-by-bit at elaboration — leftmost element =
  port msb (each side in its own declared `[msb:lsb]` order); an element
  naming a same-scope bus used whole contributes all of its bits; works
  positionally, named (`.p({b[1],b[0]})`), and nested through instance
  levels. A bit-count/width mismatch is a hard compile error.
- **Recursion**: direct self-calls and call-graph cycles are clean errors —
  `analog function 'f1' cannot call itself: recursion is not allowed`, the
  mutual case naming the full cycle (`info: call cycle: f1 -> f2 -> f1`).
  Legitimate diamond call chains are unaffected.

## Files

| file | purpose |
|---|---|
| `evlist_demo.va` | OR'd crossing pair + `initial_step or timer` counters |
| `realtime_demo.va` | accumulates `max\|$realtime − $abstime\|` (must be 0) |
| `pconcat_demo.va` | two concat forms, each a 1 kΩ path a→c |
| `lrmpin_demo.va` | self-checking bitmask pin of 8 validated corners (score 255) |
| `_pin_compile.va` | compile-only pins (gnd branch, ddx-flow, above-DC, laplace, int fn outputs) |
| `_rec_direct.va`, `_rec_mutual.va`, `_pc_bad.va` | negative tests (must fail cleanly) |

## Run

```bash
python3 verify_lrmcorner.py
```

9 checks: [1] the OR-list counter equals the **sum** of the single-event
counters and the mixed step/timer list fires exactly twice; [2]
`$realtime ≡ $abstime` through a transient; [3] port-concat op current is
exactly 2 V / 1.5 kΩ through both concat paths; [4] direct and mutual
recursion are clean errors; [5] a 2-net concat onto a 3-bit port is
rejected; [6] the corner-pin score is 255/255; [7] the compile-only pins
build.

Note: the pin's `$vt(300)` check uses a 1e-7 tolerance — the compiler's
internal `$vt` uses newer CODATA constants than the LRM-1998 values in the
shipped `constants.vams` (difference ≈ 3e-8). Not a defect.
