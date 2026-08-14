use std::sync::Arc;

use ahash::AHashMap as HashMap;
use arena::{Arena, ArenaMap};
pub use ast::ConstraintKind;
use basedb::lints::{Lint, LintSrc};
use basedb::{AttrDiagnostic, LintAttrs};
use lower::LowerCtx;
use stdx::Ieee64;
use syntax::{ast, AstNode, AstPtr};

use crate::db::HirDefDB;
use crate::item_tree::{DisciplineAttr, ItemTreeId, ItemTreeNode, NatureAttr};
use crate::nameres::{DefMapSource, LocalScopeId};
use crate::{
    DefWithBodyId, DisciplineAttrLoc, DisciplineLoc, Expr, ExprId, FunctionLoc, Literal, Lookup,
    ModuleLoc, NatureAttrLoc, NatureLoc, ParamId, ParamLoc, ScopeId, Stmt, StmtId, Type, VarLoc,
};

mod lower;
mod pretty;

/// The body of an item
#[derive(Debug, Eq, PartialEq, Default)]
pub struct Body {
    pub exprs: Arena<Expr>,
    pub stmt_scopes: ArenaMap<Stmt, ScopeId>,
    pub stmts: Arena<Stmt>,
    pub entry_stmts: Box<[StmtId]>,
    /// Integer literals spelled with don't-care digits (`'b1x?`) that are
    /// NOT `casex`/`casez` items (those are consumed into [`Case::masks`]
    /// at collection); validation rejects every entry (Enhancement-78).
    pub stray_dontcare_literals: Vec<ExprId>,
    /// Part-select expressions (`base[msb:lsb]`, Enhancement-85) found in
    /// this body. They are only legal in instance port connections (which
    /// never body-lower -- elaboration consumes them textually), so every
    /// entry here is an error, reported by hir_ty body validation.
    pub stray_part_selects: Vec<ExprId>,
}

#[derive(Default, Debug, Eq, PartialEq)]
pub struct BodySourceMap {
    pub expr_map: HashMap<AstPtr<ast::Expr>, ExprId>,
    pub expr_map_back: ArenaMap<Expr, Option<AstPtr<ast::Expr>>>,
    pub stmt_map: HashMap<AstPtr<ast::Stmt>, StmtId>,
    pub stmt_map_back: ArenaMap<Stmt, Option<AstPtr<ast::Stmt>>>,
    lint_map: ArenaMap<Stmt, LintAttrs>,

    /// Diagnostics accumulated during body lowering. These contain `AstPtr`s and so are stored in
    /// the source map (since they're just as volatile).
    pub diagnostics: Vec<AttrDiagnostic>,
}

impl BodySourceMap {
    pub fn lint_src(&self, stmt: StmtId, lint: Lint) -> LintSrc {
        self.lint_map[stmt].lint_src(lint)
    }
}

impl Body {
    pub fn body_with_sourcemap_query(
        db: &dyn HirDefDB,
        id: DefWithBodyId,
    ) -> (Arc<Body>, Arc<BodySourceMap>) {
        let mut body = Body::default();
        let mut source_map = BodySourceMap::default();

        let root_file = id.file(db);
        let tree = db.item_tree(root_file);
        let ast_id_map = db.ast_id_map(root_file);
        let ast = db.parse(root_file).tree();
        let registry = db.lint_registry();

        match id {
            DefWithBodyId::ParamId(param) => {
                let (body, sm, _) = db.param_body_with_sourcemap(param);
                return (body, sm);
            }
            DefWithBodyId::ModuleId { initial, module } => {
                let ModuleLoc { scope, id: item_tree } = module.lookup(db);

                let ast_id = tree[item_tree].ast_id();
                let ast = ast_id_map.get(ast_id).to_node(ast.syntax());
                let curr_scope = (scope, ast_id.into());

                let mut ctx = LowerCtx {
                    db,
                    source_map: &mut source_map,
                    body: &mut body,
                    ast_id_map: &ast_id_map,
                    curr_scope,
                    registry: &registry,
                };
                body.entry_stmts = if initial {
                    ast.analog_initial_behaviour().map(|stmt| ctx.collect_stmt(stmt)).collect()
                } else {
                    ast.analog_behaviour().map(|stmt| ctx.collect_stmt(stmt)).collect()
                };
            }

            DefWithBodyId::FunctionId(id) => {
                let FunctionLoc { id: item_tree, .. } = id.lookup(db);

                let scope = ScopeId {
                    root_file,
                    local_scope: LocalScopeId::from(0u32),
                    src: DefMapSource::Function(id),
                };
                debug_assert_eq!(scope.local_scope, db.function_def_map(id).entry());

                let ast_id = tree[item_tree].ast_id();
                let ast = ast_id_map.get(ast_id).to_node(ast.syntax());
                let curr_scope = (scope, ast_id.into());

                let mut ctx = LowerCtx {
                    db,
                    source_map: &mut source_map,
                    body: &mut body,
                    ast_id_map: &ast_id_map,
                    curr_scope,
                    registry: &registry,
                };
                body.entry_stmts = ast.body().map(|stmt| ctx.collect_stmt(stmt)).collect();
            }
            DefWithBodyId::VarId(var) => {
                let VarLoc { scope, id: item_tree } = var.lookup(db);

                let ast_id = tree[item_tree].ast_id();
                // A synthetic array-return element variable (Enhancement-23) has no `ast::Var` node
                // — its `ast_id` points at the function declaration purely as a placeholder. It is
                // always written by the body before being read, so its default is never actually
                // needed; fall back to the type's zero default rather than dereferencing the AST.
                let var_ast = ast::Var::can_cast(ast_id_map.get_syntax(ast_id.erased()).syntax_kind())
                    .then(|| ast_id_map.get(ast_id).to_node(ast.syntax()));

                let curr_scope = (scope, ast_id.into());
                let mut ctx = LowerCtx {
                    db,
                    source_map: &mut source_map,
                    body: &mut body,
                    ast_id_map: &ast_id_map,
                    curr_scope,
                    registry: &registry,
                };

                let expr = if let Some(expr) = var_ast.as_ref().and_then(|ast| ast.default()) {
                    // An element of an array variable (`real x[0:2] = '{...};`) takes its
                    // initializer from the corresponding leaf of the shared `'{...}` literal
                    // (flat position `array_index`, row-major for multi-dimensional arrays),
                    // exactly like array parameters (Enhancement-43). A missing leaf lowers as
                    // a missing expression, surfacing a proper diagnostic instead of checking
                    // the whole aggregate against the element's scalar type once per element.
                    match tree[item_tree].array_index {
                        Some(pos) => {
                            // Enhancement-457: expands replication elements too
                            let elem = crate::item_tree::flatten_pattern(expr)
                                .into_iter()
                                .nth(pos as usize);
                            ctx.collect_opt_expr(elem)
                        }
                        None => ctx.collect_expr(expr),
                    }
                } else {
                    let default_val = match db.var_data(var).ty {
                        Type::Real => Literal::Float(Ieee64::with_float(0.0)),
                        Type::Integer => Literal::Int(0),
                        // A `string` variable declared without an initializer
                        // defaults to the empty string (Verilog-AMS LRM), rather
                        // than crashing the compiler.
                        Type::String => Literal::String("".into()),
                        _ => unreachable!("invalid var type (TODO arrays)"),
                    };
                    ctx.alloc_expr_desugared(Expr::Literal(default_val))
                };
                let stmt = ctx.alloc_stmt_desugared(Stmt::Expr(expr));
                body.entry_stmts = vec![stmt].into_boxed_slice();
            }
            DefWithBodyId::NatureAttrId(attr) => {
                let NatureAttrLoc { nature, id } = attr.lookup(db);
                let NatureLoc { root_file, id: discipline_id } = nature.lookup(db);

                let nature = &tree[discipline_id];
                let idx = usize::from(nature.attrs.start()) + usize::from(id);
                let attr = &tree[ItemTreeId::<NatureAttr>::from(idx)];

                let ast = ast_id_map.get(attr.ast_id).to_node(ast.syntax());
                let curr_scope = (ScopeId::root(root_file), attr.ast_id.into());

                let mut ctx = LowerCtx {
                    db,
                    source_map: &mut source_map,
                    body: &mut body,
                    ast_id_map: &ast_id_map,
                    curr_scope,
                    registry: &registry,
                };
                let expr = ctx.collect_opt_expr(ast.val());
                let stmt = ctx.alloc_stmt_desugared(Stmt::Expr(expr));
                body.entry_stmts = vec![stmt].into_boxed_slice();
            }
            DefWithBodyId::DisciplineAttrId(attr) => {
                let DisciplineAttrLoc { discipline, id } = attr.lookup(db);
                let DisciplineLoc { root_file, id: discipline_id } = discipline.lookup(db);

                let discipline = &tree[discipline_id];
                let idx = usize::from(discipline.extra_attrs.start()) + usize::from(id);
                let attr = &tree[ItemTreeId::<DisciplineAttr>::from(idx)];
                let ast = ast_id_map.get(attr.ast_id).to_node(ast.syntax());
                let curr_scope = (ScopeId::root(root_file), attr.ast_id.into());

                let mut ctx = LowerCtx {
                    db,
                    source_map: &mut source_map,
                    body: &mut body,
                    ast_id_map: &ast_id_map,
                    curr_scope,
                    registry: &registry,
                };
                let expr = ctx.collect_opt_expr(ast.val());
                let stmt = ctx.alloc_stmt_desugared(Stmt::Expr(expr));
                body.entry_stmts = vec![stmt].into_boxed_slice();
            }
        }

        (Arc::new(body), Arc::new(source_map))
    }

    pub fn param_body_with_sourcemap_query(
        db: &dyn HirDefDB,
        id: ParamId,
    ) -> (Arc<Body>, Arc<BodySourceMap>, ParamExprs) {
        let mut body = Body::default();
        let mut source_map = BodySourceMap::default();
        let root_file = id.lookup(db).scope.root_file;

        let tree = db.item_tree(root_file);
        let ast_id_map = db.ast_id_map(root_file);
        let ast = db.parse(root_file).tree();

        let ParamLoc { id: item_tree, scope } = id.lookup(db);
        let ast_id = tree[item_tree].ast_id();

        let registry = db.lint_registry();
        let mut ctx = LowerCtx {
            db,
            source_map: &mut source_map,
            body: &mut body,
            ast_id_map: &ast_id_map,
            curr_scope: (scope, ast_id.into()),
            registry: &registry,
        };

        // A `paramset`-bound target parameter (Enhancement-21) takes its value from the paramset's
        // `.<param> = <expr>;` override expression instead of its own declared default. The
        // override lives in the `paramset` declaration (a `ParamsetOverride` node) and is lowered
        // here in the twin module's scope, so it resolves the paramset's own parameters. Such a
        // parameter has no constraints of its own (it is an internal localparam now).
        // NOTE: resolved before touching the `ast::Param` node -- a paramset
        // hierarchical-system-parameter localparam (Enhancement-44) has a
        // placeholder `ast_id` (it points at the `ParamsetOverride` node, not
        // an `ast::Param`), so the cast below must not run for it.
        if let Some(ov_ast_id) = tree[item_tree].override_expr {
            let file = db.parse(root_file).tree();
            let ov = ast_id_map.get(ov_ast_id).to_node(file.syntax());
            let default = ctx.collect_opt_expr(ov.val());
            let entry_stmts = vec![ctx.alloc_stmt_desugared(Stmt::Expr(default))];
            body.entry_stmts = entry_stmts.into_boxed_slice();
            return (
                Arc::new(body),
                Arc::new(source_map),
                ParamExprs { default, bounds: Vec::new().into() },
            );
        }

        let ast = ast_id_map.get(ast_id).to_node(ast.syntax());

        // An element of an array-valued parameter takes its default from the corresponding leaf of
        // the shared `'{...}` array literal (flat declaration-order position `array_index`). The
        // literal is nested for a multi-dimensional parameter (`'{'{..},'{..}}`), so it is
        // flattened row-major before indexing.
        let default = match tree[item_tree].array_index {
            Some(pos) => {
                // Enhancement-457: expands replication elements too
                let elem = ast
                    .default()
                    .map(crate::item_tree::flatten_pattern)
                    .and_then(|f| f.into_iter().nth(pos as usize));
                ctx.collect_opt_expr(elem)
            }
            None => ctx.collect_opt_expr(ast.default()),
        };
        let mut entry_stmts = vec![ctx.alloc_stmt_desugared(Stmt::Expr(default))];

        let bounds = ast
            .constraints()
            .filter_map(|constraint| {
                let kind = constraint.kind()?;
                let val = match constraint.val()? {
                    ast::ConstraintValue::Val(val) => {
                        let val = ctx.collect_expr(val);
                        let stmt = ctx.alloc_stmt_desugared(Stmt::Expr(val));
                        entry_stmts.push(stmt);
                        ConstraintValue::Value(val)
                    }
                    ast::ConstraintValue::Range(range) => {
                        let start = ctx.collect_opt_expr(range.start());
                        let stmt = ctx.alloc_stmt_desugared(Stmt::Expr(start));
                        entry_stmts.push(stmt);

                        let end = ctx.collect_opt_expr(range.end());
                        let stmt = ctx.alloc_stmt_desugared(Stmt::Expr(end));
                        entry_stmts.push(stmt);

                        ConstraintValue::Range(Range {
                            start,
                            start_inclusive: range.start_inclusive(),
                            end,
                            end_inclusive: range.end_inclusive(),
                        })
                    }
                };
                Some(ParamConstraint { kind, val })
            })
            .collect();

        body.entry_stmts = entry_stmts.into_boxed_slice();

        (Arc::new(body), Arc::new(source_map), ParamExprs { default, bounds })
    }
}

#[derive(Debug, Eq, PartialEq, Clone)]
pub struct ParamExprs {
    pub default: ExprId,
    pub bounds: Arc<[ParamConstraint]>,
}

#[derive(Debug, Eq, PartialEq, Clone, Copy)]
pub struct Range {
    pub start: ExprId,
    pub start_inclusive: bool,
    pub end: ExprId,
    pub end_inclusive: bool,
}

#[derive(Debug, Eq, PartialEq, Clone, Copy)]
pub enum ConstraintValue {
    Value(ExprId),
    Range(Range),
}

#[derive(Debug, Eq, PartialEq, Clone, Copy)]
pub struct ParamConstraint {
    pub kind: ConstraintKind,
    pub val: ConstraintValue,
}
