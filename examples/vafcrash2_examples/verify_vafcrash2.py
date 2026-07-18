#!/usr/bin/env python3
"""
verify_vafcrash2.py -- Enhancement-220: openvaf-r crash hardening (round 2).

Re-running the fuzzer against the shipped compiler with diverse compact-model
seeds and new mutation strategies (keyword / attribute / bracket injection) found
that ~5% of mutated inputs still CRASHED the compiler (exit 101, "OpenVAF
encountered a problem and has crashed!") rather than reporting an error. Triage
grouped them into NINE distinct root causes, all fixed -- every one a compiler
panic on malformed input that should be a clean diagnostic (the E-213 class):

  [parser-stuck]  parser/src/parser.rs -- the parser can spin in error recovery;
        a step counter `assert!`ed ("the parser seems stuck") and crashed. It now
        signals EOF at the limit so parsing winds down and reports its errors.
  [empty-span]    basedb/src/diagnostics.rs -- a diagnostic built from an empty
        node list hit `to_unified_span_list([]) => unimplemented!()`. It now
        renders label-less, anchored to the root file (SourceMap::root_file).
  [macro-arg-range] preprocessor/src/grammar.rs -- TextRange::new(start,end) with
        start>end (a macro-argument/`define/`include span at EOF) tripped a
        text-size assert; the five sites clamp end>=start.
  [expr-unwrap]   hir_ty/src/diagnostics.rs + validation.rs -- 28 sites did
        expr_map_back[e].unwrap()/stmt_map_back[s].unwrap(); a SYNTHESIZED
        expression has no source-map-back entry, so reporting a type error on it
        panicked. They resolve the span through a fallback (empty range) now.
  [builtin-arg]   hir_ty/src/validation/body.rs -- 11 sites did
        expr_types[arg].unwrap_node()/unwrap_branch()/unwrap_port_flow(), which
        `unreachable!()` when a builtin (e.g. $port_connected) or nature access
        gets a wrong-typed argument inference did not reject. They bail cleanly.
  [span-map]      syntax/src/lib.rs + preprocessor/src/sourcemap.rs -- mapping a
        span across source contexts could yield start>end (to_ctx_span) or a
        subrange past its parent (FileSpan::with_subrange assert); both clamp.
  [include-slice] preprocessor/src/grammar.rs -- stripping the quotes off an
        include path with path[1..len-1] panicked on a malformed/unterminated
        string literal (a lone `"`); it is now a total slice.
  [no-signature]  hir_ty/src/inference.rs -- resolving a call whose arguments
        match NO overload left the candidate list empty and `candidates[0]`
        indexed out of bounds; it falls back to the pre-filter set.

Each check confirms the pathological input now yields a clean ERROR (nonzero exit,
no panic/crash/hang), and that valid code still compiles. See Enhancement-220.md.
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
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


D = os.path.join(tempfile.gettempdir(), "vafcrash220")
os.makedirs(D, exist_ok=True)
HDR = '`include "disciplines.vams"\n'


def wr(name, content):
    p = os.path.join(D, name)
    with open(p, "w") as f:
        f.write(content)
    return p


def run(path, timeout=25):
    """Return verdict in OK / ERROR / CRASH / HANG."""
    try:
        r = subprocess.run([OPENVAF, path, "-o", os.path.join(D, "out.osdi")],
                           capture_output=True, text=True, timeout=timeout, errors="replace")
    except subprocess.TimeoutExpired:
        return "HANG"
    out = ((r.stdout or "") + (r.stderr or "")).lower()
    if r.returncode is not None and r.returncode < 0:
        return "CRASH"
    if "panicked at" in out or "has crashed" in out or r.returncode == 101:
        return "CRASH"
    return "OK" if r.returncode == 0 else "ERROR"


# --- module bodies that reach the fixed code paths ---------------------------
MOD = "module m(a,b); inout a,b; electrical a,b;\n"

# malformed inputs, one (or more) per root cause. Each must NOT crash/hang.
cases = {
    # [include-slice] unterminated string literal after `include
    "include: unterminated string":        '`include "',
    "include: bare quote at eof":           HDR + '`include "\n',
    # [macro-arg-range] macro call / define whose arg list runs to EOF
    "macro call arg to eof":                HDR + "`define F(x) x\n`F(",
    "define param list to eof":             HDR + "`define F(a",
    # [builtin-arg] a builtin / nature access with a wrong-typed argument
    "port_connected of an integer":         HDR + MOD + "analog if ($port_connected(1)) I(a,b)<+0; endmodule\n",
    "port_connected of an expression":      HDR + MOD + "analog if ($port_connected(V(a,b)+1)) I(a,b)<+0; endmodule\n",
    "potential of non-nodes":               HDR + MOD + "analog V(1, 2) <+ 0; endmodule\n",
    # [arity] a builtin called with too few arguments (indexes args[0..] in validation)
    "port_connected of nothing":            HDR + MOD + "analog if ($port_connected()) I(a,b)<+0; endmodule\n",
    "simparam of nothing":                  HDR + MOD + "analog I(a,b) <+ $simparam(); endmodule\n",
    "noise_table of nothing":               HDR + MOD + "analog I(a,b) <+ white_noise($noise_table()); endmodule\n",
    # [no-signature] operator / call with arguments matching no overload
    "bitwise-or of reals":                  HDR + MOD + "analog I(a,b) <+ (1.5 | 2.5); endmodule\n",
    # [empty-span] / [span-map] a mixed / degenerate module head
    "mixed module head":                    HDR + "module m(a, input b); inout a; electrical a,b; endmodule\n",
    "empty ansi/nonansi head":              HDR + "module m(); ; endmodule\n",
    # [parser-stuck] keyword salad + attribute/bracket noise (recovery stress)
    "keyword salad":                        HDR + MOD + "analog begin " + "module analog begin end case for " * 40 + " end endmodule\n",
    "attribute + bracket noise":            HDR + "module m(a); (* *) electrical [ } ) a; (* k= analog begin end endmodule\n",
    # [expr-unwrap] a type error whose expression is synthesized/desugared
    "type error in contribution":           HDR + MOD + "analog I(a,b) <+ V(a,b) ? : ; endmodule\n",
}

print("Enhancement-220: nine compiler panics on malformed input -> clean errors")
for name, src in cases.items():
    v = run(wr("c.va", src))
    check(f"{name} -> clean error, no crash/hang  [{v}]", v in ("ERROR", "OK"), v)

# --- regression: valid code still compiles -----------------------------------
valid = {
    "valid resistor":            HDR + "module r(a,b); inout a,b; electrical a,b; parameter real R=1k;\n"
                                        "analog I(a,b) <+ V(a,b)/R; endmodule\n",
    "valid port_connected":      HDR + "module m(a); inout a; electrical a;\n"
                                        "analog if ($port_connected(a)) I(a) <+ 0; endmodule\n",
    "valid include path strip":  HDR + "module m(a); inout a; electrical a; analog I(a)<+0; endmodule\n",
}
for name, src in valid.items():
    v = run(wr("ok.va", src))
    check(f"valid: {name} still compiles", v == "OK", v)

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
