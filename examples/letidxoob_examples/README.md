# letidxoob_examples — Enhancement-280

`get_index_values` (`src/frontend/com_let.c`) validated `low > high` and
`high >= n_elem_this_dim` **inside the range (`v[lo:hi]`) branch only**. A SINGLE index
returned unchecked, so

```spice
let vx[100] = 1        # on a 66-element vector
```

walked into the byte-offset arithmetic and performed a **heap-buffer-overflow WRITE** --
memory corruption from an ordinary typo. The range form `vx[0:999]` was correctly
rejected all along.

Fix: move both checks out of the range branch so a single index is validated too. Reads
are unaffected (`op_ind` clamps an out-of-range read index, Enhancement-274), and every
valid assignment behaves as before.

## Verify

```
python3 verify_letidxoob.py
```

Six checks: `let w[10]=99`, `let w[999]=99`, `let w[1e308]=99` rejected cleanly; the
last valid index and a mid-vector assignment still assign; the range form still rejected.
