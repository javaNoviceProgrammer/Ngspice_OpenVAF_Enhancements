//! Enhancement-702 (hunt F6 of 2026-09-21): which run-time `$table_model` data
//! arrays depend on the solution. Computed once at the end of inference
//! (`InferenceResult::captured_table_data`), read by the `table_data_captured`
//! lint and by `hir_lower`'s capture of the knots (LRM 9.21.1).
use ahash::HashSet;
use hir_def::body::Body;
use hir_def::expr::{CaseCond, Event, GlobalEvent};
use hir_def::{BuiltIn, Expr, ExprId, Stmt, StmtId};
use syntax::ast::AssignOp;
use syntax::name::Name;

use crate::inference::{AssignDst, InferenceResult, ResolvedFun};

/// Enhancement-702 (hunt F6 of 2026-09-21): LRM 9.21.1 -- "the state of the data
/// source is captured on the first call to the table model function. Any change
/// after this point is ignored." The run-time array form (E-389) now captures its
/// arrays at the instance's first evaluation of each analysis, so an element the
/// body computes from a potential, a flow or the time is read once and the
/// dependence the author wrote never reaches the table. This is the one analysis
/// behind two consumers that must agree: the `table_data_captured` lint reports
/// every entry, and the lowering latches exactly these tables and leaves every
/// other table's data live. A table built from parameters, constants, the
/// temperature or an `@(initial_step)` fill cannot change between two setups, so
/// its capture would be a no-op that only costs the compile-time folding and the
/// setup-phase hoisting of its interpolant (a 256-knot cubic table that folds
/// today does not compile as an evaluation-time spline).
///
/// Taint is by variable name, whole body, without flow sensitivity, as
/// `lint_mfactor_double_scaling` has it: a source is a potential or flow probe or
/// `$abstime`/`$realtime`; an assignment whose value (or whose element index)
/// reads a source or a tainted name taints its destination, and so does one under
/// an `if`, `case`, loop or event whose control reads one -- the element's value
/// then depends on the solution through the path taken. An assignment inside
/// `@(initial_step)` does not taint: it runs at the first evaluation only, which
/// is the capture. A table whose two data arrays are untainted (parameters,
/// constants, `$temperature`) is not reported -- nothing about it changes.
pub fn captured_table_data(body: &Body, infere: &InferenceResult) -> Vec<(StmtId, ExprId)> {
    fn root_name(body: &Body, expr: ExprId) -> Option<Name> {
        match body.exprs[expr] {
            Expr::Path { ref path, .. } => path.segments.last().cloned(),
            Expr::BitSelect { ref base, .. } => base.segments.last().cloned(),
            _ => None,
        }
    }
    fn reads_solution(
        body: &Body,
        infere: &InferenceResult,
        expr: ExprId,
        tainted: &HashSet<Name>,
    ) -> bool {
        if let Some(ResolvedFun::BuiltIn(b)) = infere.resolved_calls.get(&expr) {
            if matches!(
                b,
                BuiltIn::potential | BuiltIn::flow | BuiltIn::abstime | BuiltIn::realtime
            ) {
                return true;
            }
        }
        match body.exprs[expr] {
            Expr::Path { ref path, .. } => {
                path.segments.last().map_or(false, |n| tainted.contains(n))
            }
            Expr::BitSelect { ref base, ref indices } => {
                base.segments.last().map_or(false, |n| tainted.contains(n))
                    || indices.iter().any(|&i| reads_solution(body, infere, i, tainted))
            }
            ref e => {
                let mut found = false;
                e.walk_child_exprs(|child| {
                    if !found && reads_solution(body, infere, child, tainted) {
                        found = true;
                    }
                });
                found
            }
        }
    }
    /// One pass over a statement tree. `dependent`: under a control whose value
    /// reads the solution; `initial`: inside `@(initial_step)`.
    fn walk(
        body: &Body,
        infere: &InferenceResult,
        stmt: StmtId,
        dependent: bool,
        initial: bool,
        tainted: &mut HashSet<Name>,
        changed: &mut bool,
    ) {
        match body.stmts[stmt] {
            Stmt::Assignment { dst, val, assignment_kind: AssignOp::Assign } => {
                if initial
                    || !matches!(
                        infere.assignment_destination.get(&stmt),
                        Some(AssignDst::Var(_))
                    )
                {
                    return;
                }
                let Some(name) = root_name(body, dst) else { return };
                if tainted.contains(&name) {
                    return;
                }
                let index_dependent = match body.exprs[dst] {
                    Expr::BitSelect { ref indices, .. } => {
                        indices.iter().any(|&i| reads_solution(body, infere, i, tainted))
                    }
                    _ => false,
                };
                if dependent || index_dependent || reads_solution(body, infere, val, tainted) {
                    tainted.insert(name);
                    *changed = true;
                }
            }
            Stmt::Block { body: ref stmts, .. } => {
                for &s in stmts.iter() {
                    walk(body, infere, s, dependent, initial, tainted, changed);
                }
            }
            Stmt::If { cond, then_branch, else_branch } => {
                let dep = dependent || reads_solution(body, infere, cond, tainted);
                walk(body, infere, then_branch, dep, initial, tainted, changed);
                walk(body, infere, else_branch, dep, initial, tainted, changed);
            }
            Stmt::ForLoop { init, cond, incr, body: loop_body } => {
                let dep = dependent || reads_solution(body, infere, cond, tainted);
                walk(body, infere, init, dependent, initial, tainted, changed);
                walk(body, infere, incr, dep, initial, tainted, changed);
                walk(body, infere, loop_body, dep, initial, tainted, changed);
            }
            Stmt::WhileLoop { cond, body: loop_body }
            | Stmt::DoWhile { cond, body: loop_body } => {
                let dep = dependent || reads_solution(body, infere, cond, tainted);
                walk(body, infere, loop_body, dep, initial, tainted, changed);
            }
            Stmt::Repeat { count, body: loop_body } => {
                let dep = dependent || reads_solution(body, infere, count, tainted);
                walk(body, infere, loop_body, dep, initial, tainted, changed);
            }
            Stmt::Case { discr, ref case_arms, .. } => {
                let mut dep = dependent || reads_solution(body, infere, discr, tainted);
                for arm in case_arms {
                    if let CaseCond::Vals(ref vals) = arm.cond {
                        dep = dep || vals.iter().any(|&v| reads_solution(body, infere, v, tainted));
                    }
                }
                for arm in case_arms {
                    walk(body, infere, arm.body, dep, initial, tainted, changed);
                }
            }
            Stmt::EventControl { ref event, body: event_body } => {
                let initial_step =
                    matches!(event, Event::Global { kind: GlobalEvent::InitialStep, .. });
                // a cross/above/timer event is a control that reads the solution
                let dep = dependent || !matches!(event, Event::Global { .. });
                walk(body, infere, event_body, dep, initial || initial_step, tainted, changed);
            }
            _ => {}
        }
    }
    /// The expressions a statement evaluates itself (not those of nested statements).
    fn stmt_exprs(body: &Body, stmt: StmtId) -> Vec<ExprId> {
        match body.stmts[stmt] {
            Stmt::Expr(e) => vec![e],
            Stmt::Assignment { dst, val, .. } => vec![dst, val],
            Stmt::If { cond, .. }
            | Stmt::ForLoop { cond, .. }
            | Stmt::WhileLoop { cond, .. }
            | Stmt::DoWhile { cond, .. } => vec![cond],
            Stmt::Repeat { count, .. } => vec![count],
            Stmt::Case { discr, ref case_arms, .. } => {
                let mut v = vec![discr];
                for arm in case_arms {
                    if let CaseCond::Vals(ref vals) = arm.cond {
                        v.extend(vals.iter().copied());
                    }
                }
                v
            }
            _ => Vec::new(),
        }
    }
    fn visit(body: &Body, expr: ExprId, f: &mut impl FnMut(ExprId)) {
        f(expr);
        body.exprs[expr].walk_child_exprs(|child| visit(body, child, f));
    }

    let mut tainted: HashSet<Name> = HashSet::default();
    loop {
        let mut changed = false;
        for &s in body.entry_stmts.iter() {
            walk(body, infere, s, false, false, &mut tainted, &mut changed);
        }
        if !changed {
            break;
        }
    }
    let mut found = Vec::new();
    if tainted.is_empty() {
        return found;
    }
    // the run-time 1-D form, keyed exactly as `hir_lower::expr::lower_table_model`
    // keys it: two 1-D array references after the input, at most a control behind
    let is_arr = |e: ExprId| {
        infere.array_var_refs.contains_key(&e) || infere.array_param_refs.contains_key(&e)
    };
    let ndim = |e: ExprId| infere.array_shapes.get(&e).map_or(1, |s| s.len());
    for (stmt, _) in body.stmts.iter_enumerated() {
        for root in stmt_exprs(body, stmt) {
            visit(body, root, &mut |expr| {
                let Expr::Call { ref args, .. } = body.exprs[expr] else { return };
                if !matches!(
                    infere.resolved_calls.get(&expr),
                    Some(ResolvedFun::BuiltIn(BuiltIn::table_model))
                ) || !(3..=4).contains(&args.len())
                    || !is_arr(args[1])
                    || ndim(args[1]) != 1
                    || !is_arr(args[2])
                    || ndim(args[2]) != 1
                    || (args.len() == 4 && is_arr(args[3]))
                {
                    return;
                }
                for &data in &args[1..3] {
                    if infere.array_var_refs.contains_key(&data)
                        && root_name(body, data).map_or(false, |n| tainted.contains(&n))
                    {
                        found.push((stmt, data));
                        return;
                    }
                }
            });
        }
    }
    found
}
