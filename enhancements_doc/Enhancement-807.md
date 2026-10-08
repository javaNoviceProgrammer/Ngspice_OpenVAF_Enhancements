# Enhancement-807: `altermod nch g=7m` reaches every bin of a binned model — it was "no such device or model name nch"

**Scope:** D13 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `frontend/spiceif.c`: new `e807_altermod_bins`, called by `if_setparam` when a model write
  names nothing; the file includes `dstring.h`.

`examples/osdislips_examples/` (section [13], five checks). **ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 93 of 93 per solver (4 of the 5
in [13] fail on the E-795 binaries); the full sweep, 538 of 538.

## What was wrong

A binned model is a set of cards `nch.1`, `nch.2`, … that instances name as `nch`. Each instance
binds to the bin covering its `l` and `w` (E-495 for OSDI, ngspice's own binning for BSIM).
`altermod nch g=7m` changed nothing:

```
Error: no such device or model name nch
```

The error said nothing about the bins. No spelling reached them together:
- `nch*`, `nch.*` and `@nch*[g]` were "no such device or model name";
- E-436's `@*:name[…]` covers subcircuit copies only.

The only way was one `altermod` per bin.

## The change

When `altermod` (or `altermod @nch[g]=…`) names no model and no device, the cards named
`<name>.<digits>` are found. The value is given to each through the ordinary path, so every bin
keeps its own messages and its own refusal (a range check, a parameter it lacks). One note names
them, in bin order:

```
Note: altermod: 'nch' is a binned model; g was given to its 2 bins (nch.1, nch.2).
```

The note counts real writes (E-544's counter):
- if only some bins took the value, it says how many of how many;
- if none did (a parameter no bin has), it says "no bin took nosuch" after each bin's refusal.

A name with no bins keeps the old error. Built-in binned cards (BSIM4 `nch.1`/`nch.2`) work the
same way.

## The checks

osdislips [13]:

- `altermod nch g=7m`: both bins move (7 mA each), with the note in bin order;
- `altermod @nch[g]=7m`: the same;
- a parameter no bin has: each bin's refusal, then "no bin took";
- a name with no bins: still "no such device or model name";
- BSIM4 bins: `altermod nch vth0=0.3` raises the drain current.

## Limits

- Bins are matched by the name pattern `<name>.<digits>` (ngspice's binning convention), not by
  which cards actually bind together.
- `alter` (instance parameters) and reads (`print @nch[g]`) are unchanged: an instance belongs to
  one bin, and a read of "the" value of a family has no single answer.
