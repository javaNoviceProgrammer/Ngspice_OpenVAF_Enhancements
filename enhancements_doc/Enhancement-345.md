# Enhancement-345 — naming a plot no longer walks the plot list

Enhancement-343 removed one quadratic term from a long `sweep` and recorded, with
a profile, that the remainder was somewhere else entirely:

> 89% of what is left is `plot_alloc()` scanning the plot list case-insensitively
> for a unique name.

That doc listed two ways to fix it and rejected both, for reasons that turned out
to be exactly right and are addressed below. This is the fix.

**The sweep is now linear.** 87× at 64,000 points — 54.97 s down to 0.632 s.

---

## The cost

`plot_alloc()` and `plot_add()` both pick a plot's name by counting a shared,
monotone `plot_num` upward until `<abbrev><plot_num>` is not the typename of any
plot currently in `plot_list`:

```c
do {
    (void) sprintf(buf, "%s%d", s, plot_num);
    for (tp = plot_list; tp; tp = tp->pl_next)      /* O(plots) */
        if (cieq(tp->pl_typename, buf)) {
            plot_num++;
            break;
        }
} while (tp);
```

Plots are prepended, so the *colliding* probe finds its match at the head in
O(1). It is the *successful* probe — proving a name absent — that traverses the
whole list. One full walk per plot created, with a `tolower` per character, and a
sweep creates a plot per point: quadratic in the sweep length.

## The fix, and what deliberately did not change

Only the **membership test** changed. A hash index of the typenames currently in
`plot_list` answers it in O(1):

```c
static void plot_unique_typename(const char *abbrev, char *buf, size_t bufsz)
{
    plot_index_init();
    for (;;) {
        (void) snprintf(buf, bufsz, "%s%d", abbrev, plot_num);
        if (!plot_name_taken(buf))
            return;
        plot_num++;
    }
}
```

The search still starts at the same shared, monotone `plot_num` and still counts
up by one. That matters more than it looks:

- `plot_num` is shared across abbreviations and only advances on a collision, so
  the sequence is `op1 tran1 op2 ac2 op3` — not `op1 op2 op3`. Preserved.
- A number freed by `destroy all` is **reused**. Enhancement-343 rejected a
  "remember every name ever issued" superset cache precisely because it would
  have silently changed this. The index tracks live membership, so `op1`, `op2`,
  `destroy all`, `op` still gives `op1` again.

Both copies of the loop — `plot_alloc()` and `plot_add()` carried the same one —
now share `plot_unique_typename()`.

### Making the index exact

E-343's other rejected option was an exact index, on the grounds that `plot_list`
is mutated in about nine places and a missed insertion hands out a **duplicate
plot name**. That objection is answered by removing the nine places rather than
by tracking them:

- `plot_new()` is now the **single insertion point**. Six callers open-coded the
  same two lines (`com_fft.c` ×2, `linear.c` ×2, `postcoms.c`, `spec.c`) and now
  call it. Afterwards, the only `pl_next = plot_list` left in the tree is inside
  `plot_new()` itself.
- `killplot()` calls the new `plot_forget()` before unlinking.
- `com_removecirc()` rewrites `plot_list` wholesale rather than unlinking, so it
  calls `plot_forget_all()`; the index rebuilds itself from the list on next use.
- The index is built **lazily from `plot_list`**, so plots that predate it — the
  static `const` plot — are covered with no registration step.

## How it was proven

A change like this is only as good as the evidence that the index and the list
agree. So `plot_name_taken()` carries a `PLOTNAME_SELFCHECK` block that answers
the same question the old way and `abort()`s on any disagreement:

```c
#ifdef PLOTNAME_SELFCHECK
    for (tp = plot_list; tp; tp = tp->pl_next)
        if (tp->pl_typename && cieq(tp->pl_typename, typename)) { scan = 1; break; }
    if (scan != hit) { ...; abort(); }
#endif
```

**The full example suite was run with that build: 276/276 OK, zero
disagreements.** The block stays in the source, unset, so the check can be
re-run against future changes.

This caught nothing on its own — but the bug it was there for showed up anyway,
and is worth recording. Converting the open-coded prepends with a regex quietly
produced a **double insertion**: three of those sites already called
`plot_new()`, with the redundant two lines wrapped *around* it, so the edit
turned the trailing line into a second `plot_new()` call. The second call ran
`new->pl_next = plot_list` when `plot_list` was already `new` — a self-loop, and
`vec_gc` spun on the circular list forever. It was found by a stress case
(`fft`) that hung, and located by sampling the hung process rather than by
guessing. The lesson is the ordinary one: a mechanical bulk edit needs each site
read, because the pattern being replaced was not the pattern actually there.

### Names are identical

15 stress cases, each compared against the previous binary: mixed analyses,
`destroy all` and single-plot `destroy` (first, middle, last), `setplot new`,
`fft`, `linearize` ×2, `spec`, rawfile `write`/`load` ×2, load-then-destroy,
twelve-then-destroy, `remcirc`, sweep-then-destroy, and nested `destroy all`.
**All 15 produce byte-identical plot-name sequences.**

### Measured

Same deck, same machine, `sweep pr lin N 1k 3k -analysis op`:

| points | E-344 | E-345 | speedup | µs/point | time × per doubling |
|---|---|---|---|---|---|
| 1,000 | 0.02 s | 0.018 s | 1.4× | 18 | — |
| 2,000 | 0.05 s | 0.027 s | 1.8× | 13 | 1.5× |
| 4,000 | 0.13 s | 0.046 s | 2.7× | 12 | 1.7× |
| 8,000 | 0.40 s | 0.083 s | 4.7× | 10 | 1.8× |
| 16,000 | 1.45 s | 0.163 s | 8.9× | 10 | **2.0×** |
| 32,000 | 6.09 s | 0.321 s | 19.0× | 10 | **2.0×** |
| 64,000 | 54.97 s | 0.632 s | **87.0×** | 10 | **2.0×** |

Per-point cost is pinned at 10 µs and the doubling ratio has converged on 2.0×.
That is what linear looks like, and it is the first time this sweep has been
linear.

Taken together with Enhancement-343, a 16,000-point sweep has gone from 39.55 s
(measured before E-343, same machine and deck) to 0.163 s — about **240×**.

## Verification

- **Self-check build over the whole suite:** 276/276 OK, zero index/list
  disagreements.
- **Naming:** 15 stress cases byte-identical to the previous binary.
- **Regression** (release build): 277/277 OK.
- **Example:** `examples/plotname_examples/` — 7 checks covering the
  shared-`plot_num` sequence, reuse after `destroy all`, single-plot destroy,
  the `fft`/`linearize`/rawfile-load routes, flat per-point cost across a 4×
  span, and the swept values themselves.

## What is left

Nothing quadratic that I can measure in this path. The sweep's cost is now
linear in its point count, and the remaining per-point 10 µs is the analysis
itself.
