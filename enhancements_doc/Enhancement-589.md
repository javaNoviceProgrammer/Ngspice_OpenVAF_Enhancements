# Enhancement-589: `show` and `showmod` print every name and value in full

**Scope:** `src/frontend/device.c` (the classic `show`/`showmod` table: a per-batch
width pass, and every `%*.*s` of that printer made a `%*s`),
`examples/showwidth_examples/` (new, 19 checks per solver). **ngspice only.** Hunt
finding F7 of 2026-09-08.

**Suites:** [`showwidth_examples`](../examples/showwidth_examples/) 19 of 19 per
solver, both solvers; every suite that reads `show` output passes unchanged; full
sweep 484 of 484.

## What was wrong

The table `show` and `showmod` print has a name column and one column per device.
Both widths were compile-time constants, `LEFT_WIDTH` 11 and `DEV_WIDTH` 21, and both
were used as the *precision* of the format as well as its width (`"%*.*s"`), so any
text longer than the column was cut without a word:

```
 lnm models (A simulator independent device loaded with OSDI)
      model                    lm
averyveryve                     7        <- averyveryverylongparametername
twelve_char                    12        <- twelve_chars
```

A Verilog-A model with the ordinary long parameter names of a compact model, an OSDI
hierarchy whose child parameters are mangled to `l1__deep_parameter_name_in_child`,
a 30-level chain whose parameters all listed as `a__a__a__a_`, an instance name of
35 characters, a model name, or a string parameter value longer than 21 characters:
each lost its tail in the one listing meant to show it, while
`print @lm[averyveryverylongparametername]` printed the value under the full name.
`show` and `showmod` are the commands a user reaches for to see what a model has;
they were the one place a name could not be read back.

## What changed

The widths are decided per table, from what the table will print, and nothing is
truncated any more.

* `show_set_widths` runs once per batch of devices (each turn of the device loop in
  `all_show_old`). The name column is the longest keyword the batch will list — the
  same filter `param_forall_old` applies (askable, not redundant, set or solved,
  interesting unless `all`) — plus any explicit names after `:`, and never narrower
  than the classic 11. The device columns start at the classic 21; the batch's
  instance and model names are measured, and if one is wider the columns widen and
  the number of devices per row is recomputed from `width` (fewer fit, and with fewer
  in the batch the longest name can only get shorter, so one pass settles it). A name
  wider than the screen gets one device per table rather than a cut name.
* Every `%*.*s` of the classic printer is now `%*s`: parameter names, the `device`
  and `model` header rows, string and instance-valued cells, the `---------` and
  `?????????` rows, and the `-` placeholder of a vector value that is not there —
  which is now padded to the column, so it sits under the numbers instead of ten
  characters in. A cell that is still wider than its column overflows it; it never
  loses characters.
* Short names produce the classic table byte for byte (`show r1`, `showmod dm`
  compared against the old output in the suite). `show -v`, the `altshow` layout,
  `print @dev[name]` and the E-491 unknown-name warning are untouched.
* A device type with no model parameter table (a `vsource` when `showmod all` walks
  every type) has a NULL count pointer; the width pass checks it the way the printer
  already did.

```spice
show n1                       * 30-character instance parameter name in full
showmod mm                    * l1__deep_parameter_name_in_child, a 49-character string value
set width=200
show nlong_a nlong_b          * two 35-character instance names on one header row
```

## Verification

| check | result |
|---|---|
| `showmod`: 31- and 12-character model parameter names, a 32-character mangled child name, a 49-character string value | each printed in full with its value, all names right-aligned to one 32-wide column |
| `show`: a 30-character instance parameter name; `device`/`model` header labels | in full; the labels sit in the same 30-wide column |
| two 35-character instance names | at `width` 80 one table each; at 200 one header row with both, values on one row |
| short names (`show r1`, `showmod dm`) | the classic 11 + 1 + 21 layout, byte for byte |
| `width` 40, narrower than the name | the full name, one device per table |
| explicit names after `:`, an unknown 33-character name | the column widens for them; the unknown one prints in full on its `?????????` row with the E-491 warning |
| `show all` and `showmod all` with model-less devices present | run to completion (the NULL-table guard) |
| an unset vector parameter's `-` | ends in the value column, like a number |
| array elements `w[1]` | listed under their bracketed names |
