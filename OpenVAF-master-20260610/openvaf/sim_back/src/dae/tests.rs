use std::fs;

use expect_test::expect_file;
use hir::diagnostics::sink::Buffer;
use hir::diagnostics::ConsoleSink;
use hir::CompilationDB;
use indoc::indoc;
use lasso::Rodeo;
use stdx::{integration_test_dir, openvaf_test_data};

use crate::context::{Context, OptimiziationStage};
use crate::dae::DaeSystem;
use crate::topology;

fn run_test(src: &str) {
    let db = CompilationDB::new_virtual(src).unwrap();
    let mut sink = ConsoleSink::new(&db);
    let module = crate::collect_modules(&db, false, &mut sink).unwrap().remove(0);
    let mut literals = Rodeo::new();
    let mut context = Context::new(&db, &mut literals, &module);
    context.compute_outputs(true);
    context.compute_cfg();
    context.optimize(OptimiziationStage::Initial);
    let topology = topology::Topology::new(&mut context);
    let mut dae_system = DaeSystem::new(&mut context, topology, &mut sink, &mut Vec::new());
    context.compute_cfg();
    context.optimize(OptimiziationStage::Final);
    dae_system.sparsify(&mut context);
    let name = module.module.name(&db);
    let test_dir = openvaf_test_data("dae");
    let topology = format!("{dae_system:#?}");
    assert!(context.func.validate());
    expect_file![test_dir.join(format!("{name}_system.snap"))].assert_eq(&topology);
    let func = format!("{:#?}", context.func);
    expect_file![test_dir.join(format!("{name}_mir.snap"))].assert_eq(&func)
}

#[test]
fn diode() {
    let src = fs::read_to_string(integration_test_dir("DIODE").join("diode.va")).unwrap();
    run_test(&src);
}

#[test]
fn resistor() {
    let src = fs::read_to_string(integration_test_dir("RESISTOR").join("resistor.va")).unwrap();
    run_test(&src);
}

#[test]
fn lim_rhs() {
    let src = indoc! {r#"
        `include "disciplines.vams"
        module lim_rhs(inout a, inout c);
            electrical a, c;
            parameter real foo=1.0, bar=2.0;
            analog begin
                I(a, c) <+ foo*exp($limit(V(a,c), "testlim"));
            end
        endmodule
    "#};
    run_test(src);
}

#[test]
fn lim_rhs_react() {
    let src = indoc! {r#"
        `include "disciplines.vams"
        module lim_rhs_react(inout a, inout c);
            electrical a, c;
            parameter real foo=1.0, bar=2.0;
            analog begin
                I(a, c) <+ ddt(foo*$limit(V(a,c), "testlim"));
            end
        endmodule
    "#};
    run_test(src);
}

#[test]
fn lim_rhs_sign() {
    let src = indoc! {r#"
        `include "disciplines.vams"
        module lim_rhs_sign(inout a, inout c);
            electrical a, c;
            parameter real foo=1.0, bar=2.0;
            real Vac;
            analog begin
                if (foo < 0) 
                    Vac = $limit(V(c, a), "testlim");
                else
                    Vac = $limit(V(a, c), "testlim");

                I(a, c) <+ foo*exp(Vac);
            end
        endmodule
    "#};
    run_test(src);
}

#[test]
fn voltage_src() {
    let src = indoc! {r#"
        `include "disciplines.vams"
        module voltage_src(inout a, inout c);
            electrical a, c;
            parameter real foo=1.0;
            analog begin
                V(a, c) <+ foo;
            end
        endmodule
    "#};
    run_test(src);
}

#[test]
fn const_switch_branch() {
    let src = indoc! {r#"
        `include "disciplines.vams"
        module const_switch_branch(inout a, inout c);
            electrical a, c;
            parameter real foo=1.0;
            analog begin
                if (foo < 0 )
                    V(a, c) <+ foo;
                else
                    I(a, c) <+ foo;
            end
        endmodule
    "#};
    run_test(src);
}

#[test]
fn dyn_switch_branch() {
    let src = indoc! {r#"
        `include "disciplines.vams"
        module dyn_switch_branch(inout a, inout c);
            electrical a, c;
            parameter real foo=1.0;
            analog begin
                if (V(a, c) < 0) 
                    V(a, c) <+ foo * V(a, c);
                else
                    I(a, c) <+ foo * V(a, c);
            end
        endmodule
    "#};
    run_test(src);
}

/// Enhancement-86 regression: a voltage-source branch between a port and an
/// internal node. Two DAE bugs hid here: the small-signal pruner classified
/// the internal node as a zero-DC noise node (its conduction silently moved
/// to the AC-only residual), and the V<+0 collapse hint eliminated the very
/// branch-current unknown the model reads.
#[test]
fn vsrc_internal_node() {
    let src = indoc! {r#"
        `include "disciplines.vams"
        module vsrcint(a, o);
            inout a, o; electrical a, o;
            electrical f;
            branch (a, f) am;
            analog begin
                V(am) <+ 0.0;
                I(f) <+ V(f)/1k;
                V(o) <+ 1000.0*I(am);
            end
        endmodule
    "#};
    run_test(src);
}

// Enhancement-90: a non-ANSI header with a multi-bit *input* bus port that
// is not the last port. The bus bits must appear contiguously and in
// header-port order among the DAE unknowns (`in[0], in[1], in[2], y`), so
// the OSDI terminals map positionally to the netlist. Before the fix the
// extra bits were appended after `y`, scrambling terminal order.
#[test]
fn bus_input_port_order() {
    let src = indoc! {r#"
        `include "disciplines.vams"
        module busport_e90(in, y);
            input [0:2] in;
            output y;
            electrical [0:2] in;
            electrical y;
            analog I(y) <+ (V(y) - V(in[1]))*1e-3;
        endmodule
    "#};
    run_test(src);
}

/// Enhancement-400: the DAE build reports a branch that is written as both a potential
/// and a flow source with nothing conditional between the two -- one of the contributions
/// is dropped, and which one depends purely on statement order.
///
/// Both orderings must be reported and the switch-branch idiom must not be, which is the
/// entire discrimination: only the DAE build can tell them apart, because only there is
/// `is_voltage_src` known to be a constant rather than a runtime value.
fn diagnostics_of(src: &str) -> String {
    let db = CompilationDB::new_virtual(src).unwrap();
    let mut buf = Buffer::no_color();
    {
        let mut sink = ConsoleSink::buffer(&db, &mut buf);
        sink.annonymize_paths();
        let module = crate::collect_modules(&db, false, &mut sink).unwrap().remove(0);
        let mut literals = Rodeo::new();
        let mut context = Context::new(&db, &mut literals, &module);
        context.compute_outputs(true);
        context.compute_cfg();
        context.optimize(OptimiziationStage::Initial);
        let topology = topology::Topology::new(&mut context);
        DaeSystem::new(&mut context, topology, &mut sink, &mut Vec::new());
    }
    String::from_utf8(buf.into_inner()).unwrap()
}

fn dut(body: &str) -> String {
    format!(
        "`include \"disciplines.vams\"\n\
         module dut(a, b);\n\
         inout a, b;\n\
         electrical a, b;\n\
         parameter real sw = 1.0;\n\
         analog begin\n{body}end\n\
         endmodule\n"
    )
}

#[test]
fn discarded_contribution() {
    // potential first: the branch ends up a flow source, the potential is dropped
    let diag = diagnostics_of(&dut("V(a, b) <+ 0.4;\nI(a, b) <+ 1e-3;\n"));
    assert!(diag.contains("L022"), "{diag}");
    assert!(
        diag.contains("branch (a,b) is contributed as both a potential and a flow source"),
        "{diag}"
    );
    assert!(diag.contains("this potential contribution is discarded"), "{diag}");
    assert!(diag.contains("the branch is a flow source here"), "{diag}");

    // flow first: the mirror image, same branch, opposite verdict
    let diag = diagnostics_of(&dut("I(a, b) <+ 1e-3;\nV(a, b) <+ 0.4;\n"));
    assert!(diag.contains("this flow contribution is discarded"), "{diag}");
    assert!(diag.contains("the branch is a potential source here"), "{diag}");

    // a switch branch contributes both too, but each on its own path: nothing is dropped
    let diag =
        diagnostics_of(&dut("if (sw != 0)\nV(a, b) <+ 0.4;\nelse\nI(a, b) <+ 1e-3;\n"));
    assert_eq!(diag, "");

    // neither is a single-kind branch, whichever kind that is
    assert_eq!(diagnostics_of(&dut("V(a, b) <+ 0.4;\n")), "");
    assert_eq!(diagnostics_of(&dut("I(a, b) <+ 1e-3;\n")), "");

    // an explicit allow silences it
    let diag = diagnostics_of(&dut(
        "(* openvaf_allow=\"discarded_contribution\" *) V(a, b) <+ 0.4;\nI(a, b) <+ 1e-3;\n",
    ));
    assert_eq!(diag, "");
}
