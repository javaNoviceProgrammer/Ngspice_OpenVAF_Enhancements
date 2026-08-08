use rowan::TextRange;
use tokens::SyntaxKind;
use tokens::SyntaxKind::NET_TYPE;

use crate::ast::{
    self, support, ArgListOwner, AttrsOwner, BlockItem, ConstraintValue, Expr, FunctionItem,
    LiteralKind, ModulePortKind, ModulePorts, Name, PathSegmentKind,
};
use crate::name::{kw, kw_comp};
use crate::{match_ast, AstNode, AstPtr, SyntaxError, SyntaxNode, SyntaxNodePtr, T};

pub(crate) fn validate(root: &SyntaxNode, errors: &mut Vec<SyntaxError>) {
    for node in root.descendants() {
        match_ast! {
            match node {
                ast::Path(path) => validate_path(path,errors),
                ast::BlockStmt(block) => validate_block(block, errors),
                ast::Function(fun) => validate_function(fun, errors),
                ast::BranchDecl(decl) => validate_branch_decl(decl, errors),
                ast::DisciplineDecl(decl) => validate_discipline_decl(decl,errors),
                ast::NatureDecl(decl) => validate_nature_decl(decl,errors),
                ast::NatureAttr(attr) => validate_nature_attr(attr,errors),
                ast::Literal(decl) => validate_literal(decl, errors),
                ast::Name(name) => validate_name(name,errors),
                ast::ModuleDecl(module) => validate_module(module,errors),
                ast::ParamDecl(param) => validate_param(param, errors),
                ast::CaseStmt(stmt) => validate_case_stmt(stmt, errors),
                _ => validate_net_type_token(node,errors)
            }
        }
    }
}

/// Enhancement-421: IEEE 1364-2005 9.5 makes more than one `default` arm in a
/// single case statement illegal. openvaf accepted them without a word.
///
/// The behaviour is not wrong -- lowering keeps the arms in order and the first
/// `default` is the one that runs -- which is exactly why this is worth saying:
/// the second arm is unreachable code that looks like it does something. Checked
/// here rather than in the body lowering because this is where the `default`
/// TOKENS are, so the report can point at the offending arm and back at the one
/// that wins.
fn validate_case_stmt(stmt: ast::CaseStmt, errors: &mut Vec<SyntaxError>) {
    let mut first = None;
    for case in stmt.cases() {
        let Some(tok) = case.default_token() else { continue };
        match first {
            None => first = Some(tok.text_range()),
            Some(first) => errors.push(SyntaxError::MultipleCaseDefaults {
                first,
                extra: tok.text_range(),
            }),
        }
    }
}

fn validate_param(param_decl: ast::ParamDecl, errors: &mut Vec<SyntaxError>) {
    let range_allowed =
        param_decl.ty().map_or(true, |ty| ty.integer_token().is_some() | ty.real_token().is_some());
    if range_allowed {
        return;
    }

    for param in param_decl.paras() {
        for constraint in param.constraints() {
            if matches!(constraint.val(), Some(ConstraintValue::Range(_))) {
                if let Some(name) = param.name() {
                    errors.push(SyntaxError::RangeConstraintForNonNumericParameter {
                        param: name.text().to_owned(),
                        range: constraint.syntax().text_range(),
                        ty: param_decl.ty().unwrap().syntax().text_range(),
                    });
                }
            }
        }
    }
}

fn validate_net_type_token(node: SyntaxNode, errors: &mut Vec<SyntaxError>) {
    if matches!(node.kind(), SyntaxKind::NET_DECL | SyntaxKind::PORT_DECL) {
        if let Some(token) = support::token(&node, NET_TYPE) {
            if token.text() != kw::raw::ground {
                errors.push(SyntaxError::IllegalNetType {
                    found: token.text().to_owned(),
                    range: token.text_range(),
                })
            }
        }
    }
}

fn validate_module(module: ast::ModuleDecl, errors: &mut Vec<SyntaxError>) {
    let ports = if let Some(ports) = module.module_ports() { ports } else { return };
    match validate_module_ports(&ports, errors) {
        Some((true, _)) => {
            let body_ports: Vec<_> =
                module.body_ports().map(|port| port.syntax().text_range()).collect();
            if !body_ports.is_empty() {
                errors.push(SyntaxError::IllegalBodyPorts {
                    head: ports.syntax().text_range(),
                    body_ports,
                })
            }
        }
        Some((false, names)) => {
            for port in module.body_ports() {
                if let Some(decl) = port.port_decl() {
                    for name in decl.names() {
                        if names.binary_search_by(|locs| locs[0].text().cmp(&name.text())).is_err()
                        {
                            errors.push(SyntaxError::PortNotDeclaredInModule {
                                head: ports.syntax().text_range(),
                                pos: name.syntax().text_range(),
                                name: name.text().to_owned(),
                            })
                        }
                    }
                }
            }
        }
        None => (),
    }
}

fn validate_module_ports(
    ports: &ModulePorts,
    errors: &mut Vec<SyntaxError>,
) -> Option<(bool, Vec<Vec<ast::Name>>)> {
    let mut names: Vec<Vec<ast::Name>> = Vec::new();
    let mut has_decl = false;
    for port in ports.ports() {
        if let ModulePortKind::Name(name) = port.kind() {
            match names.binary_search_by(|locs| locs[0].text().cmp(&name.text())) {
                Ok(pos) => names[pos].push(name.clone()),
                Err(pos) => names.insert(pos, vec![name.clone()]),
            }
        } else {
            has_decl = true
        }
    }

    if !names.is_empty() && has_decl {
        errors.push(SyntaxError::MixedModuleHead { module_ports: AstPtr::new(ports) });
        // Don't lint body ports when the head is ambiguous
        return None;
    }

    for locs in &names {
        if locs.len() == 1 {
            continue;
        }
        let name = locs[0].text().to_owned();
        errors.push(SyntaxError::DuplicatePort {
            pos: locs.iter().map(|it| it.syntax().text_range()).collect(),
            name,
        })
    }

    Some((has_decl, names))
}

fn is_valid_inf_position(s: SyntaxNode) -> bool {
    if s.kind() == SyntaxKind::RANGE {
        return true;
    }
    if s.parent().map_or(false, |parent| parent.kind() == SyntaxKind::RANGE) {
        if let Some(expr) = ast::PrefixExpr::cast(s) {
            if matches!(expr.op_kind(), Some(ast::UnaryOp::Neg) | None) {
                return true;
            }
        }
    }
    false
}

fn validate_nature_attr(attr: ast::NatureAttr, errors: &mut Vec<SyntaxError>) {
    if attr.name().map_or(false, |name| name.text() == "units") {
        if let Some(Expr::Literal(literal)) = attr.val() {
            if !matches!(literal.kind(), LiteralKind::String(_)) {
                errors.push(SyntaxError::UnitsExpectedStringLiteral {
                    range: literal.syntax().text_range(),
                })
            }
        }
    }
}

fn validate_literal(literal: ast::Literal, errors: &mut Vec<SyntaxError>) {
    let range = literal.syntax().text_range();
    match literal.kind() {
        ast::LiteralKind::Inf => {
            if !literal.syntax.parent().map_or(true, is_valid_inf_position) {
                errors.push(SyntaxError::IllegalInfToken { range });
            }
        }

        // Enhancement-425: a real literal that does not fit in a double.
        //
        // `StdRealNumber::value` is `src.parse().unwrap()` and `SiRealNumber::value`
        // multiplies that by its scale factor. `f64::from_str` does not fail on an
        // overflowing exponent -- it returns an INFINITY -- so `r = 1e309;` compiled
        // clean and the model returned INF at run time, poisoning everything
        // downstream as INF/NaN.
        //
        // This compiler has already decided twice that an overflowing literal is a
        // mistake worth reporting: Enhancement-396 refuses `1e400` inside a
        // `$table_model` data file (its comment names this exact `from_str`
        // behaviour), and Enhancement-422 refuses `abstol = 1e400` on a nature. A
        // bare literal in an expression is the same mistake in the same compiler.
        //
        // ONLY the literal. `1e308*10.0` is also an infinity, but that is ARITHMETIC
        // overflow -- a runtime property of the expression, not a mis-written
        // constant -- and Enhancement-396 drew exactly that line. Underflow is left
        // alone too: `1e-320` is a denormal and `1e-400` is 0.0, both of which IEEE
        // 754 defines and neither of which destroys the rest of the computation.
        ast::LiteralKind::StdRealNumber(lit) => {
            let v = lit.value();
            if v.is_infinite() {
                errors.push(SyntaxError::RealLiteralOverflow { span: range, negative: v < 0.0 });
            }
        }
        ast::LiteralKind::SiRealNumber(lit) => {
            let v = lit.value();
            if v.is_infinite() {
                errors.push(SyntaxError::RealLiteralOverflow { span: range, negative: v < 0.0 });
            }
        }

        // Enhancement-425: a based literal with a ZERO size.
        //
        // IEEE 1364-2005 3.5.1: the size "shall be a non-zero unsigned decimal
        // number". `parse_based_int_masked` ends with `.clamp(1, 32)`, so a zero
        // size silently became ONE BIT and the literal's value bore no relation to
        // its digits: `0'd5` evaluated to 1 (5 masked to one bit), `0'h1` to 1.
        //
        // Checked here rather than in `parse_based_int_masked`: that returns
        // `Option` and `IntNumber::value`'s own documentation says a `None` makes
        // callers fall back to reading the text as a REAL, which would turn one
        // silent wrong answer into another. The clamp's upper bound is left as it
        // is -- a size above 32 truncates, which 3.5.1 explicitly permits (`4'hFF`
        // is 15) and which Verilog-A's 32-bit `integer` makes the only sane reading.
        ast::LiteralKind::IntNumber(lit) => {
            let text = lit.syntax.text();
            if let Some((size, _)) = text.split_once('\'') {
                let size = size.trim();
                if !size.is_empty() && size.bytes().all(|b| b.is_ascii_digit())
                    && size.bytes().all(|b| b == b'0')
                {
                    errors.push(SyntaxError::ZeroWidthLiteral { span: range });
                }
            }
        }

        ast::LiteralKind::String(_) => (),
    }
}

fn validate_path(path: ast::Path, errors: &mut Vec<SyntaxError>) {
    if path.segment_kind() == Some(PathSegmentKind::Root) && path.parent_path().is_none() {
        errors.push(SyntaxError::IllegalRootSegment {
            path_segment: path.segment_token().unwrap().text_range(),
            prefix: None,
        })
    }

    for qual in path.qualifiers() {
        if qual.qualifier().is_some() && path.segment_kind() == Some(PathSegmentKind::Root) {
            errors.push(SyntaxError::IllegalRootSegment {
                path_segment: path.segment_token().unwrap().text_range(),
                prefix: Some(path.top_path().syntax().text_range()),
            })
        }
    }
}

fn validate_block(block: ast::BlockStmt, errors: &mut Vec<SyntaxError>) {
    if block.block_scope().is_some() {
        let mut items = block.items();

        let first_stmt = loop {
            match items.next() {
                Some(BlockItem::Stmt(stmt)) => break stmt,
                Some(BlockItem::ParamDecl(_) | BlockItem::VarDecl(_)) => (),
                None => return,
            }
        };

        let misplaced_items: Vec<_> = items
            .filter_map(|item| {
                matches!(item, ast::BlockItem::VarDecl(_) | ast::BlockItem::ParamDecl(_))
                    .then(|| AstPtr::new(&item))
            })
            .collect();

        if !misplaced_items.is_empty() {
            errors.push(SyntaxError::BlockItemsAfterStmt {
                items: misplaced_items,
                first_stmt: first_stmt.syntax().text_range(),
            })
        }
    } else {
        let items: Vec<_> = block
            .items()
            .filter_map(|item| {
                matches!(item, ast::BlockItem::VarDecl(_) | ast::BlockItem::ParamDecl(_))
                    .then(|| AstPtr::new(&item))
            })
            .collect();

        if !items.is_empty() {
            if let Some(begin_token) = block.begin_token() {
                errors.push(SyntaxError::BlockItemsWithoutScope {
                    items,
                    begin_token: begin_token.text_range(),
                })
            }
        }
    }
}

fn validate_function(fun: ast::Function, errors: &mut Vec<SyntaxError>) {
    let mut items = fun.function_items();

    let body = loop {
        match items.next() {
            Some(FunctionItem::Stmt(stmt)) => break stmt,
            None => {
                errors.push(SyntaxError::FunWithoutBody { fun: fun.syntax().text_range() });
                return;
            }
            _ => (),
        }
    };

    let illegal_items: Vec<_> = items
        .clone()
        .filter(|item| !matches!(item, FunctionItem::Stmt(_)))
        .map(|item| AstPtr::new(&item))
        .collect();

    if !illegal_items.is_empty() {
        errors.push(SyntaxError::FunItemsAfterBody {
            items: illegal_items,
            body: body.syntax().text_range(),
        })
    }

    let additional_bodys: Vec<_> = items
        .filter_map(|item| {
            if let FunctionItem::Stmt(stmt) = item {
                Some(stmt.syntax().text_range())
            } else {
                None
            }
        })
        .collect();

    if !additional_bodys.is_empty() {
        errors.push(SyntaxError::MultipleFunBodys { additional_bodys, body: AstPtr::new(&body) })
    }
}

fn validate_name(name: Name, errors: &mut Vec<SyntaxError>) {
    if let Some(ident) = name.ident_token() {
        let parent = name.syntax().parent();
        let p = parent.as_ref();

        let compat = match ident.text() {
            kw::raw::units if p.map_or(false, |p| p.kind() == SyntaxKind::ATTR) => return,
            kw::raw::units
            | kw::raw::idt_nature
            | kw::raw::ddt_nature
            | kw::raw::abstol
            | kw::raw::access
                if p.map_or(false, |p| p.kind() == SyntaxKind::NATURE_ATTR) =>
            {
                return
            }
            kw::raw::domain | kw::raw::potential | kw::raw::flow
                if p.map_or(false, |p| p.kind() == SyntaxKind::DISCIPLINE_ATTR) =>
            {
                return
            }
            ident if kw::is_reserved(ident) => false,
            ident if kw_comp::is_reserved(ident) => true,
            _ => return,
        };

        errors.push(SyntaxError::ReservedIdentifier {
            src: SyntaxNodePtr::new(name.syntax()),
            compat,
            name: ident.text().to_owned(),
        })
    }
}

fn validate_branch_decl(decl: ast::BranchDecl, errors: &mut Vec<SyntaxError>) {
    if let Some(arg_list) = decl.arg_list() {
        match arg_list.args().count() {
            1 => {
                let arg = arg_list.args().next().unwrap();
                match arg {
                    ast::Expr::PortFlow(_) => (),
                    ast::Expr::PathExpr(path)
                        if path.path().map_or(true, |path| path.qualifier().is_none()) => {}
                    ast::Expr::BitSelectExpr(_) => (),
                    _ => errors.push(SyntaxError::IllegalBranchNodeExpr {
                        single: true,
                        illegal_nodes: vec![arg.syntax().text_range()],
                    }),
                }
            }
            2 => {
                let arg1 = arg_list.args().next().unwrap();
                let arg2 = arg_list.args().nth(1).unwrap();

                let mut illegal_nodes = Vec::new();

                let is_valid_endpoint =
                    |e: &ast::Expr| e.as_path().is_some() || matches!(e, ast::Expr::BitSelectExpr(_));

                if !is_valid_endpoint(&arg1) {
                    illegal_nodes.push(arg1.syntax().text_range())
                }

                if !is_valid_endpoint(&arg2) {
                    illegal_nodes.push(arg2.syntax().text_range())
                }

                if !illegal_nodes.is_empty() {
                    errors.push(SyntaxError::IllegalBranchNodeExpr { single: false, illegal_nodes })
                }
            }
            cnt => errors.push(SyntaxError::IllegalBranchNodeCnt {
                cnt,
                arg_list: arg_list.syntax().text_range(),
            }),
        }
    }
}

fn validate_nature_decl(nature: ast::NatureDecl, errors: &mut Vec<SyntaxError>) {
    if let Some(parent) = nature.parent() {
        check_nature_path(&parent, errors)
    }
    for attr in nature.attrs() {
        if let (Some(name), Some(val)) = (attr.name(), attr.val()) {
            let name_text = name.syntax().text();
            if name_text == "ddt_nature" || name_text == "idt_nature" {
                check_nature_ref_attr(&val, errors)
            } else if name_text == "access" && val.as_raw_ident().is_none() {
                errors.push(SyntaxError::IllegalAttriubte {
                    attr: "access",
                    expected: "an identifier",
                    range: val.syntax().text_range(),
                })
            }
        }
    }
}

fn check_nature_path(path: &ast::Path, errors: &mut Vec<SyntaxError>) {
    if let Some(segment) = path.segment_token() {
        match path.qualifiers().count() {
            0 => (),
            // Enhancement-39: a nature may also be referenced through a discipline --
            // `discipline.potential` / `discipline.flow` -- both as the parent of a
            // derived nature (`nature X : electrical.flow;`) and in
            // `ddt_nature`/`idt_nature` attribute values. The item-tree lowering
            // (`lower_nature_path`) has always supported these forms; the validation
            // just didn't whitelist them.
            1 if matches!(
                segment.text(),
                "ddt_nature" | "idt_nature" | "potential" | "flow"
            ) => (),
            _ => errors.push(SyntaxError::IllegalNatureIdent { range: path.syntax().text_range() }),
        }
    }
}

fn check_nature_ref_attr(val: &Expr, errors: &mut Vec<SyntaxError>) {
    if let Expr::PathExpr(path) = val {
        if let Some(path) = path.path() {
            check_nature_path(&path, errors)
        }
    } else if val.syntax().children_with_tokens().all(|t| t.kind() != SyntaxKind::ERROR) {
        errors.push(SyntaxError::IllegalNatureIdent { range: val.syntax().text_range() })
    }
}

fn validate_discipline_decl(discipline: ast::DisciplineDecl, errors: &mut Vec<SyntaxError>) {
    // LRM 3.6.2.2 (Enhancement-50): nature bindings imply the continuous
    // domain -- a `domain discrete` binding alongside a `potential`/`flow`
    // nature binding is an error.
    let mut discrete_range = None;
    let mut nature_range = None;
    for attr in discipline.discipline_attrs() {
        if let Some(name) = attr.name() {
            let is_overwrite = match name.qualifier() {
                Some(qual)
                    if (qual.syntax().text() == "potential" || qual.syntax.text() == "flow")
                        && qual.qualifier().is_none() =>
                {
                    true
                }
                None => false,
                _ => {
                    errors.push(SyntaxError::IllegalDisciplineAttrIdent {
                        range: name.syntax().text_range(),
                    });
                    continue;
                }
            };

            let name_text = name.syntax().text().to_string();
            match &*name_text {
                "domain" | "potential" | "flow" => {
                    if let Some(tok) = attr.eq_token() {
                        errors.push(SyntaxError::SurplusToken {
                            found: T![=],
                            span: tok.text_range(),
                        })
                    }
                }
                _ if attr.eq_token().is_none() => {
                    if let Some(val) = attr.val() {
                        errors.push(SyntaxError::MissingToken {
                            expected: T![=],
                            span: val.syntax().text_range(),
                            expected_at: TextRange::at(name.syntax().text_range().end(), 0.into()),
                        })
                    }
                }
                _ => (),
            }

            if let Some(val) = attr.val() {
                match &*name_text {
                    "potential" | "flow" => {
                        if !is_overwrite && nature_range.is_none() {
                            nature_range = Some(attr.syntax().text_range());
                        }
                        check_nature_ref_attr(&val, errors)
                    }
                    "idt_nature" | "ddt_nature" if is_overwrite => {
                        check_nature_ref_attr(&val, errors)
                    }

                    "domain" => {
                        let src = val.syntax().text();
                        if src == "discrete" {
                            discrete_range = Some(attr.syntax().text_range());
                        }
                        if src != "continuous" && src != "discrete" {
                            errors.push(SyntaxError::IllegalAttriubte {
                                attr: "domain",
                                expected: "continuous or discrete",
                                range: val.syntax().text_range(),
                            })
                        }
                    }

                    _ => (),
                }
            }
        }
    }

    if let (Some(domain_range), Some(nature_range)) = (discrete_range, nature_range) {
        errors.push(SyntaxError::DiscreteDomainWithNatures { domain_range, nature_range });
    }
}
