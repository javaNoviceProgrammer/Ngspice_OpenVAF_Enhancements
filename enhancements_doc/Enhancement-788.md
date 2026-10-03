# Enhancement-788: `help optimize` describes every option — the full description beneath the one-line text, with the methods, the results and examples that run

**Scope:** ngspice: `frontend/com_optimize.c` (`com_optimize_help[]`), `frontend/com_optimize.h`,
`frontend/com_help.c` (`help_details`, `help_detail`), `frontend/commands.c` (optimize's one-line
text). Docs: `docs/internals/ngspice_internals/ngspice_commands.md` (the generated `help all` table
and the hand-written row), `docs/handbook/03-ngspice-workflows.md`. Examples: helpcmd (seven new
checks).

**Suites:** helpcmd 27 of 27 (8 fail on the E-787 binaries: [9]'s description check and all
seven of [10]); the full sweep, 536 of 536.

## What was wrong

`help optimize` printed the command table's one line, and that line had stayed at the options of
E-145: `[-method nm|lm]`, "Nelder-Mead / least-squares Levenberg-Marquardt". Seven of the nine
methods (tr, pso, de, sa, cmaes, bayes, nsga2), design centering (`-center`, `-spec`, `-samples`,
`-lhs`), constraints (`-constrain`, `-ctol`), `-polish`, `-starts`, `-seed`, `-swarmsize`, the
short and alias spellings, and everything a script reads afterwards (`optimize_status` and the
rest) were nowhere in it. The command accepts 39 flag spellings and 31 method names; the only
complete accounts were the source, the handbook and the optimizer manual
(`ngspice_optimizer.md`), none of them at the prompt.

## The change

`help optimize` prints a full description of 127 lines beneath the one-line text, after a blank
line:

| Section | What it gives |
|---|---|
| Usage | the shape of the command |
| Knobs | `-param`, `-mparam`, `-dparam` with their short forms, what each sets and how, the 128 limit, the scaled search |
| Analyses | `-analysis` and its stages, the limit of 8 |
| Objective | `-minimize`, `-target` (weights), `-center` with `-spec`, `-samples`, `-lhs`, the nsga2 objectives with `-maximize`; when `-min` means `-minimize` |
| Expressions | which options take several words, which take one, how to start an expression with `-` (double quotes or `0-`), the last value being read |
| Constraints | `-constrain`, `-ctol`, what the report says |
| Methods | all nine with every alias, which are local and which global, the defaults |
| Options | `-maxiter` (what it counts per method), `-tol`, `-swarmsize` (each method's default), `-seed`, `-polish`, `-starts`, `-verbose` |
| Results | where the circuit is left, what the report notes, every published name and when it is set, Ctrl-C, `.option osdimc` |
| Examples | three, on a deck the text names: a scalar minimum, a weighted two-knob fit of a diode, a constrained CMA-ES run with `-polish` |

The text is an array of lines in `com_optimize.c`, beside the parser, so an option is described
where it is added. `com_help.c` keeps a table of such descriptions -- optimize's is the first --
and prints the one for a command after its line, with `out_send`, so the text takes no printf
conversion. `help all` is unchanged in form: one line per command (E-753); optimize's line now
names the nine methods, `-center`, `-constrain`, `-polish` and `-starts`, and says that
`help optimize` describes every option. The table in the internals document was regenerated
from the binary, and its hand-written row for optimize rewritten.

## The checks

helpcmd [10], seven checks:

- the description follows the one-line text after a blank line;
- every flag and alias the parser accepts (39) appears in it, scraped from `com_optimize.c`, so a
  flag added without being described fails;
- every `-method` name the parser accepts (31) appears in it;
- every result the command publishes (the 8 names it sets, with `optimize_<name>` and the
  `pareto` vectors) is named;
- it fits 79 columns, and only its section headers start in column 0, so [6], which reads
  `help <name>` output for command names, cannot take a line for one;
- `help all` keeps optimize to one line naming the nine methods;
- the three examples run as printed on the deck the description names: R2 = 1k; is and n fitted
  to 1.13e-13 and 1.21; R2 = 1.5k with `v(out) <= 0.6` met.

## Limits

- Only optimize has a full description. The table in `com_help.c` takes others (sweep,
  montecarlo, track ...) as one entry each.
- `help optimize` follows `set moremode` paging like `help all`; in batch mode and on a pipe it
  prints straight through.
