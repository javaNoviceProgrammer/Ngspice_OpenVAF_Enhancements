# stringio_examples — Enhancement-11 string-formatting & file-reading functions

End-to-end verification of the Verilog-AMS string-formatting and file-reading
system functions implemented in Enhancement-11 (the counterparts to the
file-output set in `../fileio_examples/`), using **version11's own** `openvaf-r`
and `ngspice-46`.

Functions covered: `$swrite`, `$sformat`, `$sscanf`, `$fgets`, `$fscanf`,
`$ferror`.

## Files

| File | Purpose |
|---|---|
| `stringio_demo.va` | Formats strings (`$sformat`/`$swrite`), parses a literal (`$sscanf`), round-trips a file read (`$fgets`/`$fscanf` over a file it wrote itself), queries `$ferror`, and writes a report. |
| `verify_stringio.py` | Runs a `.op` and checks the report against expected values. |
| `stringio_out.txt`, `_sio.cir`, `*.osdi` | Artifacts. |

## Run

```
python3 verify_stringio.py
```

Expected tail:

```
ALL PASS (6/6)
```

## What it checks (`stringio_out.txt`)

```
sformat=[R=1000 G=0.001]
swrite=[n= 5 ok]
sscanf=3 42 3.14 [hello]
fgets=13
fscanf=2 99 2.5
ferror=0 []
```

- `$sformat`/`$swrite` format into a string variable (`$swrite` concatenates
  like `$write`).
- `$sscanf("42 3.14 hello", ...)` parses an int / real / string and returns the
  match count (3).
- `$fgets` reads the line `"line seven 7\n"` back from a file (length 13,
  including the newline).
- `$fscanf` parses `"99 2.5"` from a file (count 2).
- `$ferror` on a good descriptor returns code 0 and an empty message.

## Notes

The scanner parses each field by the **destination variable's type** (int via
`strtol`, real via `strtod`, string as the next whitespace-delimited token)
rather than by interpreting the C format string — adequate for the usual
whitespace-separated input. As with the file-output functions, keep string/file
I/O parameter/setup-derived so it runs once in the model's initialization code
(see `../Enhancement-11.md` §1.3, §6).
