# Enhancement-752: built-in PRBS and PAM4 sources — `PRBS(v1 v2 tbit [td [tr [tf [order [seed]]]]])` and `PAM4(v1 v2 tsym ...)` on the independent voltage and current sources, a Fibonacci shift register with the standard maximal-length taps (PRBS7 to PRBS31 as test equipment sends them, PRBS13Q and PRBS31Q Gray-coded as IEEE 802.3 defines them), corners scheduled as PULSE schedules its edges, the stream a pure function of time, refusals by name, `alter` re-reading the list and a per-run re-arm

**Scope:** a feature, asked for as "there is no built-in PRBS source", and
its four-level form asked for next ("if I need PAM4 do I cascade two prbs
sources?"). A new helper, `frontend/trannoise/prbs.c` with
`include/ngspice/prbs.h` (the register, the taps table, the level of a
symbol, the value and the next corner), and the two sources: `vsrc/` and
`isrc/` each gain the function in their type enum, the `prbs` and `pam4`
keywords in their parameter table, the parse case with its refusals, the
transient value, the breakpoint scheduling, the per-run re-arm and the free
on delete. Nothing else changes: PULSE, PWL, TRNOISE and TRRANDOM are
untouched, as is every analysis.

**Suites:** `prbs` 42 of 42 per solver (new; 1 of 27 on the E-751 binary, the
Python taps check); `guardspell` 54 of 54, `eye` 7 of 7, `trnoise` 6 of 6,
`inputguard` 100 of 100, `pwlfix`, `srcnote` 12 of 12 unchanged; the full
sweep 533 of 533.

## What was missing

Every serial-link deck in this repository builds its data pattern outside
ngspice: `examples/eye_examples/make_eye_fig.py` writes a PRBS as a PWL list
from Python, the coupled-channel example of the Touchstone work drives its
bus with PULSE trains, and a user wanting a PRBS31 at 10 Gb/s for a microsecond
would write ten thousand PWL points by hand or by script. The sources have
PULSE, SIN, EXP, PWL, SFFM, AM, TRNOISE and TRRANDOM, but no bit stream.

## What changed

```
Vtx tx 0 PRBS(0 1 100p 0 20p 20p 31)
Itx 0 rx PRBS(0 1m 100p)
Vp4 tx 0 PAM4(-0.6 0.6 100p 0 10p 10p 13)
```

| argument | meaning | default |
|---|---|---|
| `v1`, `v2` | the level of a 0 bit and of a 1 bit | required |
| `tbit` | the bit period | required |
| `td` | the delay before the first bit; `v1` is held until then | 0 |
| `tr`, `tf` | rise and fall time of a transition | the analysis's step, as PULSE |
| `order` | the register length n, 2..31; the stream repeats every 2^n − 1 bits | 7 |
| `seed` | the register's initial contents, nonzero in its low n bits | all ones |

The bits come from a Fibonacci linear-feedback shift register: the new bit
is the exclusive-or of the tapped positions, the register shifts, the new bit
is the output. The taps are the standard maximal-length ones, ITU-T O.150's
polynomials for the orders it names (x^7 + x^6 + 1, x^9 + x^5 + 1,
x^11 + x^9 + 1, x^15 + x^14 + 1, x^23 + x^18 + 1, x^31 + x^28 + 1), IEEE
802.3 clause 120's x^13 + x^12 + x^2 + x + 1 for 13, and Xilinx XAPP052's
for the other lengths, so PRBS7, PRBS9, PRBS11, PRBS15, PRBS23 and PRBS31
are the sequences a pattern generator sends, and every length 2..31 runs its
full period (the suite checks 2..20 in Python). Bit k occupies
`[td + k·tbit, td + (k+1)·tbit)`; a transition starts at the bit boundary and
takes `tr` or `tf`; a bit equal to its predecessor is flat. With the all-ones
seed PRBS7 starts with six zeros, its longest run.

**PAM4.** `PAM4(v1 v2 tsym [td [tr [tf [order [seed]]]]])` reads the same
register two bits per symbol and Gray-codes the pair, 00, 01, 11, 10 to the
levels `v1`, `v1 + (v2 − v1)/3`, `v1 + 2(v2 − v1)/3`, `v2`, the first bit the
most significant, as IEEE 802.3 clause 120 and OIF-CEI define PRBS13Q and
PRBS31Q. Order 13 is that clause's polynomial, so `PAM4(... 13)` is PRBS13Q:
8191 symbols per period (two bit periods, the bit period being odd) with
2047, 2048, 2048 and 2048 symbols on the four levels; `PAM4(... 31)` is
PRBS31Q. A transition between any two levels is linear over `tr` when it
rises and `tf` when it falls, whatever its size. Two PRBS sources in series
with weights of two thirds and one third still give a four-level signal, but
from two registers, which is not the standard pattern; the keyword exists so
that the standard one is one line.

**Corners are breakpoints.** The accept function schedules the next corner
of the stream, a transition's start or its end, the way PULSE schedules its
edges (the `CKTminBreak` bookkeeping included); a run of equal bits schedules
nothing, so the stepper is never stopped inside one. Every transition's start
and end is a time point of the run, and the edge is exactly linear.

**A pure function of time.** The value at a time is computed from the bit
index, not from a running state, so a rejected timestep costs nothing and two
runs give the same stream. The register after bit k is cached with a ring of
the last 64 bits for the stepper's backward moves; a move further back than
that restarts from the seed. Ten thousand bits of PRBS31 at 10 Gb/s run in
0.6 s.

**Per-run re-arm.** The register and the scheduled corner are reset in the
sources' temperature functions, beside E-498's re-arm of the PULSE break time,
so the setup-reuse fast path of a sweep gets a fresh stream too, and a
`resume` continues the old one. `alter @vtx[prbs] = [ ... ]` re-reads the
list and rebuilds the register, as TRRANDOM rebuilds its state.

**Refusals by name.** Fewer than three values, a bit time that is not
positive, a negative delay, a rise or fall time longer than the bit, an order
outside 2..31, a seed that is not a positive integer or whose low n bits are
zero: each is refused before anything is stored, naming the source, the value
and what was expected, on the voltage and on the current source alike.

**With a dc value.** `Vtx tx 0 dc 0.3 PRBS(0 1 1n)` serves 0.3 to the
operating point and starts the transient at `v1`, as PULSE does, and E-513's
note about the two disagreeing applies unchanged.

## Verification

`examples/prbs_examples/verify_prbs.py`, 42 checks per solver: the 254-bit
stream against a Python LFSR with the same taps on both source types, the
period, the count of ones and the longest runs; every corner a time point and
the edges linear; order 9's period, a seed as a rotation of the cycle, order
15 with negative levels, PRBS31 for ten thousand bits; omitted edges and the
delay; the dc value at the operating point; nine refusals; `alter` and two
identical runs; the taps table's full periods; a 2 Gb/s PRBS7 through an
RC channel giving E-207's `eye` an open eye; and PAM4: 16382 symbols of
PRBS13Q against the reference, the 8191-symbol period and its balance, the
level spacing at the symbol centres, a rising and a falling edge between
levels, the current source, PRBS31Q for 3000 symbols, three refusals in the
keyword's own words, and an `alter` from `prbs` to `pam4`. On the E-751
binary, which does not know either keyword, 1 of 27 passes.

## What this does not do

- No explicit bit pattern (`PAT`-style `0110...` strings) and no
  differential pair in one source: a second source with `v1`/`v2` swapped and
  the same seed is the complement.
- PAM4 only as the Gray-coded standard pattern: no binary-weighted mapping,
  no PAM8, no precoding, and no per-level rise time; a transition's time does
  not scale with its size.
- The seed is the register's contents, not a phase: to start a PRBS7 at bit
  k of its cycle, give the register that stands there.
- No jitter or amplitude noise on the stream; TRNOISE in series, or a
  `laplace` filter behind the source, adds either.
- The `.model`-line and `alter` spellings are the source's usual ones; there
  is no `show` of the decoded bits.
- The eye example's own figure script still writes its PWL; it is not
  rewritten to the new source.

**Update ([E-774](Enhancement-774.md)).** `prbs` and `pam4` had no answer in the sources' parameter query, so every source's device table printed both rows as `<<NAN, error = 7>>`, repeated by a row count read from an unset value -- three times on macOS, without end on aarch64 Linux, where it ran the CI runner out of memory. Both keywords answer now, only the active one with its description.
