# sweepbounds_examples — Enhancement-270

The `sweep` command now **validates its numeric bounds**. Its
`<start> <stop> <step>` (and `lin|dec|oct <N> <start> <stop>`) parser read each
bound with `sw_num`, which silently returns `0` for a non-numeric token
(`ft_numparse` fails → `atof("x") == 0`). An ASan/UBSan fuzz of the command turned
up two consequences:

- a typo'd bound became a `0` endpoint, so `sweep r1 1k xk 1k` became a `1k → 0`
  range and ran the sanity-capped **100000 analyses** — a minutes-long apparent hang;
- an overflowing bound (`1e400 → inf`) fed the point-count `(int) floor(...)` cast →
  **undefined behaviour** (`inf` outside `int` range), flagged by UBSan;
- an absurd count with *finite* bounds — a tiny step (`1n 1u 1e-30`), a huge
  `lin <N>` (a multi-GB `TMALLOC`), or a tiny `dec`/`oct` spacing — also ran away.

Fix (`src/frontend/com_sweep.c`): `sw_isfinitenum` requires each bound to be a
finite number (rejecting non-numeric tokens *and* inf/NaN), the point count is
bounded **before** the `(int)` cast, and a requested count above `SW_MAXPTS` is now
a clean `sweep: too many points …` error rather than a silent clamp-and-run. A bad
bound now errors quickly instead of hanging or tripping UB; valid sweeps are
unchanged.

## Verify

```
python3 verify_sweepbounds.py
```

Six checks: an overflow bound (`1e400`), a non-numeric bound, a typo'd suffix
(`xk`), and a non-numeric `dec <N>` all error quickly (no hang, no UB); and valid
`1k 3k 1k` / `lin 3 1k 3k` sweeps still produce the correct points.
