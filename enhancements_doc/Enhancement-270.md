# Enhancement-270 — ngspice: `sweep` validates its numeric bounds (fixes a UB + a runaway)

An ASan/UBSan fuzz of ngspice's newest command parsers surfaced a bug in the
`sweep` command's specification parser (`sw_parse_spec`, `src/frontend/com_sweep.c`).

## The bug

`sweep` reads each bound of its `<start> <stop> <step>` (and
`lin|dec|oct <N> <start> <stop>`) form with `sw_num`, which parses a SPICE number
and **silently returns `0`** for a token it can't parse (`ft_numparse` fails →
`atof("x") == 0`). Nothing checked that the bounds were actually numbers, with two
consequences:

1. **Runaway sweep.** A typo'd bound became a `0` endpoint. `sweep r1 1k xk 1k`
   became a `1k → 0` range which, with a small step, generated the sanity-capped
   maximum of `SW_MAXPTS = 100000` points — 100000 analyses, a minutes-long
   apparent hang.
2. **Undefined behaviour.** An overflowing bound — `sweep r1 1k 1e400 1`, where
   `1e400` overflows a `double` to `inf` — flowed into the point-count expression
   `cnt = (int) floor((f1 - f0) / st + 1e-9) + 1`. Casting `inf` to `int` is
   undefined behaviour; UBSan reported *"inf is outside the range of representable
   values of type 'int'"* at `com_sweep.c:332`.
3. **Absurd point count.** Even with perfectly *finite* bounds, an absurd count
   ran away: a tiny step (`sweep r1 1n 1u 1e-30` → ~10²⁴ points) or a tiny
   `dec`/`oct` spacing was silently capped at `SW_MAXPTS` and run as 100000
   analyses, and a huge `lin <N>` (`sweep r1 lin 999999999 1k 5k`) skipped even
   the clamp and asked `TMALLOC` for a multi-gigabyte array. All present as a hang.

None reaches memory unsafety on the shipped build (the cast yields a garbage count
that the `SW_MAXPTS` clamp bounds), but the runaway hangs and the UB are all real
defects on malformed input.

## Fix

`src/frontend/com_sweep.c`:

- **`sw_isfinitenum(tok, &val)`** — parse a bound as a **finite** number: reject a
  non-numeric token (so a typo can't silently become `0`) *and* a non-finite value
  (`inf`/`NaN` from an overflowing literal). The `lin/dec/oct` and
  `start/stop/step` branches validate every bound through it and emit a clean
  `sweep: non-numeric …` / `sweep: … needs finite numeric …` error on failure.
- The `start/stop/step` point count is computed as a `double` and the
  `(int)` cast is guarded, so `inf`/`NaN` can never reach it.
- **An absurd point count is now rejected, not silently clamped.** A requested
  count above `SW_MAXPTS` (from a huge `lin <N>`, a tiny `dec`/`oct` spacing, or a
  tiny start/stop/step) yields a clean `sweep: too many points …` error rather than
  a 100000-analysis run or a multi-gigabyte allocation.

Valid sweeps are unaffected — a well-formed `<start> <stop> <step>`, `lin`/`dec`/
`oct`, or `list` sweep produces exactly the same points as before.

## Verification

`examples/sweepbounds_examples/verify_sweepbounds.py` (9 checks): an overflow bound
(`1e400`), a non-numeric bound, a typo'd suffix (`xk`), a non-numeric `dec <N>`, a
tiny step (`1n 1u 1e-30`), a huge `lin 999999999`, and a wide `dec` range all error
quickly (no hang, no UB, no runaway) where they previously hung or tripped UBSan;
and valid `1k 3k 1k` / `lin 3 1k 3k` sweeps still produce the correct points. Found
with an ASan/UBSan instrumented build fuzzing the sweep/alter/altermod/loadpull/
rfstab/stb/let/pyplot command parsers. Full dual-solver example regression passes.

## Scope

One source file (`src/frontend/com_sweep.c`). No change to any valid sweep result.
