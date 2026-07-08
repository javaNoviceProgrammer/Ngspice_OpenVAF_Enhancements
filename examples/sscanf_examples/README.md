# sscanf_examples — `$sscanf` format base (Enhancement-105)

`$sscanf` / `$fscanf` parsed every integer field with `strtol` base 0 (base
inferred from the **input's** own prefix), ignoring the format string. So
`$sscanf("ff", "%h", x)` gave 0 (it needed `"0xff"`) and `$sscanf("17", "%o",
x)` gave 17 as decimal (it needed `"017"`). Enhancement-105 makes the conversion
character select the base: `%h`/`%x` hex, `%o` octal, `%b` binary, `%d` decimal.

`sscanf_demo.va` parses fixed input strings and exposes the parsed values as
operating-point variables. The verify checks `%h ff→255`, `%o 17→15`, `%b
1010→10`, `%d 42→42` (each wrong under the old base-0 behavior), a repeated
`%h %h → 160, 255`, and a mixed `%d %g → 7, 8.5` with the correct match count.
Run: `python3 verify_sscanf.py` (7 checks).
