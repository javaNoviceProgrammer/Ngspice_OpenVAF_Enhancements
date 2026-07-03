# analysis_examples — variadic `analysis(...)` (Enhancement-30)

Demonstrates the **multi-argument list form** of the Verilog-AMS `analysis()`
system function, using **version11's own** `openvaf-r` and `ngspice-46`.

## What was broken

`analysis()` returns true if the current analysis matches any name in a **list**,
e.g. `analysis("ac", "noise")` or `analysis("ic", "dc")` (LRM 4.7.1). The
single-argument form worked, but OpenVAF declared the builtin with exactly one
argument, so the list form failed to compile:

```
error: invalid argument count: expected 1 arguments but found 2
```

## The fix

`analysis` is made a **varargs** builtin, and the lowering **bitwise-OR**s the
per-argument matches (OR, not a sum — at an operating point both `"static"` and
`"dc"` are set, and the result must still be 1). Pure front-end change; no OSDI/
ngspice change. See `../Enhancement-30.md`.

## The demo

`analysis_demo.va` is a conductance that is `g_static` at the DC operating point and
`g_dynamic` for the dynamic analyses, chosen by one list-form call:

```verilog
g = g_static;
if (analysis("ac", "tran", "noise")) g = g_dynamic;
I(a, b) <+ g * V(a, b);
```

## Run

```
python3 verify_analysis.py
```

Checks (ALL PASS): the list form compiles; DC → `g_static`; AC and TRAN →
`g_dynamic`; and `analysis("static","dc","ic")` at `.op` returns exactly 1 (OR, not
a sum). Recognised analysis names: `ac`, `dc`, `tran`, `ic`, `static`, `noise`,
`nodeset`.
