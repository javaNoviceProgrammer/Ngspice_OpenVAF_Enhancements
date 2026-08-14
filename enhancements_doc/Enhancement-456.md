# Enhancement-456 — `analog initial` ran on every evaluation

LRM 5.2 is unambiguous:

> The analog initial block is executed **once for each analysis**, and can be
> executed for each sub-task of parameter sweep analysis (such as dc sweep).

It was instead lowered straight into the front of the eval function, concatenated
with the main analog block, so its statements re-ran on **every evaluation** and
overwrote whatever the model had accumulated between timesteps.

That destroyed the one thing the construct exists for.

## A peak detector that does not hold its peak

```verilog
real peak;
analog initial begin peak = 0.0; end
analog begin
    if (V(in) > peak) peak = V(in);
    V(out) <+ peak;
end
```

Driven with a ramp 0 → 1 → 0, this must hold 1.0 once the input has peaked. It
tracked the input **back down** instead:

| t | 2 µs | 5 µs | 8 µs | 9.5 µs |
|---|---|---|---|---|
| with `analog initial` | 0.4 | 1.0 | **0.4** | **0.1** |
| the same model without it | 0.4 | 1.0 | 1.0 | 1.0 |

A counter behaved the same way — with `analog initial cnt = 0;` it never left
zero; without it, it counted 1, 3, 6, 9. Nothing was reported either way. The
construct designed for one-time initialisation was the only thing that broke
state, and using it looked like the careful thing to do.

## The fix

The initial block is gated on `ParamKind::IsInitialStep` — the flag
`@(initial_step)` already uses. That was not a guess: the *same* models written
as `@(initial_step) peak = 0.0;` inside the main block always worked, so there
was a working reference for the target semantics inside the compiler, and the
fixed models reproduce its numbers exactly.

Measured, `IsInitialStep` fires **once per analysis per instance**: once for an
`op`, once for a whole `tran`, once for an entire `dc` sweep however many points
it has, twice for `op` then `dc`, and once per instance with two instances. That
is the LRM's baseline rule. (The LRM's follow-on clause — re-execution per
sub-task of a parameter sweep — is permissive, "*can* be executed", and its
mandatory half applies only when a parameter referenced by the block changes
during the sweep.)

Statements still lower in source order and still run before the main block, so
multiple `analog initial` blocks compose exactly as before (LRM 5.2: "executed as
if concatenated"). They are simply no longer re-applied afterwards.

The MIR shows the whole change:

```
block0:  br <is_initial_step>, block2, block3
block2:  <the initial block's statements>
block3:  (nothing)
block4:  v29 = phi [v23, block2], [v24, block3]      <- initialised, or retained
         <the main analog block>
```

The phi is the point: on the first evaluation the variable takes the initialised
value, on every later one it carries what the model last put there.

**The gate is emitted only when a module actually has an initial block.** Without
that guard every model picks up an `IsInitialStep` parameter and an empty
conditional it never asked for — which showed up immediately as a 32-byte change
in a MEXTRAM model that has no initial block at all.

## Verification

**`examples/analoginit_examples` — 10/10** under both solvers, and **6/10 on the
previous compiler**, where the four failures are exactly the defect.

The suite is built around `_ref` twins: each model appears once written with
`analog initial` and once with `@(initial_step)` in the main block. The fixed
models must **match the reference at every probe**, not merely "hold a peak
now" — a looser check would pass a model that held the wrong value.

* the peak detector holds 1.0 after the peak, matching its reference exactly
* the counter accumulates 1, 3, 6, 9, matching its reference exactly
* a value set once in the initial block still reaches the body (`x` = 5, and the
  body recomputes `y` = 2x every evaluation)
* two `analog initial` blocks still compose in source order to exactly 2 mS

**Corpus: 107 compiled by both, 17 rejected by both, 0 rc differences, 0 byte
differences** — measured against the pre-Enhancement-455 binary, so it covers
both enhancements together. No corpus model uses `analog initial`, and the
emptiness guard is what keeps those 107 byte-identical.

`cargo test` passes across 47 test binaries. The `mir/analog_initial.va`
snapshot was **intentionally updated**: it had captured the defect — the initial
block's statements computed unconditionally in `block0` — and now records the
branch, the empty else, and the phi. Full regression **370/370**, both solvers,
with `multianalog_examples` (which pins multiple-block ordering) and
`lrm_examples` unaffected.
