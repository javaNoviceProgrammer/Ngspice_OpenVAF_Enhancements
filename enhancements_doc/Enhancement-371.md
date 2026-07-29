# Enhancement-371 — per-type plot numbering, and a date on every plot

Two things a user noticed about a 500-point sweep: the plot was called `sweep500`
rather than `sweep1`, and its **Date** field was empty.

Neither number was a coincidence, and both had the same shape of cause — a
property that was set in one place and assumed everywhere.

---

## 1. Why `sweep500`

`plot_unique_typename()` picked a name by counting up a **single counter shared by
every plot type**:

```c
static void plot_unique_typename(const char *abbrev, char *buf, size_t bufsz)
{
    plot_index_init();
    for (;;) {
        (void) snprintf(buf, bufsz, "%s%d", abbrev, plot_num);   /* plot_num is global */
        if (!plot_name_taken(buf))
            return;
        plot_num++;
    }
}
```

A `sweep` runs one analysis per point **and keeps its plot** — that is deliberate,
so waveforms can be overlaid. A 500-point sweep therefore creates `op1 … op500`,
each collision pushing the shared counter, and by the time the sweep's own plot is
named the counter stands at 500. Hence `sweep500`.

The number looked like the point count. It was really *"how many plots exist"* —
and the resemblance is exact only because the per-point plots are what pushed it.

Measured before the fix, with a `tran` and an `ac` also in the deck:

```
sweep: 501 points into plot 'sweep501' (now current)
Current sweep501    op501, op500, op499, … op3, noise3
```

### The fix

Each abbreviation now carries its own counter, so the first sweep is `sweep1`
whatever else has run:

```
sweep: 501 points into plot 'sweep1' (now current)
```

A `tran`/`ac`/`tran`/`ac`/`noise`/`sweep`/`sweep` deck goes from

```
before:  sweep12  op12 … op3   noise3
after:   sweep2   op10 … op1   noise2
```

It differs from the old behaviour in exactly the pathological case: when one
type's plots number an unrelated type. In ordinary use the two agree, because a
collision on `tran1` only ever pushed the counter for the next `tran`.

### What had to be preserved

[Enhancement-345](Enhancement-345.md) exists because this naming path was
**quadratic** over a sweep — 89 % of a 64000-point sweep sat in
`plot_alloc → cieq → tolower`, and E-345 fixed it by starting the search from the
shared monotone counter and testing membership through a hash index.

A per-type counter that restarted the search at 1 each time would have
reintroduced precisely that quadratic. So the counter is **remembered per type**
(an `nghash` keyed on the lowercased abbreviation) and the search resumes from it.
The E-345 example's timing check still passes: 22 → 21 µs/point, ratio 0.93 for a
4× longer sweep.

### `destroy` has to walk it back down

`destroy all` must restart numbering at `tran1` — the
[E-81](Enhancement-81.md) lifecycle example pins that, and **it is what caught the
first version of this change.** `destroy` unlinks plots one at a time through
`plot_forget()` rather than calling `plot_forget_all()`, so `plot_forget()` now
lowers that type's counter to the freed number. Destroying `op1 … op10` walks it
down to 1.

That also makes a *single* `destroy op2` recycle the number, which the shared
counter never did (it went on to `op4`). Recycling is the behaviour `destroy all`
always had, so this makes the two consistent rather than introducing a new rule.

## 2. Why the Date was empty

Only the **analysis** path set it. `outitf.c`, which creates the plot for every
`.tran`/`.ac`/`.dc`/`.noise`/…, did:

```c
struct plot *pl = plot_alloc(run->type);
...
pl->pl_date = copy(datestring());
```

Every plot created **directly by a command** — `sweep`, `hb`, `envelope`, `eye`,
`loadpull`, `stb`, `rfstab`, `qpac` — called `plot_alloc()` and never set a date,
so `pl_date` stayed NULL and `print` rendered it as `(null)`:

```
                                         v1
                                         Sweep  (null)
```

### The fix

Stamp it in `plot_alloc()` — the single point where every plot is created:

```c
pl->pl_typename = copy(buf);
pl->pl_date = copy(datestring());
```

which covers all eight command paths at once and any future caller for free. The
five sites that previously set their own date are now redundant and were removed,
except `rawfile.c`, where a loaded rawfile carries its **own** date that must win —
that one frees the stamp before replacing it, so centralising does not leak.

## Verification

`examples/plotname_examples` — the E-345 example, whose expectations this change
deliberately alters — was updated and extended rather than replaced, because it is
the file that documents this behaviour.

```
   fixed:        9/9
   pre-fix:      4/9   per-type sequence        got op1 tran1 op2 ac2 op3
                       destroy one recycles     went to op4, not op2
                       fft/load naming          sp2/op2, not sp1/op1
                       sweep plot has a date    "(null)" present
```

The `tran` date row **passes on both** binaries — that is the control showing the
analysis path always had a date and still does, and that only the command paths
changed.

Regression 294/294.

## A note on the numbers not being 1, 2, 3 in general

Two sweeps in one session are now `sweep1` and `sweep2`. The per-point `op` plots
are still created and still kept (`op1 … op501`), because `-overlay` and waveform
inspection rely on them. If that accumulation is itself unwanted for long sweeps,
that is a separate change from naming and is not made here.
