# helpcmd_examples — Enhancement-174, Enhancement-753 and Enhancement-788

```
python3 verify_helpcmd.py
```

27 checks ([9]'s two hold the internals document `ngspice_commands.md` to the binary's `help all`). Not a circuit simulation, so the dual-solver harness does not apply.

**[1]–[4], [E-174](../../enhancements_doc/Enhancement-174.md): `help` must not
crash.** Each help string is passed to printf as the format, so a bare `%` in
one killed `help all`. An interactive ngspice on a pty runs `help`, `help all`
and `help montecarlo` to completion and renders the literal "95% CI", and a
static scan of `commands.c` refuses any help string with a format hazard.

**[5]–[8], [E-753](../../enhancements_doc/Enhancement-753.md): `help all`
lists every command, one line each.** The listing counted the table up to the
first command without a handler, so the eleven control keywords and the
seventeen commands after them were never shown, and a few texts broke the
one-line form (`setscale`'s embedded newline among them).

- **[5]** every line of the `help all` list has the form `name args : text.`
  with no continuation line, no blank line inside it, the separator, a final
  period and single spacing; the list is sorted.
- **[6]** the listed names are exactly the table's names that `help <name>`
  answers in this build (165), the 28 from `while` down included.
- **[7]** `help setscale` is one line; `help` alone, an unknown name and the
  manual links behave as before.
- **[8]** `newhelp` at the advanced level lists the keywords too.

On the E-752 binary 9 of 18 pass.

**[10], [E-788](../../enhancements_doc/Enhancement-788.md): `help optimize`
describes every option.** The one-line text had stayed at E-145's options (two
of the nine methods, nothing of `-center`, `-constrain`, `-polish` or
`-starts`); `help optimize` now prints a full description beneath it, kept
beside the parser in `com_optimize.c`.

- **[10]** the description follows the one-line text after a blank line; every
  flag and alias (39) and every `-method` name (31) the parser accepts appears
  in it, scraped from the source, and every result the command publishes; it
  fits 79 columns with only its section headers in column 0; `help all` keeps
  optimize to one line naming the nine methods; the three examples run as
  printed on the deck the description names (R2 = 1k; is and n fitted;
  R2 = 1.5k with the constraint met).

On the E-787 binaries 8 of 27 fail ([9]'s description check and all seven of
[10]).
