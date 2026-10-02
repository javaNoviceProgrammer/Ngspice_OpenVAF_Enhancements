# Enhancement-774: a voltage or current source's prbs and pam4 rows were errors, printed with an unset row count — three times on macOS and without end on aarch64 Linux, which ran the linux-arm CI runner out of memory in every suite whose operating point printed a source; the source answers both keywords, a failed query is one row, and the sweep holds known platform gaps out by name

**Scope:** ngspice: `spicelib/devices/vsrc/vsrcask.c`, `spicelib/devices/isrc/isrcask.c`
(the `prbs` and `pam4` queries), `frontend/device.c` (`printvals`, `printvals_old`).
Examples: `_setup.py` (`PLATFORM_EXCLUDE`, `platform_key`, `platform_excluded`),
`run_regression.py` (the per-platform exclusion), the prbs suite (section [11]).

**Suites:** prbs 44 per solver (the E-769 binaries fail both new checks); the full sweep,
536 of 536.

## What was wrong

With E-773's watchdog the linux-arm CI sweep ran to its end for the first time (run
37018886859): 507 of 536, 28 suites stopped for memory and one timed out. The watchdog's
reports named the decks -- the smallest a 1 kΩ resistor and a DC source under `.op` -- and
one caught the output: `<<NAN, error = 7>>`, over and over.

A batch `.op` prints a table of every device's parameters. E-752 added `prbs` and `pam4` to
the voltage and current sources' parameter tables, but `VSRCask` and `ISRCask` had no case
for either, so every source answered both with E_BADPARM. `printvals_old` printed the error
-- and then returned the parameter's row count read from the `IFvalue` the failed query had
not filled in, and its caller prints row after row until that count runs out. On macOS the
stack happened to hold a 3 (every source's table carried six error rows, unremarked); on
x86-64 Linux a small number; on aarch64 Linux a number large enough that ngspice wrote the
row at some 70 MB/s until the 16 GB runner had nothing left. `printvals`, the `show` table's
newer printer, ignored the error altogether and read the unset vector.

## What changed

- `VSRCask`, `ISRCask`: `prbs` and `pam4` answer. Both are a PRBS function, told apart by the
  register's level count (2 or 4); as for the other waveforms (E-447), only the active one
  answers with the description, any other is empty (`-`).
- `printvals_old`, `printvals`: the value is zeroed before the query; a failed query is one
  row (`<<NAN, error = N>>` in the old printer, `-` in `show`'s), never a length read from
  memory the query did not write.
- `_setup.py`: `PLATFORM_EXCLUDE`, examples held out of the routine sweep on one platform for
  a recorded reason -- a known gap there, not a pass -- keyed by system and machine
  (normalised to aarch64 / x86_64, `*` for any system). The sweep names every one it skips;
  `--all` runs them. The first entries are the x86-64 gaps: `arrayscale`, `cubic_table` and
  `table_model` (code generation of huge modules: 554 s for a 10 000-entry instance array,
  past 120 s, past the 20-minute limit on the Linux runner) and `collapsestate` (Sparse `sens`
  of a collapse-selecting parameter, 2.5x off on x86-64, Linux and macOS alike). The linux-arm
  runaway is fixed above and needs no entry.

## Checks

prbs [11]: a batch `.op` of a DC, a PRBS and a PAM4 voltage source and a PRBS current source
prints the source tables with no error row; `show` lists `va`'s eight PRBS values under
`prbs` and `-` under `pam4`, `vb`'s three PAM4 values the other way round, and the current
source's three under `prbs`. Both fail on the E-769 binaries. With the host reported as
x86-64 Linux, the sweep names the four held-out suites with their reasons and runs the
other 532.

## Limits

- The x86-64 entries are open problems held out, not fixed.
