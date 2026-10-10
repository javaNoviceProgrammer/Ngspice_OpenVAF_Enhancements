# sourcenest_examples — Enhancement 843

[E-843](../../enhancements_doc/Enhancement-843.md), F6 of the
[2026-10-10 robustness and correctness campaign](../../docs/bug_hunts/2026-10-10_ngspice-openvaf-r-robustness-and-correctness-campaign.md).

A deck that `source`s itself, two decks that source each other, or a `.spiceinit` that sources
itself recursed until the stack overflowed: SIGSEGV after about 3 900 levels. `source` now stops
at 50 levels, the limit `.include` has had since Enhancement-212, and fails as a missing file
does. In batch mode ngspice exits with status 1. Under `set interactive` it drops to a prompt.

That prompt had two defects of its own:
- **It ran away at the end of its input.** The lexer had no case for EOF; it grew its buffer
  until a 2 GB realloc failed.
- **Each command typed there ran twice.** The prompt recorded its commands on the control
  level of the block that ran `source`, and that block's loop ran them again.

- **[1]** A deck that sources itself: refused at level 50, exit 1.
- **[2]** Two decks that source each other: the same.
- **[3]** A `.spiceinit` that sources itself: the same, before the deck is read.
- **[4]** A chain of 50 nested sources runs to the bottom (control).
- **[5]** A chain of 51 is refused at the 51st.
- **[6]** 60 sources one after another in a `repeat` loop all run (control).
- **[7]** `ngspice -i` with its input at end of file: refused, the prompt ends, exit 0.
- **[8]** A command typed at that prompt runs once.
- **[9]** The same prompt after a missing file: the command runs once, and the block goes on.

[7] to [9] pipe their input, and run on POSIX systems only.

Run: `python3 verify_sourcenest.py` (9 checks; 7 fail on the E-840 binaries, the other 2 are
controls).
