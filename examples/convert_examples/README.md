# convert_examples — `$rtoi` / `$itor` conversion functions (Enhancement-104)

Verilog / Verilog-AMS provides two explicit conversion system functions:
`$rtoi(real)` → integer (truncating **toward zero**) and `$itor(integer)` →
real. openvaf-r supported the *implicit* conversions but not the explicit
functions (`'$rtoi' was not found`). They matter because `$rtoi` truncates
whereas an implicit real→integer assignment **rounds** — so `$rtoi(3.9)=3` (not
4) and `$rtoi(-3.9)=-3` (not -4).

`convert_demo.va` takes `$rtoi` of module parameters (runtime path) and of a
`localparam` (const-folding path), and `$itor` of an integer. The verify checks
the toward-zero truncation on positive and negative inputs (a rounding cast
would give 4/-4), that `$rtoi(9.6)` const-folds to 9 in a `localparam`, and that
`$itor(7)*0.5 = 3.5` (proving `$itor` yields a real). Run:
`python3 verify_convert.py` (9 checks).
