# arrayrange_examples — Enhancement-636

An out-of-range array index at run time is reported. A dynamic index (a
parameter, or a value computed while solving) outside the array's declared
range read the first element and dropped the write with nothing said; now
every dimension is checked and the access is reported through the deferred
`$warning` path, once per accepted point, naming the array, the index and
what the access does instead (`index [3] of `a`, declared [0:2], is out of
range; the read returns a[0]` / `the assignment is dropped`). The first-element
read of E-489 stands. A constant index is refused at compile time as before,
now worded for an array (`array index out of range … the array 'a' is
declared [0:2]`) rather than a bus.

Run: `python3 verify_arrayrange.py` (9 checks per solver, both solvers).
