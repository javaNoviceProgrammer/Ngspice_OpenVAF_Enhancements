#!/usr/bin/env python3
"""
verify_vafcrash3.py -- Enhancement-230: openvaf-r crash hardening (round 3).

A third robustness round -- the production corpus (92/92 standalone still
compile, identical verdicts) plus a fresh mutation-fuzz campaign (~19,500
iterations, diverse compact-model seeds) -- found THREE distinct ways to make the
compiler PANIC (exit 101, "OpenVAF encountered a problem and has crashed!") on
malformed input instead of reporting a clean error. All three are the E-213 panic
class: the panic hook caught them so the compiler was never memory-unsafe, but a
crash + missing diagnostic is the wrong outcome. All fixed:

  [named-block]  hir_def/src/item_tree/lower.rs -- a `begin :` block with the
        scope colon but a missing/invalid name identifier has
        `block_scope().is_some()` yet `name == None`; it was still linked into the
        item tree as a named scope, so name resolution later did
        `.name.expect("Item tree must only contain named blocks")` and panicked
        (nameres/collect.rs:553). Lowering now gates the named-scope treatment on
        `name.is_some()` (Enter and Leave), so a nameless block is not a scope --
        the parser already reports the missing block name.

  [port-flow-decl]  hir_ty/src/validation.rs -- the "expected a port reference
        but no direction was declared" diagnostic labels each of the node's
        declarations and did `NodeTypeDecl::Port(_) => unreachable!()`, assuming
        the node has only Net decls. A node that appears in the module port list
        (a Port decl) AND carries a net type -- reached via an attribute in the
        port list plus a port-flow read `x = I(<p>)` -- has BOTH, so the
        `unreachable!()` fired. It now skips Port decls (`filter_map`).

  [str-lit]  syntax/src/ast/expr_ext.rs -- `StrLit::value()` stripped the quotes
        with `&src[1..src.len()-1]`; a malformed/unterminated string literal the
        lexer still classified as a StrLit can be a lone `"` (len 1), making the
        range [1..0] and panicking ("byte range starts at 1 but ends at 0").
        Reached via an attribute with an unterminated string value
        (`(* d=" ... *)`). It now uses a saturating range. (Same class as the
        E-220 include-path slice, different site: string literals in expressions
        / attributes.)

Each check confirms the pathological input now yields a clean ERROR (nonzero
exit, no panic/crash/hang), and that valid code still compiles. See
Enhancement-230.md.
"""
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
from _setup import VAF as OPENVAF

checks = passed = 0


def check(label, ok, detail=""):
    global checks, passed
    checks += 1
    passed += bool(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"  [{detail}]" if detail and not ok else ""))


D = os.path.join(tempfile.gettempdir(), "vafcrash230")
os.makedirs(D, exist_ok=True)
HDR = '`include "disciplines.vams"\n'


def run(src, timeout=25):
    """src is either a path to an existing .va or literal source. Returns
    OK / ERROR / CRASH / HANG."""
    if os.path.exists(src):
        path = src
    else:
        path = os.path.join(D, "m.va")
        with open(path, "w") as f:
            f.write(src)
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


print("Enhancement-230: openvaf-r crash hardening round 3 (3 panics -> clean errors)")

# --- [named-block] a `begin :` with a missing name, holding a declaration ---
named_block = {
    "begin : (no name) with a decl":
        "module m(a);\n  inout a; electrical a;\n"
        "  analog begin :\n    real x; x = 1; V(a) <+ x;\n  end\nendmodule\n",
    "begin : (no name) empty":
        "module m(a);\n  inout a; electrical a;\n  analog begin : end\nendmodule\n",
    "nested begin : (no name)":
        "module m(a);\n  inout a; electrical a;\n"
        "  analog begin : outer begin : real z; z=1; V(a)<+z; end end\nendmodule\n",
}
for name, src in named_block.items():
    v = run(src)
    check(f"named-block: {name} -> clean error, no crash  [{v}]", v == "ERROR", v)

# --- [port-flow-decl] port-list attribute + port-flow read of that port ---
port_flow = {
    "port-list attr + I(<s>) read":
        HDR + "module m( (* desc=\"x\" *) g, s);\n  inout s; electrical s; real q;\n"
        "  analog begin q = I(<s>); V(s) <+ q; end\nendmodule\n",
    "port-list attr + port_connected":
        HDR + "module m( (* desc=\"x\" *) g, s);\n  inout s; electrical s;\n"
        "  analog begin if ($port_connected(s)) V(s) <+ 0; end\nendmodule\n",
}
for name, src in port_flow.items():
    v = run(src)
    check(f"port-flow-decl: {name} -> clean error, no crash  [{v}]", v == "ERROR", v)

# --- [str-lit] attribute with an unterminated string value (saved fixture) ---
v = run(os.path.join(HERE, "crash_strlit.va"))
check(f"str-lit: attribute with an unterminated string -> clean error, no crash  [{v}]",
      v == "ERROR", v)

# --- regression: valid code still compiles ---
valid = {
    "named block begin : blk with a decl":
        HDR + "module m(a); inout a; electrical a; real x;\n"
        "analog begin : blk real y; y = 1; x = y; V(a) <+ x; end\nendmodule\n",
    "proper inout port, port-flow read":
        HDR + "module m(a); inout a; electrical a; real x;\n"
        "analog begin x = I(<a>); V(a) <+ x; end\nendmodule\n",
    "attribute with a proper string value":
        HDR + "module m(a); inout a; electrical a;\n"
        "(* desc=\"a well-formed string\" *) parameter real p = 1.0;\n"
        "analog V(a) <+ p; endmodule\n",
}
for name, src in valid.items():
    v = run(src)
    check(f"valid: {name} still compiles  [{v}]", v == "OK", v)

print(f"\n{'ALL PASS' if passed == checks else 'FAILURES'}: {passed}/{checks} passed")
sys.exit(0 if passed == checks else 1)
