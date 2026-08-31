# lrmlex — the lexical layer and compiler directives vs. the LRM (Enhancement-515)

An LRM-2023 conformance audit of clauses **2** (lexical conventions) and **10**
(compiler directives), plus Annex B, found five outright bugs, four missing
directives/features, and a handful of silently-accepted illegal forms in the
lexer and preprocessor. This suite pins the fixes end-to-end through the
committed `openvaf-r` + `ngspice`:

- **White-space-separated and macro-substituted based literals** (LRM 2.6.1):
  `5 'D 3`, `12'b 0011_0101_0001`, `` `SZ'hFF ``, `'h 837FF`, `8'sh FF` — all
  evaluated at run time (3, 849, 255, 538623, −1) next to the contiguous forms.
- **Predefined macros** (10.4/10.5): `` `__VAMS_ENABLE__ `` is defined,
  `` `undef `` can no longer remove a predefined macro (warns instead), and a
  user `` `define `` in the `__VAMS_` namespace warns.
- **`assert`, `root`, `do` as identifiers** (Annex B reserves none of them);
  `do` stays contextual so the do-while extension is unaffected.
- **Expression-position attributes** (2.9) and last-wins duplicate attributes.
- **`` `begin_keywords ``/`` `end_keywords ``** (10.6) with validated version
  specifiers, and a working `` `resetall ``.
- **`` `__FILE__``/`` `__LINE__ `` next to a relative `` `include ``**
  (`srcloc.va`) — the rewrite used to lose the include directory.
- **Illegal forms now refused**: `1.`, a string spanning a raw newline, and a
  white-space based literal whose digits don't fit its base.

Run `python3 verify_lrmlex.py` — 26 checks, both solvers.
