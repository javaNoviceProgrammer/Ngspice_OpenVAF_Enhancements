# Enhancement-502 — the guard that refuses the wrong value and admits NaN

Round 60 left the sweep/optimize/Monte-Carlo ground of the previous three rounds
and swept the commands that produce a **report** — `emir`, `eye`, `reduce`,
`envelope`, `qpss`, `hbosc`, `stb`, `rfstab`, `compose`. One guard was written the
same way in six of them:

```c
if (x <= 0.0) { refuse; }
```

Every comparison with NaN is false. That test refuses `0`, refuses a negative
number, and lets **NaN straight through** — one `!` away from correct. What
walked through it was not harmless.

## 1. A one-token SIGSEGV

`envelope <node> nan <tstop>` crashed, five runs out of five:

```
EXC_BAD_ACCESS (code=1, address=0x10)    frame #0: ngspice`SMPmatSize
```

`fc` is NaN, so `T = 1/fc` is NaN, so the settling transient is built as
`tran nan nan 0 nan`. ngspice **refuses** that command — and the refusal was never
checked, so the matrix was never built and `EFanalysis` dereferenced it one call
later.

Both halves are fixed. The argument is refused at the front, and `envelope` now
checks that its own internal transient actually ran:

```c
if (!ft_curckt || !ft_curckt->ci_ckt || !ft_curckt->ci_ckt->CKTmatrix) { ... }
```

That second check matters beyond this bug. **Any** refused transient — a step the
circuit cannot take, a bias point that will not converge — leaves `CKTmatrix`
NULL. A command must never use the result of an internal analysis without asking
whether it happened, which is Enhancement-438's shape: there, a failed sample kept
the previous plot and was counted as a pass.

## 2. A limit that is never exceeded

| command | before | after |
|---|---|---|
| `emir jmax nan` | **"0 segments over Jmax"**, every segment `ok`, on a grid with 2 genuine violations | refused |
| `emir thick nan` | every `J` reported as `nan`, all `ok` | refused |
| `qpss v(o) nan 1.1e6` | a 25-row spectrum, every frequency/magnitude/phase `nan`, rc = 0 | refused |
| `reduce nan` | **"26 nodes → 26 nodes (1.0x)"** and a `reduced.sp` that reduced nothing | refused |
| `eye -ui nan` | **eye height 0** — a fully closed serial link — width `nan` | refused |
| `emir rail nan` | "worst drop **nan** V (0.0% of rail)" | refused |

Each of those guards proves its own intent by working: `jmax 0`, `reduce -1`,
`-ui 0` and `qpss` with two equal tones were all correctly refused.

This is Enhancement-501's NaN spec bound one command over. A limit used only in a
comparison is not a strict limit when it is NaN — it is *no limit at all*, and the
report says the design passed.

## 3. The two that returned a different answer rather than a blank

**`eye -tstart nan`** was neither refused nor blank. The "skip samples before
tstart" test is also a comparison, so NaN never skipped: the startup transient the
flag exists to exclude was folded into the eye. 120 crossings instead of 114, and
RMS jitter **9.86e-13 against 1.50e-15 — 660x** — reported with no diagnostic.

**`qpss ... maxorder nan`** silently became `order <= 1`, dropping every
intermodulation product. That is the entire reason the command exists; the only
trace was a quiet `order <= 1` in a banner.

Both reached their clamp through an **undefined** `double`→`int` conversion, as
did `emir top nan` (landing on 1) and `compose lin=1e12` — which landed on
`INT_MAX` and really allocated **17 GB**. That vector was genuine:
`v[2147483000]` read back the correct value after a pause long enough to look
like a hang.

## 4. `emir` could not tell a given width from a default

`emir` computes current density from `@r[w]`, which answers `1e-5` for a resistor
whose deck line never gave a width. So the segment most likely to be the oversight
was analysed as a comfortable 10 µm conductor and reported `ok` — while the header
of `com_emir.c` documents that such segments are *skipped*.

The inverse was also true: `w=0` and `w=-0.5u` **were** skipped, and reported as
*"no width given"* — the one thing they were not.

`emir` now asks the instance (`RESwidthGiven`, reading resistor internals the way
`spicelib/analysis/rcreduce.c` already does for the `reduce` command), skips an
undimensioned segment, and reports the two reasons separately.

## The idiom was already in the tree

Three commands got this right and were left alone, and they are what the fix
copies:

- **`hbosc`** refuses `K nan` — its test is `K >= 1`, NaN-safe in the right direction.
- **`compose`** refuses NaN on every parameter it takes (*"bad parm lin = nan"*).
- **`stb`** delegates its frequency spec to `ac`, which refuses every NaN.

The guards now go through three shared helpers added to
`frontend/parser/numparse.c`, next to `ft_numparse` itself:

```c
int ft_argpos   (const char *cmd, const char *what, const char *tok, double *out);
int ft_argfinite(const char *cmd, const char *what, const char *tok, double *out);
int ft_argcount (const char *cmd, const char *what, const char *tok,
                 int lo, int hi, int *out);
```

They take the raw **token**, so the diagnostic names what the user actually typed,
and they parse with `ft_numparse` rather than `strtod` — these are SPICE numbers,
and `thick 0.5u`, `-ui 0.5n`, `jmax 3.5e11` and `1meg` are how the documentation
writes them. Enhancement-501 shipped a guard built on `strtod`, it refused
`dynamic 20u` — the spelling in Enhancement-157's own example — and the existing
aging suite caught it. `ft_argcount` checks the value **before** the cast, because
converting a NaN or an out-of-range double to `int` is undefined.

## Files

| file | change |
|---|---|
| `src/frontend/parser/numparse.c` | `ft_argpos`, `ft_argfinite`, `ft_argcount` |
| `src/include/ngspice/fteext.h` | their declarations |
| `src/frontend/com_envelope.c` | NaN-safe arguments; check the internal transient ran |
| `src/frontend/com_emir.c` | all six arguments validated; `RESwidthGiven`; two distinct skip messages |
| `src/frontend/com_eye.c` | `-ui`, `-tstart`, `-threshold`, `-window` validated; an unusable window is named |
| `src/frontend/com_qpss.c` | `<f1>`, `<f2>`, `<periods>`, `<maxorder>` validated |
| `src/frontend/com_reduce.c` | `<fmax>`, `factor`, `maxdeg` validated; `factor < 1` refused |
| `src/frontend/com_hbosc.c` | a *supplied* `fguess`/`tstab` must be usable; an absent one still defaults |
| `src/frontend/com_compose.c` | a point count larger than a vector can hold is refused |
| `src/frontend/com_rfstab.c` | a fifth S-parameter name is refused, as two or three already were |

## Verification

`examples/nanguard_examples/verify_nanguard.py` — 34 checks under both linear
solvers. 23 fail on the shipped binary.

## Withdrawn during the hunt

Four reported findings did not survive, all of them the harness rather than
ngspice: `emir` **does** print `(1 resistor skipped for EM: ...)`; `reduce` **does**
warn *"keep node 'nosuchnode' not found"* (a `[:2]` slice had cut the line off);
`reduce keep out N24` legitimately keeps `n24`; and `rfstab` reporting
*potentially UNSTABLE* for a real vector handed in as S11 is the conservative
direction, with arbitrary vector names explicitly documented.
