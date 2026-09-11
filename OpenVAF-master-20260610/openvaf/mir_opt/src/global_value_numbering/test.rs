use std::mem::ManuallyDrop;

use expect_test::{expect, Expect};
use mir::{ControlFlowGraph, DominatorTree, FuncRef, Opcode, Value, ValueList};
use mir_reader::parse_function;

use super::{CallExprPayLoad, GVNExprPayLoad, GVNExpression};

fn check(src: &str, data_flow_result: Expect) {
    let (mut func, _) = parse_function(src).unwrap();
    let mut cfg = ControlFlowGraph::new();
    cfg.compute(&func);
    let mut dom_tree = DominatorTree::default();
    dom_tree.compute(&func, &cfg, true, true, false);
    crate::inst_combine(&mut func);
    let mut gvn = super::GVN::default();
    gvn.init(&func, &dom_tree, 3);
    gvn.solve(&mut func);
    gvn.remove_unnecessary_insts(&mut func, &dom_tree);
    gvn.clear(&mut func);
    data_flow_result.assert_eq(&func.to_debug_string());
}

#[test]
fn diode() {
    let raw = r#"
        function %bar(v10, v11, v12) {
            fn0 = const fn %ddx_v10(1) -> 1
            fn1 = const fn %ddx_v11(1) -> 1
            v3 = fconst 0.0
            v6 = fconst 0x1.0000000000000p0

        block0:
            v13 = fadd v11, v11
            v102 = fadd v6, v6
            v14 = fadd v11, v11
            v103 = fadd v6, v6
            v20 = fmul v12, v10
            v21 = fdiv v20, v14
            v104 = fmul v14, v14
            v105 = fmul v103, v20
            v106 = fdiv v105, v104
            v107 = fsub v3, v106
            v22 = exp v21
            v108 = fmul v107, v22
            v23 = fmul v13, v22
            v109 = fmul v102, v22
            v110 = fmul v108, v13
            v111 = fadd v109, v110
            v101 = optbarrier v111
        }
    "#;
    let expect = expect![[r#"
        function %bar(v10, v11, v12) {
            inst0 = const fn %ddx_v10(1) -> 1
            inst1 = const fn %ddx_v11(1) -> 1
            v3 = fconst 0.0

        block0:
            v13 = fadd v11, v11
            v20 = fmul v12, v10
            v21 = fdiv v20, v13
            v104 = fmul v13, v13
            v105 = fmul v11, v20
            v106 = fdiv v105, v104
            v107 = fsub v3, v106
            v22 = exp v21
            v108 = fmul v107, v22
            v23 = fmul v13, v22
            v109 = fmul v11, v22
            v110 = fmul v108, v13
            v111 = fadd v109, v110
            v101 = optbarrier v111
        }
    "#]];
    check(raw, expect)
}

/// Enhancement-596: `GVNExpression::eq` for calls read BOTH payloads from
/// `self`, so any two call expressions were "equal" once the hash table
/// compared them. Exercise the comparison directly: same callee and args is
/// equal; a different callee, or a different argument, is not.
#[test]
fn call_expr_eq_reads_other() {
    let raw = r#"
        function %bar(v10, v11) {
            fn0 = const fn %simparam(1) -> 1
            fn1 = const fn %simparam_opt(2) -> 1

        block0:
            v12 = call fn0(v10)
            v13 = call fn1(v10, v11)
            v14 = optbarrier v12
            v15 = optbarrier v13
        }
    "#;
    let (mut func, _) = parse_function(raw).unwrap();
    let mut call = |func_ref: u32, args: &[Value]| {
        let args = ValueList::from_slice(args, &mut func.dfg.insts.value_lists);
        GVNExpression {
            opcode: Opcode::Call,
            payload: GVNExprPayLoad {
                call: ManuallyDrop::new(CallExprPayLoad { func_ref: FuncRef::with_number(func_ref).unwrap(), args }),
            },
        }
    };
    let v10 = Value::with_number(10).unwrap();
    let v11 = Value::with_number(11).unwrap();
    let a = call(0, &[v10]);
    let a2 = call(0, &[v10]);
    let b = call(1, &[v10, v11]);
    let c = call(1, &[v11, v10]);
    let d = call(1, &[v10, v10]);
    assert!(a.eq(&a2, &func), "identical calls are equal");
    assert!(!a.eq(&b, &func), "a different callee is not equal");
    assert!(!b.eq(&a, &func), "...in either order");
    assert!(!b.eq(&c, &func), "the same callee with the arguments swapped is not equal");
    assert!(!b.eq(&d, &func), "the same callee with one argument changed is not equal");
}

/// Enhancement-596, the exact shape that found it: the value numbers of the
/// reproducer's MIR (one `$simparam("gmin")` without a default, then nine
/// `$simparam(name, -1)`), whose FxHash probe sequence put the tenth call in
/// the first call's group with the same tag. With the self-comparison the
/// table answered "equal" and `v62` was replaced by `v17`.
#[test]
fn distinct_calls_are_kept() {
    let raw = r#"
        function %bar(v7, v16, v19, v24, v29, v34, v39, v44, v49, v54, v59) {
            fn0 = const fn %simparam(1) -> 1
            fn1 = const fn %simparam_opt(2) -> 1

        block2:
            v17 = call fn0(v16)
            v22 = call fn1(v19, v7)
            v27 = call fn1(v24, v7)
            v32 = call fn1(v29, v7)
            v37 = call fn1(v34, v7)
            v42 = call fn1(v39, v7)
            v47 = call fn1(v44, v7)
            v52 = call fn1(v49, v7)
            v57 = call fn1(v54, v7)
            v62 = call fn1(v59, v7)
            v68 = optbarrier v17
            v69 = optbarrier v22
            v70 = optbarrier v27
            v71 = optbarrier v32
            v72 = optbarrier v37
            v73 = optbarrier v42
            v74 = optbarrier v47
            v75 = optbarrier v52
            v76 = optbarrier v57
            v77 = optbarrier v62
        }
    "#;
    let (mut func, _) = parse_function(raw).unwrap();
    let mut cfg = ControlFlowGraph::new();
    cfg.compute(&func);
    let mut dom_tree = DominatorTree::default();
    dom_tree.compute(&func, &cfg, true, true, false);
    let mut gvn = super::GVN::default();
    gvn.init(&func, &dom_tree, 3);
    gvn.solve(&mut func);
    gvn.remove_unnecessary_insts(&mut func, &dom_tree);
    gvn.clear(&mut func);
    let out = func.to_debug_string();
    assert_eq!(out.matches("= call ").count(), 10, "every distinct call must survive:\n{out}");
    for (bar, val) in (68..=77).zip([17, 22, 27, 32, 37, 42, 47, 52, 57, 62]) {
        let line = format!("v{bar} = optbarrier v{val}");
        assert!(out.contains(&line), "missing `{line}` in:\n{out}");
    }
}
