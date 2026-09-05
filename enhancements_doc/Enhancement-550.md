# Enhancement-550: `pyplot` draws a long trace as its per-pixel min/max envelope, re-decimated on zoom

**Scope:** improvement 2 of the `pyplot` review recorded in
[E-547](Enhancement-547.md). **ngspice only; the compiler is unchanged.**

**Suites:** [`pyplot_examples`](../examples/pyplot_examples/) 35 → 40; the
twelve suites that exercise pyplot pass. Reference
[§12.5](../docs/internals/ngspice_internals/ngspice_pyplot.md).

## What changed

A pixel column can only show its extremes, so a trace with more samples than
twice the axis width in pixels is drawn as its **min/max envelope** per
column: the same picture, drawn in milliseconds — matplotlib took 4.8 s of a
5.2 s run to draw four million points onto a 640-pixel canvas.

* The envelope (`_envelope` in the generated script) bins by x, so adaptive
  time steps are handled; keeps each column's actual extreme samples in time
  order; skips NaN padding; and leaves point plots, step plots and a `vs`
  plot whose x runs backwards alone.
* **An interactive window re-decimates on every zoom, pan and resize** from
  the full data kept beside each line, so zooming into a 10 µs slice of a
  2 ms run redraws that slice in full detail. A hardcopy decimates once at
  its dpi.
* The script says what it did: `pyplot: 1000008 samples per trace drawn as a
  1280-point envelope (set pyplot_decimate=off for every sample)`.
* **`set pyplot_decimate`**: unset or `auto` as above; `off` for every
  sample; an integer for a fixed bin count. It is read as a number first and
  as a word second, since ngspice stores the two differently. The exported
  table always holds every sample.

## Measured

The million-point, four-trace hardcopy: 2.34 s end to end against 6.81 s
with decimation off; the Python step alone from 5.2 s to 0.38 s. The two
figures are indistinguishable.

## Verification

| check | result |
|---|---|
| a 200k-sample hardcopy trace | at most two points per pixel column, the same extremes per column as the full data, the message |
| `pyplot_decimate=off` | every sample drawn |
| `pyplot_decimate=500` | at most 1000 points |
| a window's line after `set_xlim` to a slice | the slice's envelope, in detail |
| a point plot and a backwards-x `vs` plot | every sample kept |
| `pyplot_examples` | 40 / 40, both solvers |
| full sweep | 453 of 455, the two others failed only while the binary was being relinked underneath them and pass individually |
