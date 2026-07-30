# Enhancement-373 — a rawfile round trip lost the scale column and renamed the axis

Found on a **fresh axis**. [E-226](Enhancement-226.md) fuzzed rawfile *loading*
with malformed input, looking for crashes. This asks a different and stronger
question: does a rawfile written by ngspice, then loaded by ngspice, still hold
the same data?

Round-trip identity is a perfect oracle — no reference implementation needed — and
it catches silent fidelity loss that a crash fuzzer cannot see. It also lands on
freshly-changed code, since [E-371](Enhancement-371.md) had just touched
`rawfile.c`.

Two independent defects came out of it. **Neither corrupted a value.**

---

## 1. `print` lost the x-axis column for every loaded plot

```
before write:   Index   v-sweep         v(mid)
after  load:    Index   v(mid)
```

The data was intact; what vanished was any indication of *which x-value each row
belonged to*.

`print` prepends the scale column only when `pl_ndims` is non-zero:

```c
if (!noprintscale && bv->v_plot->pl_ndims)                    /* postcoms.c */
    if (bv->v_plot->pl_scale && !vec_eq(bv, bv->v_plot->pl_scale)) { ...prepend... }
```

`outitf.c` initialises `pl_ndims = 0` and sets it to `1` when analysis data
arrives — but **`pl_ndims` appeared nowhere in `rawfile.c`**. Every loaded plot
therefore carried 0 and failed the gate.

**Proven, not inferred.** Before writing the fix, a one-line probe setting
`pl_ndims = 1` on load was inserted and shown to restore the column exactly, then
reverted. The fix sets it once where the reader creates the plot.

### The `op` case is the control that matters

Setting `pl_ndims = 1` could have made `print` *invent* a scale column for a plot
that has no real scale — an `op` plot's "variable 0" is just data, and the reader
assigns `pl_scale` to variable 0 unconditionally. It does not: print's inner
`pl_scale && !vec_eq(bv, pl_scale)` test still suppresses it, and `op` prints the
same header before and after. That is checked explicitly, because it is the reason
this fix is safe.

## 2. The `.dc` sweep axis was renamed

`v-sweep` was written to the file as `v(v-sweep)`, so the name did not survive a
round trip. From the writer:

```c
else if (v->v_type == SV_VOLTAGE) {
    if (ciprefix("v(", v->v_name) || newcompat.eg)
       fprintf(fp, "\t%d\t%s\t%s",    i++, v->v_name, ...);
    else
       fprintf(fp, "\t%d\tv(%s)\t%s", i++, v->v_name, ...);   /* wraps */
}
```

The `v(...)` form means *"the voltage at node X"*. That is right for a node probe
and wrong for a sweep **axis**. A `.dc` plot's scale is the synthetic,
voltage-typed vector `v-sweep`, which has no `v(` prefix, so it got wrapped.

It did **not** compound — verified over three successive write/load passes, the
prefix test makes a second pass leave `v(v-sweep)` alone — so the damage was a
one-time rename rather than runaway nesting.

The fix adds `|| v == pl->pl_scale` to the "write it as-is" condition. Checked how
wide the else-branch's reach actually was: node voltages are already named
`v(mid)` internally and take the first branch, and `let`-created vectors are
`SV_NOTYPE`, so **the plot's scale was the only thing that branch was ever reached
by**. `time` and `frequency` escaped it because they are not voltage-typed.

## Verification

`examples/rawtrip_examples` writes each analysis, loads it back, and compares.

```
   fixed:        19/19
   pre-fix:       6/19   print columns survive     tran/ac/dc, ascii and binary
                         axis present after load   time / frequency / v-sweep
                         written axis name         v(v-sweep), not v-sweep
```

The controls pass on **both** binaries: the `op` rows (no column invented) and
both value comparisons — which is what shows the values were never the problem.

## Scoped out, and why: ASCII rawfiles are 1 ULP lossy

The value comparison is byte-exact for `binary` but only to 1e-15 for `ascii`, and
that is a deliberate scoping decision rather than an oversight.

The writer emits `%.*e` with `prec = DEFPREC`, i.e. **16 significant digits**,
while reproducing an IEEE double exactly requires **17**. Measured with
`numdgt=16`: 33 of 59 rows differ, always in the **scale** column and always at
the 17th digit — `4.0000000000000004e-11` reads back as `3.9999999999999998e-11`,
one ULP. The data values were identical, and the worst relative deviation across
118 values is 4.33e-16.

The in-source comment on `raw_prec` even claims "default 15 (max)", which is
wrong — 15 is not the maximum useful precision for a double.

Raising the default precision changes the on-disk format for every ASCII rawfile
ngspice writes, which is a broader change than the two defects above, so it is
**recorded here and not made**. A serializer that cannot reproduce its own input
is arguably defective; that is a separate call.

Regression 296/296.
