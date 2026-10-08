# Enhancement-798: `print` shows a string parameter — `@t3m[mode] = lin` — where it died in `vec_get`

**Scope:** D3 of the
[ngspice + OSDI hunt of 2026-10-08](../docs/bug_hunts/2026-10-08_ngspice-osdi-hierarchy-sweeps-events-and-outputs.md).
ngspice:
- `frontend/spiceif.c`: new `if_print_string_params`.
- `frontend/postcoms.c`: `com_print` prints string parameters first and leaves out the words that
  named nothing else.
- `frontend/vectors.c`: `vec_get`'s string case.
- `include/ngspice/fteext.h`.

`examples/osdislips_examples/` (section [3], five checks); `opvar_examples` [6] updated.
**ngspice only.**

**Suites:** [`osdislips_examples`](../examples/osdislips_examples/) 56 of 56 per solver (all 5 in
[3] fail on the E-795 binaries); `opvar` 15 of 15 per solver; the full sweep, 538 of 538.

## What was wrong

A Verilog-A `parameter string mode = "lin"` is listed by `showmod` and set by `altermod` (since
the 2026-09 hunts). `print` could not read it:

```
print @t3m[mode]
ERROR: can not handle string value of 'mode' in vec_get(@t3m[mode])
Ignoring...
Warning from checkvalid: vector @t3m[mode] is not available or has zero length.
```

`print @n1` printed the same two lines for each string parameter among the numbers. A model whose
only parameter is a string printed nothing else. A string opvar (`opvar` [6]) got the same
treatment. The cause is that `print` evaluates every argument as a vector expression, and a
vector holds numbers.

## The change

`com_print` asks `if_print_string_params` about each argument before evaluating it. A plain
accessor (`@name[param]`, `@name` or `@name[all]`) has each of its string parameters printed as
text, a string opvar included. Anything else is left to the vector path untouched, with no
message from this step:

```
print @t3m[mode] v(1)
@t3m[mode] = lin
v(1) = 2.000000e+00

print @n1
@n1[imode] = fast
@n1[dt] = 0.000000e+00
...
```

An argument that named only strings is dropped from the vector list, so no checkvalid warning
follows.

An expression that meets a string parameter (`let x = @t3m[mode]`) is told what it met and where
to read it:

```
Error: @t3m[mode] is a string parameter ("lin"); a vector holds numbers, so an expression cannot use it. `print @t3m[mode]` shows it.
```

In a whole-device list read by an expression (`let`), the string parameters are left out without
a message, since `print` shows them.

## The checks

osdislips [3]:

- `print` of a model's and an instance's string parameter, and one beside a vector;
- no `vec_get` error or checkvalid warning;
- `print @n1` lists the string parameter beside the numbers;
- `print @s1m`, a model whose only parameter is a string;
- `let x = @t3m[mode]` names the parameter, the value and `print`.

opvar [6] now checks that `print @n1[modename]` shows the value of the string opvar.

## Limits

- `print col` and `print line` print the strings above the table, not in a column.
