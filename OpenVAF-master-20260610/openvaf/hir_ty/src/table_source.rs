//! Book audit (lookup tables), LRM 9.21.1: the ARRAY data source of a
//! `$table_model` -- column arrays, or one 2-D array -- is read when the model
//! is compiled, exactly as a data file is, so every element must have a value
//! the compiler can pin down. This module decides that once, for validation
//! (which reports why a table cannot be built) and for lowering (which needs
//! the values), so the two cannot disagree.
//!
//! An element's value is fixed at compile time when it is
//!   * never written by the module, and its declaration initialiser folds --
//!     a literal, `+ - * /` of such, or a `localparam`; or
//!   * written exactly once, by a straight-line assignment -- in an `analog
//!     initial` block, an `@(initial_step)` block, or the analog block itself,
//!     not under a condition, in a loop or through a function argument -- of a
//!     value that folds the same way. That is the idiom *A Practical Guide to
//!     Verilog-A* teaches: fill `y[i]`, `x[i]`, `f[i]` in `analog initial`,
//!     then `$table_model(yy, xx, y, x, f)`.
//!
//! An overridable `parameter` is never such a value: the model card may
//! replace it after the table has been built -- the rule the inline `'{...}`
//! data has always followed.

use ahash::AHashMap;
use hir_def::body::Body;
use hir_def::expr::{Event, GlobalEvent};
use hir_def::nameres::{DefMapSource, ScopeOrigin};
use hir_def::{DefWithBodyId, Expr, Lookup, ParamId, Stmt, StmtId, VarId};

use crate::db::HirTyDB;
use crate::inference::{ArrayAssign, AssignDst, InferenceResult, ResolvedFun};
use crate::types::Ty;
use crate::validation::{const_num_in, const_param_value};

/// The compile-time value of every element of an array variable used as
/// `$table_model` data, in the order given, or the reason one of them has none.
pub fn table_array_const_values(db: &dyn HirTyDB, elems: &[VarId]) -> Result<Vec<f64>, String> {
    let Some(&first) = elems.first() else { return Ok(Vec::new()) };
    let mut writes: AHashMap<VarId, Writes> =
        elems.iter().map(|&v| (v, Writes::default())).collect();
    for owner in owner_bodies(db, first) {
        let body = db.body(owner);
        let infer = db.inference_result(owner);
        // every write, wherever it stands
        for (stmt, _) in body.stmts.iter_enumerated() {
            for (var, _) in stmt_writes(db, &body, &infer, stmt) {
                if let Some(w) = writes.get_mut(&var) {
                    w.total += 1;
                }
            }
        }
        // an array, or an element, passed to an analog function may be written
        // through an output argument
        for (expr, resolved) in infer.resolved_calls.iter() {
            if !matches!(resolved, ResolvedFun::User { .. }) {
                continue;
            }
            let Expr::Call { ref args, .. } = body.exprs[*expr] else { continue };
            for &a in args {
                if let Some(vars) = infer.array_var_refs.get(&a) {
                    for v in vars {
                        if let Some(w) = writes.get_mut(v) {
                            w.total += 1;
                        }
                    }
                }
                if let Some(Ty::Var(_, v)) = infer.expr_types.get(a) {
                    if let Some(w) = writes.get_mut(v) {
                        w.total += 1;
                    }
                }
            }
        }
        // the straight-line writes, with their values
        for &stmt in body.entry_stmts.iter() {
            straight_line_writes(db, &body, &infer, stmt, &mut writes);
        }
    }
    let mut out = Vec::with_capacity(elems.len());
    for &v in elems {
        let w = &writes[&v];
        let name = &db.var_data(v).name;
        if w.total > w.straight.len() {
            return Err(format!(
                "`{name}` is written at run time -- under a condition, in a loop, from an \
                 event other than `initial_step`, through an analog function argument, or by \
                 an array copy -- so its value is not fixed when the table is built"
            ));
        }
        match w.straight.as_slice() {
            [] => match var_init_value(db, v) {
                Some(x) => out.push(x),
                None => {
                    return Err(format!(
                        "the initialiser of `{name}` is not a compile-time constant; a literal \
                         or a `localparam` works here, an overridable `parameter` cannot, \
                         because the model card may replace it after the table has been built"
                    ))
                }
            },
            [Some(x)] => out.push(*x),
            [None] => {
                return Err(format!(
                    "`{name}` is assigned a value that is not a compile-time constant; a \
                     literal or a `localparam` works here, an overridable `parameter` cannot, \
                     because the model card may replace it after the table has been built"
                ))
            }
            _ => {
                return Err(format!(
                    "`{name}` is assigned more than once, and the table is built from one value"
                ))
            }
        }
    }
    Ok(out)
}

/// The parameter-array twin: a `localparam` array's element values, or the
/// reason it has none.
pub fn table_param_const_values(
    db: &dyn HirTyDB,
    elems: &[ParamId],
) -> Result<Vec<f64>, String> {
    elems
        .iter()
        .map(|&p| {
            const_param_value(db, p, 0).ok_or_else(|| {
                let name = &db.param_data(p).name;
                if db.param_data(p).is_local {
                    format!("the value of `{name}` is not a compile-time constant")
                } else {
                    format!(
                        "`{name}` is an overridable `parameter`, which the model card may \
                         replace after the table has been built; declare the array `localparam`"
                    )
                }
            })
        })
        .collect()
}

#[derive(Default)]
struct Writes {
    /// One entry per straight-line assignment: its constant value, or `None`.
    straight: Vec<Option<f64>>,
    /// Every write, straight-line or not.
    total: usize,
}

/// The bodies that may write a variable declared in `var`'s scope: the two
/// bodies of its module (`analog initial` first), or its analog function's.
fn owner_bodies(db: &dyn HirTyDB, var: VarId) -> Vec<DefWithBodyId> {
    let mut scope = var.lookup(db.upcast()).scope;
    loop {
        match scope.src {
            DefMapSource::Function(f) => return vec![DefWithBodyId::FunctionId(f)],
            DefMapSource::Block(b) => scope = b.lookup(db.upcast()).parent(),
            DefMapSource::Root => {
                let map = scope.def_map(db.upcast());
                let mut local = Some(scope.local_scope);
                while let Some(l) = local {
                    match map[l].origin {
                        ScopeOrigin::Module(module) => {
                            return vec![
                                DefWithBodyId::ModuleId { initial: true, module },
                                DefWithBodyId::ModuleId { initial: false, module },
                            ]
                        }
                        ScopeOrigin::Function(f) => return vec![DefWithBodyId::FunctionId(f)],
                        _ => local = map[l].parent(),
                    }
                }
                return Vec::new();
            }
        }
    }
}

/// The variables one statement writes, each with its value when the statement
/// is a plain assignment of a compile-time constant.
fn stmt_writes(
    db: &dyn HirTyDB,
    body: &Body,
    infer: &InferenceResult,
    stmt: StmtId,
) -> Vec<(VarId, Option<f64>)> {
    let Stmt::Assignment { val, .. } = body.stmts[stmt] else { return Vec::new() };
    if let Some(arr) = infer.array_assignments.get(&stmt) {
        return match arr {
            ArrayAssign::Literal(pairs) => pairs
                .iter()
                .map(|&(v, e)| (v, const_num_in(db, body, infer, e, 0)))
                .collect(),
            ArrayAssign::Copy(pairs) => pairs.iter().map(|&(v, _)| (v, None)).collect(),
            ArrayAssign::Concat(pairs) => pairs.iter().map(|&(v, _)| (v, None)).collect(),
            ArrayAssign::ReturnCall { pairs, .. } => {
                pairs.iter().map(|&(v, _)| (v, None)).collect()
            }
        };
    }
    if let Some(dyn_assign) = infer.dynamic_index_assignments.get(&stmt) {
        return dyn_assign.target.elems.iter().map(|&v| (v, None)).collect();
    }
    if let Some(AssignDst::Var(v)) = infer.assignment_destination.get(&stmt) {
        return vec![(*v, const_num_in(db, body, infer, val, 0))];
    }
    Vec::new()
}

/// Records the assignments reachable from `stmt` without passing a condition,
/// a loop or an event other than `initial_step`.
fn straight_line_writes(
    db: &dyn HirTyDB,
    body: &Body,
    infer: &InferenceResult,
    stmt: StmtId,
    writes: &mut AHashMap<VarId, Writes>,
) {
    match body.stmts[stmt] {
        Stmt::Block { body: ref stmts, .. } => {
            for &s in stmts {
                straight_line_writes(db, body, infer, s, writes);
            }
        }
        Stmt::EventControl {
            event: Event::Global { kind: GlobalEvent::InitialStep, .. },
            body: inner,
        } => straight_line_writes(db, body, infer, inner, writes),
        Stmt::Assignment { .. } => {
            for (v, val) in stmt_writes(db, body, infer, stmt) {
                if let Some(w) = writes.get_mut(&v) {
                    w.straight.push(val);
                }
            }
        }
        _ => {}
    }
}

/// The folded declaration initialiser of a variable (its type's zero when it
/// has none).
fn var_init_value(db: &dyn HirTyDB, var: VarId) -> Option<f64> {
    let owner = DefWithBodyId::VarId(var);
    let body = db.body(owner);
    let infer = db.inference_result(owner);
    let &stmt = body.entry_stmts.first()?;
    let Stmt::Expr(e) = body.stmts[stmt] else { return None };
    const_num_in(db, &body, &infer, e, 0)
}
