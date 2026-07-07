#!/usr/bin/env python3
"""Curate the raw LRM code blocks into a compile suite.

Reads raw_blocks/ (from extract_lrm_examples.py) and probe_status.json and
sorts every module-containing block into:

  va/           in-scope Verilog-A examples expected to COMPILE (verbatim,
                or with a minimal annotated patch / context stub)
  limitations/  in-scope examples openvaf-r rejects today; the expected
                diagnostic is pinned in manifest.json
  ams/          examples using the mixed-signal (AMS/digital) language,
                outside the Verilog-A analog subset openvaf targets
  findings/     legal LRM code that currently CRASHES the compiler
                (kept out of verify until fixed)
  fragments/    non-module snippets (kept for reference, not compiled)

Every manual disposition asserts a content fingerprint so a re-extraction
that renumbers blocks fails loudly instead of misclassifying.
"""
import json
import os
import re
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
RAW = os.path.join(HERE, "raw_blocks")

PORTLINT = ["-W", "port_without_direction"]

VERTNPN_STUB = """
// [lrm_examples context] The LRM leaves vertNPN to the imagination (it is a
// SPICE .model in the companion netlist of Annex E).  Minimal GP-style BJT
// so elaboration has a real target.
module vertNPN(c, b, e);
   inout c, b, e;
   electrical c, b, e;
   parameter real is_ = 1e-16 from (0:inf);
   parameter real bf = 100.0 from (0:inf);
   analog begin
      I(b, e) <+ (is_/bf)*(limexp(V(b, e)/$vt) - 1);
      I(c, e) <+ is_*(limexp(V(b, e)/$vt) - 1);
   end
endmodule
"""

ANNEX_E_STUBS = """
// [lrm_examples context] Annex E SPICE-compatibility primitives referenced
// by the oscillator example, as plain Verilog-A modules.
module resistor(p, n);
   inout p, n; electrical p, n;
   parameter real r = 1k;
   analog I(p, n) <+ V(p, n)/r;
endmodule
module capacitor(p, n);
   inout p, n; electrical p, n;
   parameter real c = 1p;
   parameter real ic = 0;
   analog I(p, n) <+ ddt(c*V(p, n));
endmodule
module inductor(p, n);
   inout p, n; electrical p, n;
   parameter real l = 1u;
   analog V(p, n) <+ ddt(l*I(p, n));
endmodule
module vsine(p, n);
   inout p, n; electrical p, n;
   parameter real dc = 0;
   analog V(p, n) <+ dc;
endmodule
module isine(p, n);
   inout p, n; electrical p, n;
   parameter real dc = 0;
   analog I(p, n) <+ dc;
endmodule
""" + VERTNPN_STUB

# ---------------------------------------------------------------------------
# Manual dispositions for blocks the automatic probe could not settle.
# key: raw block name (without .txt)
# fp:  substring that must appear in the block (renumbering guard)
# cls: ok | ams | limitation | pseudo | junk | crash
# expect: diagnostic fragment pinned for limitations
# trim_after: keep lines up to and including the Nth occurrence of a marker
# patches: list of (old, new) literal replacements
# append: extra source appended (context stubs)
# flags: extra openvaf-r flags recorded in the manifest
# note: one-line rationale (lands in RESULTS.md)
# ---------------------------------------------------------------------------
MANUAL = {
    "block_018_1": dict(fp="shiftPlus5", cls="ok",
        trim_after=("endmodule", 4),
        note="signal-flow disciplines (voltage/current); syntax-summary junk trimmed off the tail"),
    "block_032_1": dict(fp="full_case", cls="junk",
        note="attribute-section pseudo-code (<rest_of_case_statement>); crashes the compiler - finding F2"),
    "block_045_4": dict(fp="crosstalk", cls="limitation",
        expect="refers to module 'gen'",
        note="name-then-range array ports (input in[0:2]) now supported (E-89); still a limitation on the undefined gen/sink modules + the multi-dimensional parameter-array literal override"),
    "block_048_2": dict(fp="ttl_curr", cls="ok",
        trim_after=("endnature", 3),
        no_include=True,  # ttl_curr declares access=I, which collides with disciplines.vams Current
        append="""
// [lrm_examples context] minimal discipline + module so the derived
// natures are actually elaborated (flow-only signal per LRM 3.6.1).
discipline ttl;
   flow new_curr;
enddiscipline
module ttl_load(a, b);
   inout a, b;
   ttl a, b;
   analog I(a, b) <+ 1u;
endmodule
""",
        note="derived/alias natures (nature X : parent) with a context module added"),
    "block_062_2": dict(fp="probe_p", cls="ok",
        patches=[("module current_sink(p);", "module current_sink(p);\n   inout p; // [lrm_examples patch] direction added")],
        note="named port branch 'branch (<p>) probe_p;' (LRM 3.7.2); used to crash the compiler - fixed by E-84 (F1)"),
    "block_091_1": dict(fp="module adc", cls="limitation",
        expect="'i' was not found in the current scope",
        note="param-dependent bus width now folds (E-91); still blocked on the genvar for-loop used *inside* the analog block (analog-block genvar unrolling is unsupported)"),
    "block_112_1": dict(fp="myscope", cls="limitation",
        expect="hierarchical/block-scoped parameter",
        note="block-scoped parameters WORK (E-87); this file is correctly rejected only because it also demos the LRM's own `#(.myscope.p2(4)) // error` case, now a clean targeted diagnostic (was a parser cascade)"),
    "block_117_1": dict(fp="module dac", cls="limitation",
        expect="'i' was not found in the current scope",
        note="param-dependent bus width now folds (E-91); still blocked on the analog-block genvar for-loop"),
    "block_119_1": dict(fp="signal_monitor", cls="ok",
        trim_after=("endmodule", 4),
        patches=[("    module top;\n       A a1();\n       B b1();",
                  "    module top;\n       A a1();\n       B b1();\n       drv_m drv();          // [lrm_examples context] provides the top.drv nets\n       signal_monitor mon(); // [lrm_examples context] instantiated so its refs resolve")],
        append="""
// [lrm_examples context] the LRM leaves top.drv to the imagination; a
// minimal module with the two nets the monitor probes.
module drv_m();
   electrical a, b;
   analog begin
      V(a, b) <+ 0.75;
      I(b) <+ V(b)/1k;
   end
endmodule
""",
        note="hierarchical net + named-branch probes from sibling modules (V(top.drv.a), V(top.a1.b)); parse/elaboration added by E-86; trailing branch()-fragment section trimmed"),
    "block_134_1": dict(fp="genvarexp", cls="limitation",
        expect="'k' was not found in the current scope",
        note="param-dependent bus width now folds (E-91); still blocked on the analog-block genvar for-loop"),
    "block_140_2": dict(fp="=== 1'b1", cls="ams",
        note="cross() with digital enable expression (===) and empty optional args"),
    "block_144_1": dict(fp="absdelta", cls="ams",
        note="wreal/assign/always sampler (mixed-signal)"),
    "block_155_3": dict(fp="processinfo", cls="limitation",
        expect="'processinfo' was not found",
        note="hierarchical refs to an uninstantiated process-info module"),
    "block_158_1": dict(fp="paramset nch nmos3", cls="limitation",
        expect="instantiates paramset 'nch'",
        note="paramset targeting a SPICE primitive (nmos3) rather than a VA module"),
    "block_150_1": dict(fp="sigmadelta", cls="ok",
        append="""
// [lrm_examples context] The LRM's d2a here is a mixed-signal D/A the text
// never defines; minimal analog stand-in so the sigma-delta loop elaborates.
module d2a(dout, aref, din);
   inout dout, aref, din;
   electrical dout, aref, din;
   parameter integer width = 1 from [1:24];
   analog V(dout) <+ V(aref) * ((V(din) > 0.5) ? 1.0 : 0.0);
endmodule
""",
        note="sigma-delta ADC loop (cross/transition/idt, implicit nets aa0-aa2); d2a context stub added"),
    "block_152_2": dict(fp="spice_pmos", cls="ok",
        append="""
// [lrm_examples context] Annex E SPICE-compatibility MOS primitives
// (square-law level-1, 3-terminal), matching examples/annexe_examples (E-89).
module spice_nmos(d, g, s);
   inout d, g, s; electrical d, g, s;
   parameter real l = 1u from (0:inf);
   parameter real w = 1u from (0:inf);
   parameter real vto = 0.7;
   parameter real kp = 2e-5 from (0:inf);
   real vgs, vds, vov, ids;
   analog begin
      vgs = V(g, s); vds = V(d, s); vov = vgs - vto;
      if (vov <= 0.0)      ids = 0.0;
      else if (vds >= vov) ids = 0.5*kp*(w/l)*vov*vov;
      else                 ids = kp*(w/l)*(vov*vds - 0.5*vds*vds);
      I(d, s) <+ ids;
   end
endmodule
module spice_pmos(d, g, s);
   inout d, g, s; electrical d, g, s;
   parameter real l = 1u from (0:inf);
   parameter real w = 1u from (0:inf);
   parameter real vto = -0.7;
   parameter real kp = 1e-5 from (0:inf);
   real vsg, vsd, vov, isd;
   analog begin
      vsg = V(s, g); vsd = V(s, d); vov = vsg + vto;
      if (vov <= 0.0)      isd = 0.0;
      else if (vsd >= vov) isd = 0.5*kp*(w/l)*vov*vov;
      else                 isd = kp*(w/l)*(vov*vsd - 0.5*vsd*vsd);
      I(s, d) <+ isd;
   end
endmodule
""",
        note="transmission gate over the Annex E SPICE MOS primitives spice_nmos/spice_pmos; primitives provided as context (E-89, examples/annexe_examples)"),
    "block_153_2": dict(fp="weakp", cls="ok",
        append="""
// [lrm_examples context] the `mosp` wrapper from the page-152 example plus
// the Annex E spice_pmos it instantiates (E-89).
module mosp(drain, gate, source);
   inout drain, gate, source; electrical drain, gate, source;
   parameter real gate_length = 0.3e-6;
   parameter real gate_width  = 4.0e-6;
   spice_pmos #(.l(gate_length), .w(gate_width)) p(drain, gate, source);
endmodule
module spice_pmos(d, g, s);
   inout d, g, s; electrical d, g, s;
   parameter real l = 1u from (0:inf);
   parameter real w = 1u from (0:inf);
   parameter real vto = -0.7;
   parameter real kp = 1e-5 from (0:inf);
   real vsg, vsd, vov, isd;
   analog begin
      vsg = V(s, g); vsd = V(s, d); vov = vsg + vto;
      if (vov <= 0.0)      isd = 0.0;
      else if (vsd >= vov) isd = 0.5*kp*(w/l)*vov*vov;
      else                 isd = kp*(w/l)*(vov*vsd - 0.5*vsd*vsd);
      I(s, d) <+ isd;
   end
endmodule
""",
        note="instance-parameter forms over the mosp/spice_pmos Annex E primitives; provided as context (E-89)"),
    "block_153_3": dict(fp="vco1", cls="ok",
        append="""
// [lrm_examples context] The LRM never defines the vco it instantiates;
// minimal stand-in with the two parameters the example overrides.
module vco(lo_out, rf_in);
   output lo_out; input rf_in;
   electrical lo_out, rf_in;
   parameter real centerFreq = 1000 from (0:inf);
   parameter real convGain = 100 from (0:inf);
   analog V(lo_out) <+ convGain * V(rf_in) / centerFreq;
endmodule
""",
        note="hierarchy example (named parameter overrides); vco context stub added"),
    "block_156_1": dict(fp="matchedres", cls="ok",
        append="""
// [lrm_examples context] polyres per the page-155 example, minus the
// processinfo hierarchy the LRM leaves undefined.
module polyres(a, b);
   inout a, b;
   electrical a, b;
   parameter real length = 1u from (0:inf);
   parameter real width = 1u from (0:inf);
   parameter real rsh = 50 from (0:inf);
   analog I(a, b) <+ V(a, b) * width / (rsh * length);
endmodule
""",
        note="matched-resistor layout example: .$xposition/.$yposition instance overrides on each polyres (E-44 hidden state parameters); context stub added"),
    "block_263_1": dict(fp="module_a", cls="ok",
        append="""
// [lrm_examples context] trivial stand-in for the undefined module_a.
module module_a(p, n);
   inout p, n;
   electrical p, n;
   analog I(p, n) <+ V(p, n) / 1k;
endmodule
""",
        note="hierarchical path illustration; module_a context stub added"),
    "block_168_1": dict(fp="for (i=bits-1", cls="limitation",
        expect="compile-time-constant integer",
        note="generate-for with parameter loop bounds (structure cannot depend on runtime-bindable parameters; E-67 scope decision)"),
    "block_170_1": dict(fp="coeff1", cls="limitation",
        expect="elaboration-time constant",
        note="generate-if on $param_given (parameter-driven structure; E-67 scope decision)"),
    "block_171_2": dict(fp="bits > 1", cls="limitation",
        expect="elaboration-time constant",
        note="generate-if on a parameter (parameter-driven structure; E-67 scope decision)"),
    "block_191_1": dict(fp="connectmodule d2a", cls="ams",
        note="connectmodule skeletons (mixed-signal auto-insertion)"),
    "block_206_1": dict(fp="dig_inv d1", cls="ams",
        note="mixed digital/analog ring with connect rules"),
    "block_206_2": dict(fp="always out = #10", cls="ams",
        note="digital inverter + analog inverter pair (reg/always)"),
    "block_209_1": dict(fp="module analog_inv", cls="ams",
        note="mixed-net example: analog inverter wired to ddiscrete_1v2 nets via connect rules"),
    "block_162_3": dict(fp="reg clk", cls="ams", note="digital testbench (reg/initial/always)"),
    "block_163_1": dict(fp="adc4", cls="ok",
        note="binary ADC tree wired with part-selects (out[3:2]); used to be a parse error - fixed by E-85 (F6)"),
    "block_164_1": dict(fp="adc2 hi", cls="ok",
        append="""
// [lrm_examples context] "adc is same as defined in 6.5.4" -- the 1-bit
// slice of the page-163 example, minimal analog stand-in.
module adc (out, remainder, in);
   output out, remainder;
   input in;
   electrical out, remainder, in;
   analog begin
      V(out) <+ (V(in) > 0.5) ? 1.0 : 0.0;
      V(remainder) <+ 2.0*(V(in) - ((V(in) > 0.5) ? 0.5 : 0.0));
   end
endmodule
""",
        note="named part-select connections (.out(out[3:2])); parse fixed by E-85 (F6), adc context stub added"),
    "block_169_1": dict(fp="rcline", cls="limitation",
        expect="bus bit-select index must be a constant",
        note="param-dependent bus width now folds (E-91); still blocked on a param-valued bus bit-select outside a declaration (n[N]) + the undefined resistor/capacitor primitives"),
    "block_169_2": dict(fp="rcline2", cls="limitation",
        expect="bus bit-select index must be a constant",
        note="param-dependent bus width now folds (E-91); still blocked on a param-valued bus bit-select (n[N]) + undefined primitives"),
    "block_171_1": dict(fp="nqsMod", cls="pseudo",
        note="contains a literal '...' placeholder; also generate-if on a parameter (see E-67)"),
    "block_172_1": dict(fp="genblk2", cls="limitation",
        expect="unexpected token 'if'",
        note="generate-if with parameter condition + implicit genblk naming (E-67 scope decision)"),
    "block_180_2": dict(fp="wire in", cls="ams", note="wire net driving analog"),
    "block_181_1": dict(fp="1'bx", cls="ams", note="ddiscrete net with ===/x/z comparisons"),
    "block_182_1": dict(fp="reg dnet", cls="ams", note="reg/initial digital converter"),
    "block_182_2": dict(fp="sampler", cls="ams", note="reg/always sampler"),
    "block_184_1": dict(fp="sampler3", cls="ams", note="posedge on wire mixed with cross()"),
    "block_184_2": dict(fp="sampler2", cls="ams", note="always @(cross) driving a reg"),
    "block_205_1": dict(fp="dig_inv", cls="ams", note="digital inverter (reg/always/#delay)"),
    "block_208_1": dict(fp="connectmodule", cls="ams", note="connectmodule + connectrules"),
    "block_210_1": dict(fp="connectmodule", cls="ams", note="connectmodule (elect_to_logic)"),
    "block_218_1": dict(fp="wire", cls="ams", note="wire nets"),
    "block_219_1": dict(fp="d2aC", cls="ams", note="wire [15:0] bus + posedge in analog"),
    "block_220_1": dict(fp="connectmodule", cls="ams", note="connectmodule pair"),
    "block_256_1": dict(fp="mytask", cls="ams", note="task/$display (digital context)"),
    "block_265_1": dict(fp="twoclk", cls="ok",
        patches=[("electrical vout_q1, vout_q1b;",
                  "electrical vout_q1, vout_q2; // [lrm_examples patch] LRM erratum: 'vout_q1b' is a typo for port 'vout_q2'")],
        note="timer/transition/$port_connected clock source; $port_connected on unconnected flattened ports used to fail - fixed by E-84 (F5). Also fixes a genuine typo in the LRM's own example"),
    "block_267_1": dict(fp="analog_node_alias", cls="limitation",
        expect="refers to module 'resistor'",
        note="$analog_node_alias/$analog_port_alias example; elaboration rejects the unconnected instance nets"),
    "block_274_3": dict(fp="f_xy", cls="limitation",
        expect="requires a bit-select",
        note="$table_model with runtime array data arguments"),
    "block_278_1": dict(fp="connectmodule", cls="ams", note="connectmodule with drive strength"),
    "block_281_1": dict(fp="`__FILE__", cls="junk",
        note="compiler-directive name table; separately, `__FILE__/`__LINE__ are unsupported - finding F4"),
    "block_343_1": dict(fp="$resistor", cls="limitation",
        expect="'$resistor' was not found",
        flags=PORTLINT,
        note="Annex E SPICE-compatibility system function $resistor()"),
    "block_416_1": dict(fp="diffPair", cls="ok",
        flags=PORTLINT,
        append=VERTNPN_STUB,
        note="differential pair; LRM omits port directions (lint demoted) + vertNPN context stub"),
    "block_416_2": dict(fp=".SUBCKT", cls="junk",
        note="SPICE netlist from Annex E, not Verilog-A"),
    "block_416_3": dict(fp="module osc", cls="ok",
        flags=PORTLINT,
        patches=[("ecpOsc Osc1 (out, gnd);", "ecpOsc Osc1 (out, gnd); // instantiates the module from the next example")],
        merge_with="block_416_4",
        append=ANNEX_E_STUBS,
        note="ECP oscillator pair of examples merged; Annex E primitive stubs added"),
    "block_416_4": dict(fp="ecpOsc", cls="merged", note="merged into block_416_3"),
    "block_438_1": dict(fp="generate i (bits-1,0)", cls="limitation",
        expect="legacy generate 'i': the bounds must be elaboration-time constants",
        note="legacy Verilog-A 1.0 'generate i (msb,lsb)' statement (Annex C) now supported (E-88) with constant bounds; this example uses a PARAMETER bound (bits-1) + parameter bus width, both elaboration-time-unresolvable -- stays a limitation"),
}



# ---------------------------------------------------------------------------
# Micro-repros for the defect findings (RESULTS.md). Emitted into findings/;
# `expect=None` means "must compile" (a fixed defect, pinned against
# regression); a string pins the diagnostic of a still-open gap.
# ---------------------------------------------------------------------------
MICROS = {
    "micro_portbranch.va": dict(expect=None, src="""`include "disciplines.vams"
// F1 (fixed): named port branch, LRM 3.7.2 -- used to panic the compiler
module current_sink(p);
   inout p;
   electrical p;
   branch (<p>) probe_p;
   analog $strobe("current probed is %g", I(probe_p));
endmodule
"""),
    "micro_portconnected.va": dict(expect=None, src="""`include "disciplines.vams"
// F5 (fixed): $port_connected on an unconnected port of a flattened
// instance -- used to fail validation after the port became a local net
module leaf(a, b);
   output a, b;
   electrical a, b;
   analog begin
      V(a) <+ 1.0;
      if ($port_connected(b))
         V(b) <+ 2.0;
      else
         V(b) <+ 0.0;
   end
endmodule
module top(y);
   output y;
   electrical y;
   leaf l1(.a(y));   // .b left unconnected
endmodule
"""),
    "micro_deadop.va": dict(expect=None, src="""`include "disciplines.vams"
// F7 (fixed): an analog operator inside a constant-false branch -- the dead
// transition() survived const-folding as a detached op and aborted codegen
module m(a, b);
   output a, b; electrical a, b;
   integer q;
   analog begin
      @(timer(0, 1u)) q = !q;
      if ((1))
         V(a) <+ transition(q, 1n, 1n, 1n);
      else
         V(a) <+ 0.0;
      if ((0))
         V(b) <+ transition(!q, 1n, 1n, 1n);
      else
         V(b) <+ 0.0;
   end
endmodule
"""),
    "micro_unknownmod.va": dict(
        expect="refers to module 'foo'",
        src="""`include "disciplines.vams"
// F3 (fixed): this used to compile SILENTLY, dropping the instance
module top(a, b);
   inout a, b;
   electrical a, b;
   foo f1(a, b);
   analog V(a,b) <+ 1.0;
endmodule
"""),
    "micro_file_line.va": dict(
        expect=None,
        src="""`include "disciplines.vams"
// F4 (fixed by E-85): `__FILE__/`__LINE__ predefined macros
module m(a, b);
   inout a, b; electrical a, b;
   analog begin
      $strobe("at %s:%d", `__FILE__, `__LINE__);
      V(a,b) <+ 1.0;
   end
endmodule
"""),
    "micro_partselect.va": dict(
        expect=None,
        src="""`include "disciplines.vams"
// F6 (fixed by E-85): part-selects in instance connections
module adc2(out, in);
   output [1:0] out; input in;
   electrical [1:0] out; electrical in;
   analog begin V(out[0]) <+ V(in); V(out[1]) <+ 2*V(in); end
endmodule
module adc4(out, in);
   output [3:0] out; input in;
   electrical [3:0] out; electrical in;
   adc2 hi (out[3:2], in);
   adc2 lo (out[1:0], in);
endmodule
"""),
}

def load(name):
    with open(os.path.join(RAW, name + ".txt")) as f:
        return f.read()


def apply_manual(name, body, m):
    if "trim_after" in m:
        marker, nth = m["trim_after"]
        pos = -1
        for _ in range(nth):
            pos = body.index(marker, pos + 1)
        body = body[: pos + len(marker)] + "\n"
    for old, new in m.get("patches", []):
        assert old in body, f"{name}: patch target missing: {old!r}"
        body = body.replace(old, new)
    if m.get("merge_with"):
        body = body.rstrip() + "\n\n" + load(m["merge_with"]).rstrip() + "\n"
    if m.get("append"):
        body = body.rstrip() + "\n" + m["append"]
    return body


def main():
    idx = json.load(open(os.path.join(HERE, "raw_index.json")))
    probe = json.load(open(os.path.join(HERE, "probe_status.json")))
    ok_auto = set(probe["ok"])

    for d in ("va", "ams", "limitations", "findings", "fragments"):
        shutil.rmtree(os.path.join(HERE, d), ignore_errors=True)
        os.makedirs(os.path.join(HERE, d))

    manifest = {"va": [], "limitations": [], "ams": [], "findings": [],
                "fragments": [], "excluded": []}
    seen_manual = set()

    for b in idx:
        name = b["file"].replace(".txt", "")
        body = load(name)
        page = b["page"]
        m = MANUAL.get(name)
        if m:
            seen_manual.add(name)
            assert m["fp"] in body, f"{name}: fingerprint {m['fp']!r} missing - renumbered extraction?"
            cls = m["cls"]
            if cls in ("junk", "pseudo", "merged"):
                manifest["excluded"].append({"block": name, "page": page,
                                             "class": cls, "note": m["note"]})
                continue
            body = apply_manual(name, body, m)
        else:
            has_mod = re.search(r"(?<!end)module", body) and "endmodule" in body
            if not has_mod:
                cls = "fragment"
            elif name in ok_auto:
                cls, m = "ok", {"note": ""}
            else:
                raise SystemExit(f"unclassified failing block: {name}")

        header = (f"// Verilog-AMS LRM 2023 (Accellera), example from page {page}\n"
                  f"// extracted by lrm_examples/extract_lrm_examples.py ({name})\n")
        if cls == "fragment":
            out = os.path.join(HERE, "fragments", name + ".txt")
            with open(out, "w") as f:
                f.write(body)
            manifest["fragments"].append({"block": name, "page": page})
            continue

        src = header
        if "`include" not in body and not (m or {}).get("no_include"):
            src += '`include "disciplines.vams"\n`include "constants.vams"\n'
        src += body
        dirname = {"ok": "va", "limitation": "limitations",
                   "ams": "ams", "crash": "findings"}[cls]
        va = os.path.join(HERE, dirname, f"lrm_{name.replace('block_', 'p')}.va")
        with open(va, "w") as f:
            f.write(src)
        entry = {"file": os.path.basename(va), "block": name, "page": page,
                 "note": (m or {}).get("note", "")}
        if m and m.get("flags"):
            entry["flags"] = m["flags"]
        if cls == "limitation":
            entry["expect"] = m["expect"]
        manifest[{"ok": "va", "limitation": "limitations", "ams": "ams",
                  "crash": "findings"}[cls]].append(entry)

    for fname, m in MICROS.items():
        with open(os.path.join(HERE, "findings", fname), "w") as f:
            f.write(m["src"])
        entry = {"file": fname, "block": "micro", "page": 0,
                 "note": m["src"].splitlines()[1].lstrip("/ ")}
        if m["expect"] is not None:
            entry["expect"] = m["expect"]
        manifest["findings"].append(entry)

    missing = set(MANUAL) - seen_manual
    assert not missing, f"manual entries never matched: {missing}"

    with open(os.path.join(HERE, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    for k in ("va", "limitations", "ams", "findings", "fragments", "excluded"):
        print(f"{k:12s} {len(manifest[k])}")


if __name__ == "__main__":
    main()
