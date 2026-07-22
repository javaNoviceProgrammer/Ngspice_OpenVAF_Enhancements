# derivgroup_examples — Enhancement-281

`cx_deriv` (`src/maths/cmaths/cmath4.c`) walks its input in blocks of `grouping`
(= the vector's `v_dims[0]`):

```c
for (base = 0; base < length; base += grouping)
    for (i = degree; i < grouping; i += 1) ... window around i + base ...
```

For an ordinary vector `grouping == v_length`, so there is one block and the window
fits. But a vector whose declared dimension differs from its length -- as produced by a
binary op on operands of unequal length, e.g. `min(v(b), ac.v(b))` (66-point real +
5-point complex -> length 66, dims[0] 5) -- leaves a PARTIAL last block: `base` reaches
`length - 1` while the window spans `base + grouping - 1`, reading past the input
(ASan heap-buffer-overflow READ).

Fix: bound the inner loop with `i + base < length` in both branches -- a no-op when
`grouping == length`.

## Verify

```
python3 verify_derivgroup.py
```

Four checks: `deriv(min(v(b), ac.v(b)))` and `deriv(max(...))` clean; an ordinary real
`deriv(2t)` still == 2; the complex `deriv(t + 2t*i)` still == (1, 2i).
