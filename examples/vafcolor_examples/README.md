# vafcolor_examples — openvaf-r colours a diagnostic only on a terminal

Found on 2026-09-07 when a regression sweep run from an ordinary terminal failed five
suites that a harness with `TERM` unset had just passed: `lrmdisc`, `lrmfuncs`,
`natureref`, `vafdeterminism`, `vafice`. All five parse the compiler's diagnostics, and
from a colour terminal every diagnostic the compiler wrote into a pipe carried ANSI
escape codes. The line that reads `error: …` on the screen began with
`\x1b[0m\x1b[1m\x1b[38;5;9m` in the captured text, so `startswith("error:")` was false
and a line-by-line hash of the output changed with the terminal type.

The cause was termcolor's `ColorChoice::Auto`, which consults `TERM` and `NO_COLOR` and
never the stream. Enhancement-574 makes every stream the compiler colours — diagnostics,
`Finished building`, `--lints`, `--supported-targets`, the crash report, the top-level
error — ask whether it is a terminal first.

| check | what it pins |
|---|---|
| [1] into a pipe with `TERM=xterm-256color` | a diagnostic, the `Finished` line, `--lints` and `--supported-targets` are plain text; the first diagnostic line begins with `error:` at column 0; `TERM=dumb` is plain as before |
| [2] on a pseudo-terminal | the same runs ARE coloured, and `NO_COLOR=1` or `TERM=dumb` still turn the colour off — the terminal case keeps termcolor's own policy |

## Run

```
python3 verify_vafcolor.py
```

10 checks, all PASS. Compiler only; ngspice is not involved.
