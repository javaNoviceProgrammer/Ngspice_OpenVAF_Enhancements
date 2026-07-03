# fileio_examples — Enhancement-11 file-output system functions

End-to-end verification of the Verilog-AMS file-I/O system functions implemented
in Enhancement-11, using **version11's own** `openvaf-r` and `ngspice-46`.

Functions covered: `$fopen`, `$fclose`, `$fdisplay`, `$fwrite`, `$fstrobe`,
`$fmonitor`, `$fdebug`, `$fflush`, `$ftell`, `$fseek`, `$rewind`, `$feof`.
(The reading / string-formatting functions `$fgets`/`$fscanf`/`$sscanf`/
`$swrite`/`$sformat`/`$ferror` remain unsupported — see `../Enhancement-11.md`.)

## Files

| File | Purpose |
|---|---|
| `fileio_demo.va` | A resistor that also exports a characterization report (parameters + a computed `I = V/R` table) to `fileio_out.txt` at initialization. |
| `fileio_seek.va` | Overwrites a file in place to check `$rewind` and `$fseek`. |
| `verify_fileio.py` | Compiles both, runs a `.op`, and checks the written files against the closed-form values. |
| `fileio_out.txt`, `seek_out.txt` | Files produced by the models (artifacts). |
| `*.osdi`, `_fio.cir` | Compiled models and generated deck (artifacts). |

## Run

```
python3 verify_fileio.py
```

Expected tail:

```
ALL PASS (9/9)
```

## What it checks

`fileio_out.txt` (from a `.op` with `R=1k npts=5 vmax=2`):

```
# fileio_demo characterization report
R = 1000 ohm
G = 0.001 S
npts=5  npts_hex=5  label=IV
# V[V]	I[A]
0	0
0.5	0.0005
1	0.001
1.5	0.0015
2	0.002
checksum=5000
bytes_before_this_line=160
```

This exercises `%g` (real), `%d` (int), `%h` (hex), `%s` (string), the
newline-less `$fwrite` (the `checksum=` fragments join on one line), and
`$ftell` (the reported offset equals the bytes written so far). `seek_out.txt`
comes out as `XY234**789`, confirming `$rewind` + `$fseek`.

## Note on when writes happen

Writes that depend only on **parameters/constants** run once, in the model's
initialization code — ideal for dumping model tables and parameters, which is
what this demo does. Writes that depend on **node voltages / the operating
point** are *not* supported cleanly: OpenVAF splits node-dependent code into the
per-iteration eval path, separating it from the `$fopen`/`$fclose` pair. Keep
file I/O parameter/setup-derived. See `../Enhancement-11.md` §1.3.
