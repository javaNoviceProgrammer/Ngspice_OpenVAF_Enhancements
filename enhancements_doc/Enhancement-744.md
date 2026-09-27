# Enhancement-744: `rdsnp` reads Touchstone 2 — the keywords, a per-port `[Reference]` published as `Zref`, the `Lower`/`Upper` matrix formats, the noise and information sections — refuses by name what it cannot read, names a v1 noise-parameter block as the usual cause of a bad count, and takes the specification's default for a file with no option line

**Scope:** F3 of the
[Touchstone-import hunt](../docs/bug_hunts/2026-09-26_touchstone-import.md),
with F4's message and F8, all in the same reader. `src/frontend/postcoms.c`
(`com_read_sparam`, two helpers `rdsnp_keyword` and `rdsnp_numbers`),
`src/frontend/commands.c` (the help text, both tables),
`examples/touchstone_examples/` (section [9], seven checks), `.gitignore`
(the suite's `_*.ts` probe). **ngspice only.** `wrsnp`, the `.sp` analysis,
the `pre_snp` converter (E-741) and the Python `snp2va.py` are untouched.

**Suites:** [`touchstone_examples`](../examples/touchstone_examples/) 24 of
24 per solver, both solvers (17 of 24 on the E-743 binary); `snpfuzz`,
`presnp`, `nport_native`, `rfstab`, `savenoise`, `pyplotsmith` unchanged;
full sweep 532 of 532.

## What was wrong

E-72's reader took every line that was not `#` or `!` as data and scanned it
with `sscanf`, which stops at a `[`. A Touchstone 2 keyword line therefore
yielded no numbers and was dropped whole — the frame count came out right,
which is why `rdsnp` did not share E-741's garbage fits — but so was
everything the keywords say. On the hunt's two-port with S12 a tenth of S21:

| file | `S_2_1[0]` | `S_1_2[0]` |
|---|---:|---:|
| v1 | 0.49972 − j0.01178 | 0.049972 − j0.001178 |
| v2, `[Two-Port Data Order] 12_21` | **0.049972 − j0.001178** | **0.49972 − j0.01178** |

`[Reference]` was lost, so `Rbase` fell back to the option line's `R` or to
50, and a v2 Y or Z file, which the v2 specification stores un-normalized,
would have been divided or multiplied by `Rbase` as if v1. Two smaller
things sat in the same function. A v1 two-port carrying the noise-parameter
rows the v1 specification allows was refused with *holds 214 numbers, not a
multiple of 9 — wrong port count?* (F4), the right refusal with the wrong
cause named. And a file with no option line was read as *Hz S RI R 50*
where the specification's default is *GHz S MA R 50*, which the converter
applies (F8): measured, the 100 kHz point came back as 1e-4 Hz with
magnitude and angle taken as real and imaginary parts.

## What changed

`com_read_sparam` is version-aware, the way E-741 made `parse_touchstone`.
A bracketed line is a keyword (`rdsnp_keyword` lower-cases it and collapses
its inner whitespace):

* `[Version]` marks the file as v2; from then on a numeric line before
  `[Network Data]` is an error.
* `[Number of Ports]` gives N (1 to 512); a count on the command line or an
  extension that disagrees is refused with both numbers. A v2 file without
  it is refused.
* `[Two-Port Data Order] 12_21` or `21_12` sets the two-port layout; a v2
  two-port without it is refused, the alternative being a silent swap.
* `[Number of Frequencies]` is checked against the frames read.
* `[Reference]` takes N impedances, on the keyword line or continued over
  the lines that follow; a short list is refused. They are published as
  the real vector `Zref`; `Rbase` is port 1's, and when the ports differ
  a note says so and that `wrsnp`, a v1 writer, carries one value only.
* `[Matrix Format] Full`, `Lower` or `Upper`: a triangle frame holds
  `N(N+1)/2` pairs and is mirrored into the full set of `S_i_j` vectors.
* `[Begin Information]` … `[End Information]` is skipped whole;
  `[Number of Noise Frequencies]` is accepted; `[Noise Data]` and `[End]`
  end the network data.
* `[Mixed-Mode Order]`, the option line's `G` and `H` types, and an unknown
  keyword are refused with their name and line.

A trailing `!` comment on any line is stripped (only a leading one was).
The count check names the count, the frame size and the two things it
usually means:

```
Error: v1noise.s2p holds 214 numbers of network data, not a whole number of 2-port frames of 9
(frequency + 4 pairs): a wrong port count, or Touchstone 1 noise-parameter rows after the
network data, which rdsnp does not read -- remove them, or give the port count
```

A v1 file's Y and Z are de-normalized by `Rbase` as before; a v2 file's are
taken as written. The port count of a v1 file comes from a `.sNp`, `.yNp` or
`.zNp` extension (only `.sNp` counted, so `wrsnp`'s own `.y2p` needed the
count on the command). A file with no option line is read with *GHz S MA R
50*, and the warning names that default. The help entry says what the
command reads now. The plot's shape is unchanged: `frequency` in Hz, complex
`S_i_j` (or `Y_i_j`, `Z_i_j`) in the `.sp` plot's conventions, `Rbase`, and
for a v2 file `Zref`; the summary line adds *(Touchstone 2)*.

## Verification

Section [9] of `verify_touchstone.py`, hand-written files, under both
solvers:

| check | result |
|---|---|
| a v2 two-port in `12_21` order with S12 = 0.1·S21 | S21 = −0.5j and S12 = −0.05j, not swapped; announced as Touchstone 2 |
| `[Reference] 50` / `75` over two lines, an information block, a `[Noise Data]` section | `Rbase` 50, `Zref` = [50, 75], the note, 2 points |
| a v2 Y file and a v1 `.y2p` of the same 0.02 S network | both read as 0.02 S; the `.y2p` port count from the extension |
| a 3-port `.ts` in `Lower` format, GHz | the triangle mirrored, S12 = S21, the port count from the keyword, the scale in Hz |
| a v1 file with noise-parameter rows | refused naming the count, the frame and the rows |
| no option line | frequency 1e9 and S21 = −0.5j from the GHz MA default, the warning naming it |
| `[Mixed-Mode Order]`; a v2 two-port without its data order; `rdsnp file 3` against `[Number of Ports] 2` | each refused by name |

The hunt's probe files give the v1 numbers for the v2 file, the refusal for
the noise-parameter file, and 100 kHz for the option-less file. On the E-743
binary the seven fail. The round-trip and measured-file checks of E-72
([7] and [8]) are unchanged; `snpfuzz` (which fuzzed this reader clean at
E-227) is unchanged.

## What this does not do

* The noise-parameter rows are refused, not read, in the reader as in the
  converter (F2, F4's second half). Nothing publishes NFmin, Γopt or rn.
  *(Update, E-749: both readers read them now; `rdsnp` publishes NFmin,
  SOpt and Rn in a plot of their own.)*
* `wrsnp` stays a Touchstone 1 writer: it carries one reference, so a plot
  imported from a v2 file with differing `Zref` exports with port 1's.
* Mixed-mode data, and the `G` and `H` types, are refused rather than
  converted.
* The `.sp` analysis and `rfstab` read their own plots, not files, and are
  untouched.
