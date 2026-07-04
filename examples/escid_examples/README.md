# escid_examples — escaped identifiers + integer literal bases (Enhancement-46)

Demonstrates **escaped identifiers** (`\name-with-specials `, LRM A.9.3) and
**integer literal bases** (`[size]'[s]d/h/o/b`, LRM A.8.7) — using the committed
`openvaf-r` and `ngspice-46`.

## What was broken

- **Based literals didn't exist**: `'h1F`, `'o17`, `'b1010`, `'d42`, `8'hFF`,
  `8'shFF` were all "encountered unexpected token" — the lexer had only a
  commented-out sketch of based-number tokenization. Worse, the LRM-legal
  underscore separator (`1_000_00`) **crashed the compiler** ("IntNumber token
  must be valid float syntax too"): the lexer ate the underscore but value
  parsing didn't strip it.
- **Escaped identifiers half-worked**: the lexer already emitted
  `EscapedIdent` tokens, but `Name::resolve` stripped the identifier's *last
  character* along with the backslash — so `\foo` never named the same thing
  as plain `foo` (the LRM equivalence), and the compiler's own `std.va`
  snapshot had quietly baked in `logi` for the escaped `\logic` discipline.
  The E-5 flattening also re-rendered instance-prefixed names unescaped,
  breaking any escaped net inside a submodule.

E-46 tokenizes based literals with per-base digit validation (an invalid
digit or a bare `'h` is an ordinary parse error, never a silent zero), masks
to the declared size and sign-extends under `s`, strips `_` separators in
every number form, fixes the escaped-name normalization, and teaches the
elaboration renderer to re-escape substituted names when they need it.

## Run

```
python3 verify_escid.py
```

Checks (ALL PASS): every literal form in one module sums to exactly
0.1443252345 V (hex/octal/binary/decimal, sized `8'hFF`=255, signed
`8'shFF`=−1 and `4'sb1000`=−8, `'hFFFFFFFF`=−1 32-bit wrap, separators in
`1_000_00`, `16'hAB_CD`, `1_234.5`); escaped nets/variables/parameters with
specials (`\2wire`, `\value#`, `\r+val`); `\mid` ≡ `mid` (one net); an escaped
net inside a flattened submodule; the keyword spelling `\module` as a net
name; and four malformed literal forms rejected cleanly.
