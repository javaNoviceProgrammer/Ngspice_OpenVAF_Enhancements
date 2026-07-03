# mdarray_examples — multi-dimensional arrays (Enhancement-15)

Demonstrates Verilog-A **multi-dimensional array** support, using **version11's
own** `openvaf-r` and `ngspice-46`. Enhancement-15 generalises the 1-D arrays of
Enhancement-14 to any number of dimensions:

| Capability | Syntax |
|---|---|
| N-D **declaration** (variable & parameter) | `real [0:1][0:2] m;` · `parameter real [0:1][0:1] w = ...;` |
| N-D **constant** indexing (read/write) | `m[0][1] = ...;` · `... m[1][2]` |
| **Nested** aggregate literals | `acc = '{'{a, b}, '{c, d}};` |
| N-D **dynamic** indexing (read/write) | `tr[j][i] = acc[i][j];` in nested `for` loops |
| N-D array **parameters** (per-element default + override) | `.model m mdarray_demo(w[1][1]=0.9)` |

`mdarray_demo.va` is a weighted-gain buffer: `V(out) = gain * V(in)`, where the
gain is the sum of a 2×2 weight matrix, computed through the multi-dim machinery.
So measuring `V(out)` at `V(in)=1` reads the gain back directly.

## Run

```
python3 verify_mdarray.py
```

Expected:

```
default w='{'{0.1,0.2},'{0.3,0.4}}           1.000000     1.000000  PASS
override w[1][1]=0.9                         1.500000     1.500000  PASS
override w[0][0]=0.5 w[1][1]=0.5             1.500000     1.500000  PASS
ALL PASS
```

## Notes

- **Declaration** is *ranges-before-name*: `real [0:1][0:2] m;` (2×3), one
  `[msb:lsb]` clause per dimension. Access is *brackets-after-name*: `m[i][j]`.
- **Element order / literal fill** is row-major: the outermost dimension varies
  slowest, each dimension iterated `msb`→`lsb`. So
  `real [0:1][0:2] m = '{'{a,b,c},'{d,e,f}}` maps `m[0][0]=a … m[1][2]=f`.
- **Array parameters** expand into one scalar OSDI parameter per element, named
  `w[0][0]`, `w[0][1]`, … — ngspice overrides each individually in a `.model`
  card; unset elements keep their nested-literal default.
- **Dynamic indexing** applies to array *variables*. A dynamic index lowers to a
  runtime select over the flattened element variables (flat position
  `Σ pos_k·stride_k`), so its cost grows with the total element count — fine for
  the small coefficient matrices these features target. Array *parameters* are
  constant tables, indexed by a constant index (copy into a variable array to
  index dynamically, as `mdarray_demo` does).
- Number of `[..]` clauses must match the declared dimensionality, else a
  "wrong number of array indices" error is reported.
