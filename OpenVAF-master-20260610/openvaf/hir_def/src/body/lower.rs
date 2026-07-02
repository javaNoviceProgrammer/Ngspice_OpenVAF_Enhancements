use std::mem;

use basedb::lints::LintRegistry;
use basedb::{AstIdMap, ErasedAstId, LintAttrs};
use syntax::ast::{self, ArgListOwner, AttrIter, AttrsOwner, FunctionRef};
use syntax::name::AsName;
use syntax::AstPtr;

// use tracing::debug;
use super::{Body, BodySourceMap};
use crate::db::HirDefDB;
use crate::expr::{CaseCond, Event, GlobalEvent};
use crate::nameres::DefMapSource;
use crate::{BlockLoc, Case, Expr, ExprId, Intern, Literal, Path, ScopeId, Stmt, StmtId};

pub(super) struct LowerCtx<'a> {
    pub(super) db: &'a dyn HirDefDB,
    pub(super) body: &'a mut Body,
    pub(super) source_map: &'a mut BodySourceMap,
    pub(super) ast_id_map: &'a AstIdMap,
    pub(super) curr_scope: (ScopeId, ErasedAstId),
    pub(super) registry: &'a LintRegistry,
}

impl LowerCtx<'_> {
    pub fn collect_opt_expr(&mut self, expr: Option<ast::Expr>) -> ExprId {
        if let Some(expr) = expr {
            self.collect_expr(expr)
        } else {
            self.missing_expr()
        }
    }

    pub fn collect_expr(&mut self, expr: ast::Expr) -> ExprId {
        let e = match &expr {
            ast::Expr::PrefixExpr(e) => {
                let expr = self.collect_opt_expr(e.expr());
                if let Some(op) = e.op_kind() {
                    Expr::UnaryOp { expr, op }
                } else {
                    Expr::Missing
                }
            }

            ast::Expr::BinExpr(e) => {
                let lhs = self.collect_opt_expr(e.lhs());
                let rhs = self.collect_opt_expr(e.rhs());
                Expr::BinaryOp { lhs, rhs, op: e.op_kind() }
            }

            ast::Expr::ParenExpr(e) => return self.collect_opt_expr(e.expr()),

            ast::Expr::ArrayExpr(e) => {
                let vals = e.exprs().map(|expr| self.collect_expr(expr)).collect();
                Expr::Array(vals)
            }

            ast::Expr::Call(call) => {
                let fun = call.function_ref().and_then(|fun| match fun {
                    FunctionRef::Path(path) => Path::resolve(path),
                    FunctionRef::SysFun(fun) => Some(Path::new_ident(fun.as_name())),
                });

                let args = if let Some(args) = call.arg_list().map(|list| list.args()) {
                    args.map(|arg| self.collect_expr(arg)).collect()
                } else {
                    vec![]
                };

                Expr::Call { fun, args }
            }

            ast::Expr::SelectExpr(e) => {
                let cond = self.collect_opt_expr(e.condition());
                let then_val = self.collect_opt_expr(e.then_val());
                let else_val = self.collect_opt_expr(e.else_val());
                Expr::Select { cond, then_val, else_val }
            }

            // TODO refactor with if let binding and default case is missing expression
            // BLOCK
            ast::Expr::PathExpr(path) => {
                if let Some(path) = path.path().and_then(Path::resolve) {
                    Expr::Path { path, port: false }
                } else {
                    return self.missing_expr();
                }
            }

            ast::Expr::PortFlow(port_flow) => {
                if let Some(path) = port_flow.port().and_then(Path::resolve) {
                    Expr::Path { path, port: true }
                } else {
                    return self.missing_expr();
                }
            }

            ast::Expr::BitSelectExpr(bit_select) => {
                if let Some(base) = bit_select.base().and_then(Path::resolve) {
                    let index = self.collect_opt_expr(bit_select.index());
                    Expr::BitSelect { base, index }
                } else {
                    return self.missing_expr();
                }
            }

            ast::Expr::Literal(lit) => Expr::Literal(Literal::new(lit.kind())),
        };
        self.alloc_expr(e, AstPtr::new(&expr))
    }

    pub fn collect_opt_stmt(&mut self, stmt: Option<ast::Stmt>) -> StmtId {
        match stmt {
            Some(stmt) => self.collect_stmt(stmt),
            None => self.missing_stmt(),
        }
    }

    pub fn collect_stmt(&mut self, stmt: ast::Stmt) -> StmtId {
        let s = match &stmt {
            ast::Stmt::EmptyStmt(_) => Stmt::Empty,
            ast::Stmt::AssignStmt(stmt) => match stmt.assign() {
                Some(a) => Stmt::Assignment {
                    dst: self.collect_opt_expr(a.lval()),
                    val: self.collect_opt_expr(a.rval()),
                    assignment_kind: a.op().unwrap(),
                },
                None => {
                    // debug!(
                    //     tree = debug(stmt),
                    //     src = display(stmt),
                    //     "Assign Statement without assign?"
                    // );
                    Stmt::Missing
                }
            },
            ast::Stmt::ExprStmt(stmt) => Stmt::Expr(self.collect_opt_expr(stmt.expr())),
            ast::Stmt::IfStmt(stmt) => {
                let cond = self.collect_opt_expr(stmt.condition());
                let then_branch = self.collect_opt_stmt(stmt.then_branch());
                let else_branch = self.collect_opt_stmt(stmt.else_branch());
                Stmt::If { cond, then_branch, else_branch }
            }
            ast::Stmt::WhileStmt(stmt) => {
                let cond = self.collect_opt_expr(stmt.condition());
                let body = self.collect_opt_stmt(stmt.body());
                Stmt::WhileLoop { cond, body }
            }
            ast::Stmt::RepeatStmt(stmt) => {
                let count = self.collect_opt_expr(stmt.count());
                let body = self.collect_opt_stmt(stmt.body());
                Stmt::Repeat { count, body }
            }
            ast::Stmt::ForStmt(stmt) => {
                let cond = self.collect_opt_expr(stmt.condition());
                let init = self.collect_opt_stmt(stmt.init());
                let incr = self.collect_opt_stmt(stmt.incr());
                let body = self.collect_opt_stmt(stmt.for_body());
                Stmt::ForLoop { init, cond, incr, body }
            }
            ast::Stmt::DisableStmt(stmt) => match stmt.name() {
                Some(name) => Stmt::Disable { name: name.as_name() },
                None => Stmt::Missing,
            },
            ast::Stmt::CaseStmt(stmt) => self.collect_case_stmt(stmt),
            ast::Stmt::EventStmt(stmt) => return self.collect_event_stmt(stmt),
            ast::Stmt::BlockStmt(stmt) => self.collect_block(stmt),
        };
        self.alloc_stmt(s, AstPtr::new(&stmt), stmt.attrs())
    }

    fn collect_event_stmt(&mut self, event_stmt: &ast::EventStmt) -> StmtId {
        let kind = if event_stmt.initial_step_token().is_some() {
            GlobalEvent::InitialStep
        } else if event_stmt.final_step_token().is_some() {
            GlobalEvent::FinalStep
        } else if let Some(condition) = event_stmt.condition() {
            return self.collect_cross_above_timer(event_stmt, &condition);
        } else {
            return self.collect_opt_stmt(event_stmt.stmt());
        };

        let phases = event_stmt.sim_phases().map(|lit| lit.unescaped_value()).collect();
        let event = Event::Global { kind, phases };
        let stmt = Stmt::EventControl { event, body: self.collect_opt_stmt(event_stmt.stmt()) };

        self.alloc_stmt(stmt, AstPtr::new(event_stmt).cast().unwrap(), event_stmt.attrs())
    }

    /// Recognizes `@(cross(expr, dir))` / `@(above(expr))` /
    /// `@(timer(t0, period))` -- the only expressions ever legal in this
    /// grammar position (see `EventStmt` in `veriloga.ungram`) -- by bare
    /// function name, without going through general path resolution or
    /// builtin-function dispatch: there is no general `cross`/`above`/
    /// `timer` *value*-producing builtin, these three names only mean
    /// anything as an `@(...)` event-control predicate.
    ///
    /// A malformed/unrecognized condition here degrades to the event being
    /// dropped (body always fires unconditionally) rather than a hard
    /// lowering error -- consistent with this module's existing "no
    /// lowering-level diagnostic channel; malformed input degrades safely
    /// rather than panicking" convention (parser-level diagnostics already
    /// caught genuine syntax errors upstream; `hir_ty::validation` is the
    /// right layer for a real "not a valid event-control expression"
    /// diagnostic, not yet wired up here -- see `Enhancement-8.md` known
    /// limitations).
    fn collect_cross_above_timer(
        &mut self,
        event_stmt: &ast::EventStmt,
        condition: &ast::Expr,
    ) -> StmtId {
        let fallback = |this: &mut Self| this.collect_opt_stmt(event_stmt.stmt());

        let ast::Expr::Call(call) = condition else {
            return fallback(self);
        };
        let name = call.function_ref().and_then(|fun| match fun {
            FunctionRef::Path(path) => path.as_raw_ident().map(|t| t.text().to_owned()),
            FunctionRef::SysFun(_) => None,
        });
        let mut args = call.arg_list().map(|list| list.args()).into_iter().flatten();

        let event = match name.as_deref() {
            Some("cross") => {
                let Some(expr) = args.next() else { return fallback(self) };
                let expr = self.collect_expr(expr);
                let dir = args.next().map(|e| self.collect_expr(e));
                Event::Cross { expr, dir }
            }
            Some("above") => {
                let Some(expr) = args.next() else { return fallback(self) };
                let expr = self.collect_expr(expr);
                Event::Above { expr }
            }
            Some("timer") => {
                let Some(t0) = args.next() else { return fallback(self) };
                let t0 = self.collect_expr(t0);
                let period = args.next().map(|e| self.collect_expr(e));
                Event::Timer { t0, period }
            }
            _ => return fallback(self),
        };

        let stmt = Stmt::EventControl { event, body: self.collect_opt_stmt(event_stmt.stmt()) };
        self.alloc_stmt(stmt, AstPtr::new(event_stmt).cast().unwrap(), event_stmt.attrs())
    }

    fn collect_case_stmt(&mut self, case_stmt: &ast::CaseStmt) -> Stmt {
        let discr = self.collect_opt_expr(case_stmt.discriminant());
        let case_arms = case_stmt
            .cases()
            .map(|case| {
                let cond = if case.default_token().is_some() {
                    debug_assert_eq!(case.exprs().next(), None);
                    CaseCond::Default
                } else {
                    let vals = case.exprs().map(|e| self.collect_expr(e)).collect();
                    CaseCond::Vals(vals)
                };
                Case { cond, body: self.collect_opt_stmt(case.stmt()) }
            })
            .collect();

        Stmt::Case { discr, case_arms }
    }

    pub fn collect_block(&mut self, block: &ast::BlockStmt) -> Stmt {
        let ast = self.ast_id_map.ast_id(block);
        let id = BlockLoc { ast, parent: self.curr_scope.0 }.intern(self.db);
        let scope = self.db.block_def_map(id);

        let parent_scope = match scope {
            Some(def_map) => {
                let scope = ScopeId {
                    root_file: self.curr_scope.0.root_file,
                    local_scope: def_map.entry(),
                    src: DefMapSource::Block(id),
                };

                mem::replace(&mut self.curr_scope, (scope, ast.into()))
            }
            None => {
                let scope = self.curr_scope.0;
                mem::replace(&mut self.curr_scope, (scope, ast.into()))
            }
        };

        let body = block.body().map(|stmt| self.collect_stmt(stmt)).collect();

        self.curr_scope = parent_scope;
        let name = block.block_scope().and_then(|scope| scope.name()).map(|name| name.as_name());
        Stmt::Block { name, body }
    }

    fn alloc_expr(&mut self, expr: Expr, ptr: AstPtr<ast::Expr>) -> ExprId {
        let id = self.make_expr(expr, Some(ptr.clone()));
        self.source_map.expr_map.insert(ptr, id);
        id
    }
    // desugared exprs don't have ptr, that's wrong and should be fixed
    // somehow.
    pub(super) fn alloc_expr_desugared(&mut self, expr: Expr) -> ExprId {
        self.make_expr(expr, None)
    }

    fn missing_expr(&mut self) -> ExprId {
        self.alloc_expr_desugared(Expr::Missing)
    }

    fn make_expr(&mut self, expr: Expr, src: Option<AstPtr<ast::Expr>>) -> ExprId {
        let id = self.body.exprs.push_and_get_key(expr);
        self.source_map.expr_map_back.insert(id, src);
        id
    }

    fn alloc_stmt(&mut self, stmt: Stmt, ptr: AstPtr<ast::Stmt>, attrs: AttrIter) -> StmtId {
        let attrs = LintAttrs::resolve(
            self.registry,
            attrs,
            &mut self.source_map.diagnostics,
            self.curr_scope.1,
        );
        let id = self.make_stmt(stmt, Some(ptr.clone()), attrs);
        self.source_map.stmt_map.insert(ptr, id);

        id
    }

    // desugared stmts don't have ptr, that's wrong and should be fixed
    // somehow.
    pub(super) fn alloc_stmt_desugared(&mut self, stmt: Stmt) -> StmtId {
        self.make_stmt(stmt, None, LintAttrs::empty(self.curr_scope.1))
    }

    pub(super) fn missing_stmt(&mut self) -> StmtId {
        self.alloc_stmt_desugared(Stmt::Missing)
    }

    fn make_stmt(
        &mut self,
        stmt: Stmt,
        src: Option<AstPtr<ast::Stmt>>,
        attrs: LintAttrs,
    ) -> StmtId {
        let id = self.body.stmts.push_and_get_key(stmt);
        let id2 = self.body.stmt_scopes.push_and_get_key(self.curr_scope.0);
        let id3 = self.source_map.lint_map.push_and_get_key(attrs);
        debug_assert_eq!(id, id2);
        debug_assert_eq!(id2, id3);
        self.source_map.stmt_map_back.insert(id, src);
        id
    }
}

impl Literal {
    pub fn new(ast: ast::LiteralKind) -> Literal {
        match ast {
            ast::LiteralKind::String(lit) => {
                Literal::String(lit.unescaped_value().into_boxed_str())
            }
            ast::LiteralKind::IntNumber(lit) => match lit.value() {
                Some(int) => Literal::Int(int),
                // doesn't fit in i32 (Verilog-A `integer`'s width) -- still a valid real
                // constant (e.g. a laplace_nd coefficient spelled without a decimal point),
                // so fall back to a float literal instead of erroring/panicking.
                None => Literal::Float(lit.value_as_f64().into()),
            },
            ast::LiteralKind::SiRealNumber(lit) => Literal::Float(lit.value().into()),
            ast::LiteralKind::StdRealNumber(lit) => Literal::Float(lit.value().into()),
            ast::LiteralKind::Inf => {
                // TODO check that this allowed somewhere?
                Literal::Inf
            }
        }
    }
}
