# Enhancement-343 — `cp_getvar()` synthesized the whole user-variable list

Enhancement-341 recorded, with measurements, that a long `sweep` scales
quadratically in its own point count, and deliberately shipped without a fix
because the obvious one had been **measured to give no improvement**. This is
the fix, and the reason the first attempt failed is the whole lesson.

**26.6× at 16,000 points** — 39.55 s down to 1.49 s.

---

## The cost

`cp_getvar(name, ...)` looks up **one** name. Its first statement built **all
five** synthetic user variables, searched the result, and freed it again:

```c
bool cp_getvar(char *name, enum cp_types type, void *retval, size_t rsize)
{
    uv1 = cp_usrvars();                     /* $plots, $curplot, $curplot{title,name,date} */
    for (v = variables; v; v = v->va_next)  /* only now does it look at `name` */
```

Synthesizing `$plots` walks the live plot list and copies a string per plot
(`options.c:106`). So one `cp_getvar()` call costs O(number of plots in the
session) regardless of what it was asked for.

`beginPlot()` does two of those lookups per analysis — `printinfo` and
`interp` (`outitf.c:300`, `304`) — and a sweep creates a plot per point. Point
*k* pays O(*k*), so the sweep is O(N²).

---

## Why the first attempt failed

Enhancement-341 tried making the construction **lazy**: build `uv1` only after
the `variables` search misses. That is the natural reading of "don't do work you
might not need," and it measured **1.0×**.

The reason is specific. `printinfo` and `interp` are normally **unset**, so the
`variables` search *always* misses and falls through to needing `uv1` anyway.
Laziness only helps the lookups that were never the problem.

The gate has to be on **which name is being requested**, not on when the list
gets built. Neither hot lookup is one of the five synthetic names, so the right
answer is to build *nothing at all*:

```c
uv1 = cp_usrvar(name);   /* NULL unless `name` is one of the five */
```

`cp_usrvars()` (build all five) is kept for `cp_vprint()`, which genuinely
prints all of them and is called only by a bare `set`.

Gating is safe because every caller that uses it — `cp_getvar()` and
`cp_remvar()` — also searches `plot_cur->pl_env` and `ft_curckt->ci_vars`
separately, which is the only other thing `cp_enqvar()` could have returned. For
a name that *is* one of the five, `cp_usrvar()` returns exactly the node
`cp_usrvars()` would have contributed. The search order is unchanged.

Ownership follows Enhancement-342: the shared `usrvar_fetch()` helper still
copies a borrowed node rather than splicing it.

---

## Measured

Warm runs, best of two, same machine, `sweep pr lin N 1k 3k -analysis op`:

| points | before | after | speedup | after µs/point |
|---|---|---|---|---|
| 1,000 | 0.17 s | 0.02 s | **7.3×** | 23 |
| 2,000 | 0.64 s | 0.05 s | **13.0×** | 24 |
| 4,000 | 2.49 s | 0.13 s | **18.9×** | 33 |
| 8,000 | 9.81 s | 0.41 s | **24.1×** | 51 |
| 16,000 | 39.55 s | 1.49 s | **26.6×** | 93 |

The speedup grows with N, which is what removing a quadratic term looks like.

The regression suite — the same 274 examples, unchanged — ran in **479 s**
against **748 s** on the previous binary. That is a whole-suite effect, not a
sweep-only one, because every analysis in every example was paying two of these
lookups. (Same machine, otherwise idle; some of that spread is ordinary
variance.)

---

## What is left, and why it is not fixed here

**It is not linear yet.** Per-point cost still grows — 23, 24, 33, 51, 93 µs —
and the doubling ratios are 2.1×, 2.7×, 3.1×, 3.6× where flat would be 2.0×.

Profiling the *new* binary at 64,000 points puts 89% of the remaining time in a
completely different function:

```
4960 DCop
  4940 OUTpBeginPlot
    4496 plot_alloc          <- 89%
      1888 cieq
      1438 cieq -> __tolower
      1170 cieq -> __tolower
```

`plot_alloc()` picks a unique plot name by scanning the whole plot list with a
case-insensitive compare:

```c
do {
    (void) sprintf(buf, "%s%d", s, plot_num);
    for (tp = plot_list; tp; tp = tp->pl_next)
        if (cieq(tp->pl_typename, buf)) { plot_num++; break; }
} while (tp);
```

The successful iteration always traverses the entire list. That is a second,
independently-rooted O(N) per point.

Two ways to fix it were considered and **both rejected for this change**:

1. **An exact-membership index.** Correct, but `plot_list` is mutated in about
   nine places — `plot_new()` plus half a dozen open-coded head-prepends, and
   `killplot()` plus the `mw_coms.c` path for removal. An index that misses one
   insertion hands out a duplicate plot name, which corrupts a core data
   structure. Too many sites to be confident in, in a change whose point is a
   speedup.

2. **A cheaper superset index** (record names, never remove them). Contained and
   safe against duplicates — but it **changes observable behaviour**. Today
   `plot_num` never decreases while the list *can* shrink, so after
   `destroy all` the next plot reuses the current number: plots `op1`..`op5`,
   `destroy all`, next `op` is `op5` again. A superset index would skip to
   `op6`. Scripts that destroy and then reference a plot by name would break.

Both are real changes to plot lifetime rather than to this lookup path, so they
belong in their own enhancement with their own testing. The finding is recorded
here with its profile so the next person starts from the answer.

---

## Verification

**Semantics preserved, diffed rather than eyeballed.** Output of the old and new
binaries compared byte-for-byte across: all five synthetic variables read back,
`setplot`, `set`/`unset` round-trip, and a deck with `printinfo` and `interp`
explicitly **set** — the two hot lookups, exercised on their non-default path —
across `op`, `tran` and `ac`. Identical in every case.

**Enhancement-342 still holds.** Both of its vectors re-checked on this binary:
5/5 rawfile `Option:` names clean, 5/5 `unset` names clean.

**ASan.** Clean on the semantics deck, the `printinfo`/`interp` deck, and both
E-342 reproducers.

**Regression.** Full suite, 275/275 OK.

**Example.** `examples/sweepscale_examples/` — 5 checks, including a growth-rate
check across a 4× span in point count. It asserts a ratio at or below 2.5 rather
than flat scaling, because `plot_alloc()`'s residual O(N) is still there; the
old behaviour was ~3.8.
