use std::mem;

use basedb::lints::LintRegistry;
use basedb::{AstIdMap, ErasedAstId, LintAttrs};
use syntax::ast::{self, ArgListOwner, AstToken, AttrIter, AttrsOwner, FunctionRef};
use syntax::{AstNode, SyntaxKind};
use syntax::name::AsName;
use syntax::AstPtr;

// use tracing::debug;
use super::{Body, BodySourceMap};
use crate::db::HirDefDB;
use crate::expr::{CaseCond, Event, GlobalEvent};
use crate::nameres::DefMapSource;
use crate::{BlockLoc, Case, CaseKind, CaseMask, Expr, ExprId, Intern, Literal, Path, ScopeId, Stmt, StmtId};

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
                // `-2147483648` is the smallest `integer`, but it parses as unary minus
                // applied to `2147483648`, whose magnitude does NOT fit i32. Left alone the
                // operand becomes a `Float` literal and the whole expression is then
                // evaluated in REAL arithmetic: `(-2147483648)/3` rounds to -715827883
                // instead of truncating to -715827882, and `(-2147483648)-1` saturates on
                // the store back to `integer` instead of wrapping to i32::MAX. The runtime
                // path (the same value arriving from a parameter) is correct throughout, so
                // one expression gave two answers depending on whether it was folded. Fold
                // the sign into the literal so it stays an `integer`.
                if let (Some(ast::UnaryOp::Neg), Some(ast::Expr::Literal(lit))) =
                    (e.op_kind(), e.expr())
                {
                    if let ast::LiteralKind::IntNumber(int) = lit.kind() {
                        if int.value().is_none() {
                            if let Some(val) = int.value_negated() {
                                return self.alloc_expr(
                                    Expr::Literal(Literal::Int(val)),
                                    AstPtr::new(&expr),
                                );
                            }
                        }
                    }
                }
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

            // Enhancement-34: `{...}` concatenation / `{n{...}}` replication
            ast::Expr::ConcatExpr(e) => {
                let elems = e.exprs().map(|expr| self.collect_expr(expr)).collect();
                Expr::Concat { rep: None, elems }
            }
            ast::Expr::ReplicationExpr(e) => {
                let rep = self.collect_opt_expr(e.count());
                let elems = e.elems().map(|expr| self.collect_expr(expr)).collect();
                Expr::Concat { rep: Some(rep), elems }
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
                    let indices = bit_select.indices().map(|e| self.collect_expr(e)).collect();
                    let id = self
                        .alloc_expr(Expr::BitSelect { base, indices }, AstPtr::new(&expr));
                    // part-selects are only legal in instance port connections,
                    // which elaboration consumes textually and never body-lowers;
                    // anything landing here is an error (Enhancement-85)
                    if bit_select.is_part_select() {
                        self.body.stray_part_selects.push(id);
                    }
                    return id;
                } else {
                    return self.missing_expr();
                }
            }

            ast::Expr::Literal(lit) => {
                let id =
                    self.alloc_expr(Expr::Literal(Literal::new(lit.kind())), AstPtr::new(&expr));
                // don't-care digits ('b1x?) are only meaningful as casex/casez
                // items; track every such literal -- collect_case_stmt removes
                // the legal ones and validation rejects the rest (E-78)
                if let ast::LiteralKind::IntNumber(int) = lit.kind() {
                    if int.dontcare_masks().is_some() {
                        self.body.stray_dontcare_literals.push(id);
                    }
                }
                return id;
            }
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
            ast::Stmt::DoWhileStmt(stmt) => {
                let cond = self.collect_opt_expr(stmt.condition());
                let body = self.collect_opt_stmt(stmt.body());
                Stmt::DoWhile { cond, body }
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
        // Enhancement-59: the event expression is a flat list of one or more
        // units separated by the `or` keyword (LRM 5.10) -- the body fires
        // when ANY unit fires. Walk the EVENT_STMT's direct children in
        // syntax order, segmenting on OR_KW tokens; each segment is either a
        // bare `initial_step`/`final_step` (with its own optional phase
        // strings) or a `cross`/`above`/`timer` call expression. Note the
        // statement body is itself a child node -- stop at the closing `)`.
        #[derive(Default)]
        struct Unit {
            step: Option<GlobalEvent>,
            phases: Vec<String>,
            condition: Option<ast::Expr>,
        }
        let mut units: Vec<Unit> = vec![Unit::default()];
        for child in event_stmt.syntax().children_with_tokens() {
            match &child {
                syntax::NodeOrToken::Token(tok) => match tok.kind() {
                    SyntaxKind::OR_KW => units.push(Unit::default()),
                    SyntaxKind::INITIAL_STEP_KW => {
                        units.last_mut().unwrap().step = Some(GlobalEvent::InitialStep)
                    }
                    SyntaxKind::FINAL_STEP_KW => {
                        units.last_mut().unwrap().step = Some(GlobalEvent::FinalStep)
                    }
                    SyntaxKind::STR_LIT => {
                        if let Some(lit) = ast::StrLit::cast(tok.clone()) {
                            units.last_mut().unwrap().phases.push(lit.unescaped_value());
                        }
                    }
                    SyntaxKind::R_PAREN => break,
                    _ => (),
                },
                syntax::NodeOrToken::Node(node) => {
                    if let Some(expr) = ast::Expr::cast(node.clone()) {
                        let unit = units.last_mut().unwrap();
                        if unit.condition.is_none() {
                            unit.condition = Some(expr);
                        }
                    }
                }
            }
        }

        let mut events = Vec::with_capacity(units.len());
        for unit in units {
            let event = match (unit.step, unit.condition) {
                (Some(kind), _) => Event::Global { kind, phases: unit.phases },
                (None, Some(condition)) => match self.event_from_condition(&condition) {
                    Some(ev) => ev,
                    // malformed unit: degrade the WHOLE event control to an
                    // unconditional body, the established Enhancement-8
                    // convention (see `event_from_condition`'s doc comment)
                    None => return self.collect_opt_stmt(event_stmt.stmt()),
                },
                (None, None) => return self.collect_opt_stmt(event_stmt.stmt()),
            };
            events.push(event);
        }
        let event = if events.len() == 1 {
            events.pop().unwrap()
        } else {
            Event::Or(events.into_boxed_slice())
        };
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
    fn event_from_condition(&mut self, condition: &ast::Expr) -> Option<Event> {
        let ast::Expr::Call(call) = condition else {
            return None;
        };
        let name = call.function_ref().and_then(|fun| match fun {
            FunctionRef::Path(path) => path.as_raw_ident().map(|t| t.text().to_owned()),
            FunctionRef::SysFun(_) => None,
        });
        let mut args = call.arg_list().map(|list| list.args()).into_iter().flatten();

        let event = match name.as_deref() {
            // Enhancement-399: every argument is collected now. Previously the
            // iterator was simply abandoned after the modelled ones, so surplus
            // arguments vanished without a word, and a MISSING first argument
            // (`@(cross())`) made this function return None -- which degrades the
            // whole event control to an unconditional body, so the guarded
            // statement ran on every evaluation. A missing first argument is
            // recorded as `Expr::Missing` instead, leaving a real event for
            // `hir_ty::validation` to reject.
            Some("cross") => {
                let expr = match args.next() {
                    Some(e) => self.collect_expr(e),
                    None => self.missing_expr(),
                };
                let dir = args.next().map(|e| self.collect_expr(e));
                let time_tol = args.next().map(|e| self.collect_expr(e));
                let expr_tol = args.next().map(|e| self.collect_expr(e));
                let surplus: Box<[_]> = args.map(|e| self.collect_expr(e)).collect();
                Event::Cross { expr, dir, time_tol, expr_tol, surplus }
            }
            Some("above") => {
                let expr = match args.next() {
                    Some(e) => self.collect_expr(e),
                    None => self.missing_expr(),
                };
                let tol = args.next().map(|e| self.collect_expr(e));
                let surplus: Box<[_]> = args.map(|e| self.collect_expr(e)).collect();
                Event::Above { expr, tol, surplus }
            }
            Some("timer") => {
                let t0 = match args.next() {
                    Some(e) => self.collect_expr(e),
                    None => self.missing_expr(),
                };
                let period = args.next().map(|e| self.collect_expr(e));
                let tol = args.next().map(|e| self.collect_expr(e));
                let surplus: Box<[_]> = args.map(|e| self.collect_expr(e)).collect();
                Event::Timer { t0, period, tol, surplus }
            }
            _ => return None,
        };
        Some(event)
    }

    fn collect_case_stmt(&mut self, case_stmt: &ast::CaseStmt) -> Stmt {
        // case / casex / casez share the CASE_STMT node; the keyword token
        // distinguishes them (Enhancement-78)
        let kind = case_stmt
            .syntax()
            .children_with_tokens()
            .filter_map(|it| it.into_token())
            .find_map(|t| match t.kind() {
                SyntaxKind::CASE_KW => Some(CaseKind::Case),
                SyntaxKind::CASEX_KW => Some(CaseKind::CaseX),
                SyntaxKind::CASEZ_KW => Some(CaseKind::CaseZ),
                _ => None,
            })
            .unwrap_or(CaseKind::Case);
        let discr = self.collect_opt_expr(case_stmt.discriminant());
        let case_arms = case_stmt
            .cases()
            .map(|case| {
                let (cond, masks) = if case.default_token().is_some() {
                    debug_assert_eq!(case.exprs().next(), None);
                    (CaseCond::Default, Vec::new())
                } else {
                    let mut masks = Vec::new();
                    let vals = case
                        .exprs()
                        .map(|e| {
                            let id = self.collect_expr(e.clone());
                            masks.push(self.case_item_mask(kind, &e, id));
                            id
                        })
                        .collect();
                    (CaseCond::Vals(vals), masks)
                };
                Case { cond, masks, body: self.collect_opt_stmt(case.stmt()) }
            })
            .collect();

        Stmt::Case { kind, discr, case_arms }
    }

    /// The comparison mask of one casex/casez item: a *directly written*
    /// integer literal with don't-care digits contributes a partial-care
    /// mask (and is legal there, so it leaves the stray list); everything
    /// else compares in full.
    fn case_item_mask(&mut self, kind: CaseKind, e: &ast::Expr, id: ExprId) -> CaseMask {
        if kind == CaseKind::Case {
            return CaseMask::FULL;
        }
        let int = match e {
            ast::Expr::Literal(lit) => match lit.kind() {
                ast::LiteralKind::IntNumber(int) => int,
                _ => return CaseMask::FULL,
            },
            _ => return CaseMask::FULL,
        };
        match int.dontcare_masks() {
            Some((x_mask, z_mask)) => {
                self.body.stray_dontcare_literals.retain(|&it| it != id);
                let care = match kind {
                    CaseKind::CaseX => !(x_mask | z_mask),
                    _ => !z_mask,
                };
                CaseMask { care, had_x: x_mask != 0 }
            }
            None => CaseMask::FULL,
        }
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
