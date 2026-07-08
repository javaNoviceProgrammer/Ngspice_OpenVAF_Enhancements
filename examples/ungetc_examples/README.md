# ungetc_examples — the `$ungetc` file-input function (Enhancement-108)

`$ungetc(c, fd)` pushes character `c` back onto the input stream so the next
`$fgetc(fd)` returns it — the standard one-character peek/pushback that
complements the `$fgetc` added in Enhancement-107. It returns `c` on success.

`ungetc_demo.va` reads a character, `$ungetc`s it, and confirms the next
`$fgetc` returns the same character, then performs the classic one-character
look-ahead: it accumulates the file's leading decimal digits into an integer
(`"4271;…"` → `4271`) and `$ungetc`s the first non-digit (`;`) so it stays in
the stream. Run: `python3 verify_ungetc.py` (6 checks).
