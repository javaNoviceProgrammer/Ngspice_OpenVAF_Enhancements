#!/usr/bin/env python3
"""
verify_vafcrash.py -- Enhancement-213: openvaf-r crash hardening.

Fuzzing the compiler with malformed Verilog-A found four distinct panics: instead
of reporting a diagnostic, openvaf-r aborted with "OpenVAF encountered a problem
and has crashed!" (exit 101) and wrote a crash log telling the user to file a bug.
Every one is reached from ordinary, plausible source mistakes -- most notably a
module that is simply missing its `endmodule`. See Enhancement-213.md.

The four root causes, all fixed:

  [eof-span]  syntax/src/parsing/tree_builder.rs -- a parse error at end of file
        built its span as TextRange::at(text_pos, <len of the LAST token>), i.e.
        a span starting at EOF and running *past* the end of the file (`6..12`
        for the 6 byte input "module"). Mapping it back to the source tripped an
        assert in FileSpan::with_subrange. The error belongs *at* EOF -> empty
        range. syntax/src/lib.rs additionally clamps find_ctx_range, whose
        half-open [start,end) ranges never cover the EOF position itself.

  [real-lit]  lexer/src/lib.rs -- `e`/`E` was consumed as an exponent marker even
        with no exponent after it, so `1e` lexed as a Float whose text does not
        parse as an f64 and panicked in StdRealNumber::value()'s unwrap(). An `e`
        is now only part of the number when digits (optionally signed) follow.

  [pp-eof]    preprocessor/src/parser.rs -- previous_range() and
        followed_by_bracket_without_space() indexed the token list directly, which
        is out of bounds at end of file (a bare "`define" ending the file).

  [path-assert] parser/src/grammar/paths.rs -- path() asserted its precondition
        (`assert!(p.at_ts(PATH_SEGMENT_TS))`), which several callers violate on
        plausible input: `aliasparam x = 5;` (a literal where a parameter name
        belongs), `I(<1>)`, a discipline member that is not an identifier.

Each check confirms the input now yields a clean ERROR (nonzero exit, no panic)
and that valid code still compiles unchanged.
"""
import os
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF

checks = passed = 0
def check(label, ok, detail=""):
    global checks, passed
    checks += 1; passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))

D = os.path.join(tempfile.gettempdir(), "vafcrash213")
os.makedirs(D, exist_ok=True)
HDR = '`include "disciplines.vams"\n'

def wr(name, content):
    p = os.path.join(D, name)
    with open(p, "w") as f:
        f.write(content)
    return p

def run(path, timeout=20):
    """(verdict, output, seconds); verdict in OK / ERROR / CRASH / HANG.

    NOTE: openvaf-r installs its own panic hook -- it prints "OpenVAF encountered
    a problem and has crashed!" and exits 101 rather than dying on a signal or
    printing the usual "panicked at". A crash check that only looks for those two
    (as Enhancement-148's does) would score these panics as ordinary errors, so
    exit code 101 and the hook's message are both treated as CRASH here.
    """
    t = time.time()
    try:
        r = subprocess.run([OPENVAF, path, "-o", os.path.join(D, "out.osdi"), "-I", D],
                           capture_output=True, text=True, timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG", "", time.time() - t
    out = (r.stdout or "") + (r.stderr or "")
    dt = time.time() - t
    low = out.lower()
    if (r.returncode is not None and r.returncode < 0) or r.returncode == 101 \
            or "panicked at" in low or "encountered a problem and has crashed" in low:
        return "CRASH", out, dt
    return ("OK" if r.returncode == 0 else "ERROR"), out, dt

print("Enhancement-213: openvaf-r crash hardening (EOF span / real literal / preprocessor EOF / path assert)")

# ---- [eof-span] a parse error whose span reaches end of file ----
# The headline case: a perfectly well formed module that is simply missing its
# `endmodule` -- one of the most common Verilog-A editing mistakes.
eof_cases = [
    ("module missing `endmodule`",
     HDR + "module m(inout a,b); electrical a,b; analog V(a,b) <+ 1e3*I(a,b);\n"),
    ("bare `module` keyword", "module"),
    ("module with no body", "module m"),
    ("module header then EOF", "module m(a);"),
    ("unclosed `analog begin`",
     HDR + "module m(inout a,b); electrical a,b; analog begin\n"),
    ("unterminated string literal",
     HDR + 'module m(inout a,b); electrical a,b; analog $strobe("oops); endmodule\n'),
]
for name, src in eof_cases:
    v, o, dt = run(wr("eof.va", src))
    check(f"[eof-span] {name} -> clean error, no crash", v == "ERROR", v)

# ---- [real-lit] real number with an exponent marker but no exponent ----
for name, expr in [("1e", "1e"), ("1e+", "1e+"), ("99e", "99e"), ("1.5e", "1.5e")]:
    src = HDR + f"module m(inout a,b); electrical a,b; analog V(a,b) <+ {expr}; endmodule\n"
    v, o, dt = run(wr("real.va", src))
    check(f"[real-lit] `{name}` -> clean error, no crash", v == "ERROR", v)
# also as a parameter default, which reaches value() from a different path
v, o, dt = run(wr("realp.va", HDR +
                  "module m(inout a,b); electrical a,b; parameter real p=2e;\n"
                  "analog V(a,b) <+ p*I(a,b); endmodule\n"))
check("[real-lit] `parameter real p=2e` -> clean error, no crash", v == "ERROR", v)

# ---- [pp-eof] preprocessor directives that end the file ----
# What Enhancement-213 guarantees for all of these is "does not crash". Most are
# also a diagnosed error; a bare `undef is simply accepted as a no-op by the
# preprocessor (it was never a crash, and making it an error is out of scope).
for name, src, want_err in [("bare `define", "`define", True),
                            ("`define with unclosed arg list", "`define M(a", True),
                            ("bare `undef", "`undef", False),
                            ("bare `ifdef", "`ifdef", True),
                            ("bare `include", "`include", True)]:
    v, o, dt = run(wr("pp.va", src))
    if want_err:
        check(f"[pp-eof] {name} -> clean error, no crash", v == "ERROR", v)
    else:
        check(f"[pp-eof] {name} -> accepted as a no-op, no crash", v in ("OK", "ERROR"), v)

# ---- [path-assert] callers that reach path() not at a path segment ----
path_cases = [
    ("aliasparam with no value",
     HDR + "module m(inout a,b); electrical a,b; aliasparam x = ;\n"
           "analog V(a,b) <+ I(a,b); endmodule\n"),
    ("aliasparam bound to a literal",
     HDR + "module m(inout a,b); electrical a,b; aliasparam x = 5;\n"
           "analog V(a,b) <+ I(a,b); endmodule\n"),
    ("port flow `I(<1>)`",
     HDR + "module m(inout a,b); electrical a,b; analog V(a,b) <+ I(<1>); endmodule\n"),
    ("port flow `I(<>)`",
     HDR + "module m(inout a,b); electrical a,b; analog V(a,b) <+ I(<>); endmodule\n"),
    ("discipline member that is not an identifier", "discipline d 1 = 2; enddiscipline\n"),
]
for name, src in path_cases:
    v, o, dt = run(wr("path.va", src))
    check(f"[path-assert] {name} -> clean error, no crash", v == "ERROR", v)

# ---- regression: valid code must still compile unchanged ----
valid = {
    "resistor": HDR + "module res(inout a,b); electrical a,b; parameter real r=1000.0;\n"
                      "analog V(a,b) <+ r*I(a,b); endmodule\n",
    "real exponents (1.5e3, 2e-3, 1E6)":
        HDR + "module m(inout a,b); electrical a,b; parameter real p=2e-3;\n"
              "analog V(a,b) <+ 1.5e3*I(a,b) + p + 1E6*0.0; endmodule\n",
    "aliasparam bound to a real parameter":
        HDR + "module m(inout a,b); electrical a,b; parameter real r=1000.0;\n"
              "aliasparam res = r;\n analog V(a,b) <+ r*I(a,b); endmodule\n",
    "`define with args + expansion":
        "`define TWICE(x) ((x)*2)\n" + HDR +
        "module m(inout a,b); electrical a,b; analog V(a,b) <+ `TWICE(500)*I(a,b); endmodule\n",
}
for name, src in valid.items():
    v, o, dt = run(wr("ok.va", src))
    check(f"[regression] valid: {name} still compiles", v == "OK", f"{v} {o[:150]}")

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
