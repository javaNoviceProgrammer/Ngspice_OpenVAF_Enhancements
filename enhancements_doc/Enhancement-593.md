# Enhancement-593: a `.adapt`-listed node that `autoadapt` refuses is reported, and the refusal names the extra use

**Scope:** `src/spicelib/parser/inp2n.c` (the two candidate refusals in `INPadapt`,
a record of the third OSDI instance, and `adapt_extra_line`),
`examples/adaptlisted_examples/` (new, 8 checks per solver);
`examples/autoadapt_examples/` accepts the new wording. **ngspice only.** Finding
F3 of the 2026-09-09 dig.

**Suites:** [`adaptlisted_examples`](../examples/adaptlisted_examples/) 8 of 8 per
solver, both solvers; `autoadapt` 26 of 26, `adaptquiet` unchanged; full sweep 488
of 488.

## What was wrong

`.option autoadapt` splits a bus that exactly two OSDI ports share and nothing else
touches. When something else does touch it — a third OSDI port, or a resistor or
capacitor on the base token or on one of its **bits** (`c1 x[2] 0 1p`) — the bus is
left as written. Enhancement-463 reported that; Enhancement-466 then made the option
quiet by default and moved the per-node "did not qualify" notices behind `=debug`,
which is right for a deck with many shared buses of which only some are meant to be
adapted.

That quiet also covered a node the deck asked for **by name**. `.adapt x` with a
capacitor on `x[2]` printed nothing and ran unadapted (`v(x[0])` 0.94118 where the
split gives 0.94111 / 0.93935). E-467 reports a `.adapt` member that selects nothing,
but `x` did select a candidate — two OSDI ports — that the occurrence rule then
refused, and E-466's own principle ("a deck that asked for an adapter and did not get
one must not run on in silence") was not applied to it. And in `=debug` the refusal
was a count, "node 'x' occurs 3 times in the deck, not exactly twice", with no word
about which line the third use was on; for a bit-level touch that is the whole
question.

## What changed

- A candidate the deck listed in `.adapt` has its refusal reported under the quiet
  default, at Warning level: too many OSDI ports, or a use beyond the two ports. An
  unlisted node keeps E-466's silence; `=debug` reports as before.
- Both refusals say where. The third OSDI instance is recorded as it is met, so
  "bus node 'x' is used by more than two OSDI ports (n1, n2 and n3)". For the
  occurrence rule, `adapt_extra_line` finds the first line, outside the two ports,
  that names the bus or one of its bits in a node position — the same spellings the
  count already accepts, `x`, `x[2]` and KiCad's `x_2_` — and the message quotes it:

```
Warning: autoadapt: bus node 'x' is also used by `c1 x[2] 0 1p` (3 uses, not the two
         OSDI ports n1 and n2 alone); not adapted. An adapter needs the node on exactly
         those two lines -- move the other use to x_f or x_r after splitting by hand, or
         leave the node unadapted.
```

The count-only sentence remains for the case no line can be pointed at.

## Verification

| check | result |
|---|---|
| quiet, `.adapt x`, a capacitor on `x[2]` | the refusal quotes `c1 x[2] 0 1p` and names n1 and n2; the bus stays unsplit |
| quiet, `.adapt x`, a resistor on the base token | quotes `r9 x 0 1k` |
| quiet, `.adapt x`, a third OSDI port | "more than two OSDI ports (n1, n2 and n3)" |
| quiet, no `.adapt`, the capacitor | silent, as E-466 documents |
| `=debug`, no `.adapt`, the capacitor | the refusal quotes the line |
| `.adapt x` with nothing in the way | adapted, no refusal |
| `.adapt x, y` with `y` blocked | `x` split, `y`'s refusal quotes its capacitor, nothing about `x` |
