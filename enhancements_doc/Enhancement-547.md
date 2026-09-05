# Enhancement-547: `pyplot` quotes its launch and judges its exit status

**Scope:** defects 1 and 2 of a review of the `pyplot` command (its
implementation is in `src/frontend/com_pyplot.c` and
`src/frontend/plotting/pyplot.c`; its reference is
[`docs/internals/ngspice_internals/ngspice_pyplot.md`](../docs/internals/ngspice_internals/ngspice_pyplot.md)).
The review found six defects and ranked five improvements; this and the four
enhancements that follow (E-548 to E-551) work through them in order.
**ngspice only; the compiler is unchanged.**

**Suites:** [`pyplot_examples`](../examples/pyplot_examples/) 17 → 24; the
seven other pyplot suites, `eye` and `rfplots` pass.

## The review, for the record

The command was in good shape — eight render modes, twenty-five settings, a
thorough reference, seven example suites — and everything found lived in the
plumbing around matplotlib, not in the plots:

| # | defect | fixed in |
|---|---|---|
| 1 | a deck folder with a space or an apostrophe in its path broke the launch | E-547 |
| 2 | a failing Python was invisible to ngspice: exit status 0, no image | E-547 |
| 3 | the data table carried six significant digits | E-548 |
| 4 | `ylimit` was silently dropped under `ylog` | E-548 |
| 5 | a voltage and a current shared one unlabelled axis | E-548 |
| 6 | the generated script only ran from the directory ngspice ran in | E-548 |

and the improvements: a binary data format (E-549), envelope decimation of
long traces (E-550), engineering ticks and typed labels (E-551), a default
for batch mode without a terminal, and a handful of smaller items — those two
remain open.

## What was wrong

Since Enhancement-183 the script and data are written next to the deck when
the deck is given with a path, and the command line that ran the script was
built unquoted through `system()`. With `~/My Circuits/rc.cir`, Python was
told to open the file `My`; with an apostrophe in the folder name the shell
reported an unterminated quote. The `.py` and `.data` were written, no image
was, and ngspice went on with exit status 0. The apostrophe also reached the
script's own `print('pyplot: wrote …')` line unescaped.

And only a return of −1 from `system()` was ever looked at. A missing
interpreter, or a missing matplotlib, printed Python's own error, the deck
continued, and ngspice exited 0 with no image — a silent green in a CI deck.

## What changed

* **One launch path for the five renderers**, `pyplot_run()`. The script path
  is shell-quoted (single quotes on POSIX with the `'\''` spelling for an
  embedded apostrophe; double quotes on Windows, where `start` now gets its
  empty title argument and the hardcopy line the extra outer pair cmd.exe
  strips). `pyplot_python` is still spliced verbatim so it can carry options
  such as `/usr/bin/env python3`; a value that names an executable file is
  quoted, so an interpreter path with a space is one word.
* **The exit status is judged.** A hardcopy is waited for; a non-zero exit
  prints an ngspice-side error naming the interpreter, the status and the
  image that was not written, and every `pyplot` publishes **`pyplot_status`**
  the way `shell` publishes `shellstatus`, so a batch deck can
  `if $pyplot_status ne 0 … quit 1`. A window is launched in the background,
  where nothing can be waited for; on POSIX the background shell prints the
  status if the viewer later fails.
* **The script's own "wrote" line** quotes the file name as a Python literal.

One thing the work turned up in its own test: ngspice lower-cases an
unquoted `set` value, so a path set without quotes only works on a
case-insensitive file system. The test quotes it.

## Verification

| check | result |
|---|---|
| a deck folder named `with space`, run by absolute path | the PNG is written (was: Python opened `…/with`) |
| a deck folder named `it's` | the PNG is written (was: an unterminated quote) |
| an interpreter that exits 3 | `Error: pyplot: … exited with status 3; status.png was not written`, `pyplot_status` = 3, no image |
| a missing interpreter | status 127, the same message |
| a success | `pyplot_status` = 0 |
| `pyplot_python="/usr/bin/env python3"` | still works |
| an interpreter path with a space | one word |
| `pyplot_examples` | 24 / 24, both solvers |
| full sweep | 455 of 455 |
