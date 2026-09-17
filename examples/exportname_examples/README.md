# exportname_examples — an exported name ngspice cannot reach is reported at compile time (Enhancement-652)

Nineteen checks per solver, run under both KLU and Sparse by `_setup.check_both_solvers`.

Verilog-A is case-sensitive; ngspice folds every name to lower case and keeps two flat
tables per device: the instance's parameters, aliases and operating-point variables (with
the simulator's own `m`/`temp`/`dtemp`/`dt` and the terminal currents E-394 synthesizes),
and the model's parameters and aliases. Two entries that fold to one name are one name to
`@inst[name]`, `show` and `alter`: the first in the table wins and the other is unreachable.
ngspice warns at load time; the author compiling the model never saw it. A `$` in an
exported name is read by ngspice's expression parser as a shell variable, so the name is
write-only.

The checks: an instance parameter beside a variable differing only by case (the parameter
wins, as ngspice confirms), two variables (the earlier wins), an alias beside a variable,
two model parameters (with the `@<model>`/`showmod`/`altermod` spelling), two aliases of
different parameters; variables named `m`, `temp`, `dt` (ngspice's own wins) and `i_p`/`i`
(shadowing the synthesized terminal currents); a `$` in a model parameter, an instance
parameter, an alias (write-only) and a variable (not exported), while the `x$ps` twin a
paramset creates is not reported. Not reported: a model parameter beside a variable (two
tables, both reachable), a parameter and its own alias, `dtemp` (L029's), a variable
without `desc`/`units`, and a declaration carrying `openvaf_allow`.

```bash
python3 examples/exportname_examples/verify_exportname.py
```
