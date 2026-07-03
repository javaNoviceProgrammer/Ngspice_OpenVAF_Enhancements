# dowhile_examples — Verilog-A `do ... while` loop (Enhancement-19)

Demonstrates the `do ... while` loop, using **version11's own** `openvaf-r` and
`ngspice-46`. A `do` loop runs its body **once before** the condition is first
tested — the one loop construct OpenVAF previously didn't parse (`for`, `while`,
and `repeat` already worked).

```verilog
do begin
    count = count + 1.0;
    i = i + 1;
end while (i < n);
```

`dowhile_demo.va` runs this loop and reports the iteration `count` as a gain
`V(out) = count · 1e-3 · V(in)`. Because the body always runs at least once,
`count = max(n, 1)` — in particular **`n = 0` still yields count = 1**, which is
exactly what distinguishes `do-while` from `while` (which would run the body zero
times).

## Run

```
python3 verify_dowhile.py
```

Expected:

```
  n   count (=V(out)*1000)  expected max(n,1)  result
  0                      1                  1  PASS
  1                      1                  1  PASS
  2                      2                  2  PASS
  5                      5                  5  PASS
 10                     10                 10  PASS
ALL PASS
```

## Notes

- Syntax: `do <statement> while (<condition>);` — the body may be a single
  statement or a `begin ... end` block; the trailing `;` is required.
- Lowered like `while`, but the body block is entered unconditionally and the
  condition is tested at the *end* of each iteration (a post-test loop).
