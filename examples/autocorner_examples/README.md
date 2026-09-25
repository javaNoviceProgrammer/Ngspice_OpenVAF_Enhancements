# autocorner_examples — Enhancement-656

`.option autocorner`: every run-class command (`op`, `tran`, `ac`, `dc`,
the batch-mode `run`, the shared library's) runs at the nominal `tt` and
then at every process corner the loaded Verilog-A models declare
(`(* corner=... *)`, E-654). The per-corner plots are kept, named with
their corner, so batch `.print` cards print each corner; and a combined
`autocorner<n>` plot is made current with the nominal's vectors under their
names and each corner's as `<name>_<corner>` (`v(out_ss)`), resampled onto
the nominal's scale — the form a schematic host reads. The option is inert
inside loop commands and without a declared corner; the `corner` variable
is put back afterwards.

Since [E-666](../../enhancements_doc/Enhancement-666.md) (hunt F8): a
raw-file `run <file>` puts every corner's plot in the file, each named with
its corner; `meas` reads the combined plot as its nominal's analysis;
`writemc` on it puts each value on every corner's row; the copies keep
their accessor readable (`i(v1_ss)`, `@rm_ss[rsh]`); and the devices follow
the `corner` variable when the loop ends.

Run: `python3 verify_autocorner.py` (26 checks per solver, both solvers).

Since [E-725](../../enhancements_doc/Enhancement-725.md) (check [21]): `.option saveused`
beside the option saves the base of a corner copy the block reads — `print v(out_ss)`
alone runs the pass and holds `out_ss`, the option still pruning the rest.

## Enhancement-724: batch `.meas` cards name their corner

Since [E-724](../../enhancements_doc/Enhancement-724.md) (five-options dig, F8 of
2026-09-25) a batch `.meas` under the option prints `autocorner: measures at corner
<name>` once before each run's first result — the three corners' values printed in
turn with nothing to tell them apart before. Check [16]: three headers, `tt`, `ss`,
`ff`, each before its own values; a plain batch run prints none.
