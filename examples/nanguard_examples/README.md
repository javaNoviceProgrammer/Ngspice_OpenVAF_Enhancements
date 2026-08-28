# Enhancement-502 — the guard that refuses the wrong value and admits NaN

```
python3 verify_nanguard.py
```

34 checks, both linear solvers. 23 of them fail without the fix.

## What was wrong

Round 60 swept the commands that produce a **report** — `emir`, `eye`, `reduce`,
`envelope`, `qpss`, `hbosc` — and found one guard written the same way in every
one of them:

```c
if (x <= 0.0) { refuse; }
```

Every comparison with NaN is false, so that test refuses `0`, refuses a negative
number, and lets **NaN straight through**. It is one `!` away from correct.

### 1. A one-token SIGSEGV

`envelope <node> nan <tstop>` crashed, five runs out of five:

```
EXC_BAD_ACCESS (code=1, address=0x10)    frame #0: ngspice`SMPmatSize
```

`fc` is NaN, so `T = 1/fc` is NaN, so the internal settling transient is built as
`tran nan nan 0 nan` — which ngspice **refuses**. The refusal was never checked,
the matrix was never built, and `EFanalysis` dereferenced it one call later.

Two separate fixes: the argument is refused at the front, **and** `envelope` now
checks that its own internal transient ran before using the result. Any refused
transient leaves `CKTmatrix` NULL, not just a NaN one — the same shape as
[Enhancement-438](../../enhancements_doc/Enhancement-438.md), where a failed
sample kept the previous plot and was counted as a pass.

### 2. A limit that is never exceeded

| command | before | after |
|---|---|---|
| `emir jmax nan` | **"0 segments over Jmax"**, every segment `ok` — on a grid with 2 genuine violations | refused |
| `emir thick nan` | every `J` is `nan`, all `ok` | refused |
| `qpss v(o) nan 1.1e6` | a 25-row spectrum, every frequency/magnitude/phase `nan`, rc = 0 | refused |
| `reduce nan` | **"26 nodes → 26 nodes (1.0x)"**, wrote a `reduced.sp` that reduced nothing | refused |
| `eye -ui nan` | **eye height 0** — a fully closed link — width `nan` | refused |

This is [Enhancement-501](../../enhancements_doc/Enhancement-501.md)'s NaN spec
bound, one command over: a limit used only in a comparison is not a strict limit
when it is NaN, it is *no limit at all*.

### 3. The two that returned a different answer instead of a blank

**`eye -tstart nan`** was not refused and not blank. The "skip samples before
tstart" test is also a comparison, so NaN never skipped: the startup transient the
flag exists to exclude was folded into the eye, and RMS jitter came back
**9.86e-13 instead of 1.50e-15 — 660x** — with no diagnostic.

**`qpss ... maxorder nan`** silently became `order <= 1`, dropping every
intermodulation product. That is the entire reason the command exists, and the
only trace was a quiet `order <= 1` in the banner.

Both reached their clamp through an **undefined** `double`→`int` conversion, as
did `emir top nan` (which landed on 1) and `compose lin=1e12` (which landed on
`INT_MAX` and really allocated **17 GB** — the vector was genuine,
`v[2147483000]` read back correctly).

### 4. `emir` could not tell a given width from a default

`emir` reads `@r[w]`, which answers `1e-5` for an undimensioned wire. So the
segment most likely to be the oversight was analysed as a comfortable 10 µm
conductor and reported `ok` — while the header of `com_emir.c` documents that such
segments are *skipped*. Meanwhile `w=0` and `w=-0.5u` **were** skipped and
reported as *"no width given"*, which is the one thing they were not.

`emir` now asks the instance whether the width was given (`RESwidthGiven`, as
`rcreduce.c` already reads resistor internals for `reduce`), skips it if not, and
reports the two reasons separately.

## The idiom was already in the tree

`hbosc` refuses `K nan` — because its test is `K >= 1`, which is NaN-safe in the
right direction. `compose` refuses NaN on every parameter it takes
(*"bad parm lin = nan"*). `stb` delegates its frequency spec to `ac` and refuses
every NaN. The guards now go through three shared helpers in
`frontend/parser/numparse.c` — `ft_argpos`, `ft_argfinite`, `ft_argcount` — which
parse with `ft_numparse`, so `thick 0.5u`, `-ui 0.5n` and `1meg` keep working.
