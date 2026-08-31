use std::iter::once;

use stdx::iter::zip;
use syntax::sourcemap::FileSpan;
use syntax::SyntaxKind::BLOCK_STMT;
use syntax::{AstNode, SyntaxError, TextRange, TextSize};

use crate::diagnostics::{
    text_range_list_to_unified_spans, text_ranges_to_unified_spans, Diagnostic, Label, LabelStyle,
    Report,
};
use crate::lints::builtin::vams_keyword_compat;
use crate::lints::{Lint, LintSrc};
use crate::{BaseDB, FileId};

fn syntax_err_report(missing_delimiter: bool) -> Report {
    if missing_delimiter {
        Report::error().with_notes(vec!["you might be missing a 'begin' delimiter".to_owned()])
    } else {
        Report::error()
    }
}

impl Diagnostic for SyntaxError {
    fn lint(&self, root_file: FileId, db: &dyn BaseDB) -> Option<(Lint, LintSrc)> {
        match self {
            SyntaxError::ReservedIdentifier { compat: true, src, .. } => Some((
                vams_keyword_compat,
                LintSrc {
                    overwrite: None,
                    ast: db.ast_id_map(root_file).nearest_ast_id_to_ptr(*src, db, root_file),
                },
            )),
            _ => None,
        }
    }
    fn build_report(&self, root_file: FileId, db: &dyn BaseDB) -> Report {
        let sm = db.sourcemap(root_file);
        let parse = db.parse(root_file);

        let report = match *self {
            SyntaxError::UnexpectedToken {
                ref expected,
                span,
                expected_at: Some(expected_at),
                missing_delimiter,
                panic_end: None,
                ..
            } => {
                let (file_id, [expected_at, range]) =
                    text_ranges_to_unified_spans(&sm, &parse, [expected_at, span]);
                syntax_err_report(missing_delimiter).with_labels(vec![
                    Label {
                        style: LabelStyle::Secondary,
                        file_id,
                        range: expected_at.into(),
                        message: format!("expected {}", expected),
                    },
                    Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "unexpected token".to_owned(),
                    },
                ])
            }
            SyntaxError::UnexpectedToken {
                ref expected,
                span,
                missing_delimiter,
                panic_end: Some(panic_end),
                ..
            } => {
                let message = if expected.data.len() < 4 {
                    format!("expected {}", expected)
                } else {
                    "unexpected_token".to_owned()
                };

                let (file_id, [range, skipped]) = text_ranges_to_unified_spans(
                    &sm,
                    &parse,
                    [span, TextRange::new(span.start(), panic_end)],
                );
                syntax_err_report(missing_delimiter).with_labels(vec![
                    Label { style: LabelStyle::Primary, file_id, range: range.into(), message },
                    Label {
                        style: LabelStyle::Secondary,
                        file_id,
                        range: usize::from(range.end())..usize::from(skipped.end()),
                        message: "skipping to next valid declaration".to_owned(),
                    },
                ])
            }

            SyntaxError::UnexpectedToken { ref expected, span, missing_delimiter, .. } => {
                let message = if expected.data.len() < 4 {
                    format!("expected {}", expected)
                } else {
                    "unexpected_token".to_owned()
                };
                let FileSpan { file: file_id, range } = parse.to_file_span(span, &sm);

                syntax_err_report(missing_delimiter).with_labels(vec![Label {
                    style: LabelStyle::Primary,
                    file_id,
                    range: range.into(),
                    message,
                }])
            }

            SyntaxError::SurplusToken { found, span } => {
                let FileSpan { file: file_id, range } = parse.to_file_span(span, &sm);

                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: format!("unexpected {}", found),
                    }])
                    .with_notes(vec![format!(
                        "the {} token is not required here; simply remove it",
                        found
                    )])
            }
            SyntaxError::MissingToken { expected, span, expected_at } => {
                let (file_id, [expected_at, range]) =
                    text_ranges_to_unified_spans(&sm, &parse, [expected_at, span]);
                Report::error().with_labels(vec![
                    Label {
                        style: LabelStyle::Secondary,
                        file_id,
                        range: expected_at.into(),
                        message: format!("{} might be missing here", expected),
                    },
                    Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "unexpected token".to_owned(),
                    },
                ])
            }

            SyntaxError::IllegalRootSegment { path_segment, prefix: None } => {
                let FileSpan { file: file_id, range } = parse.to_file_span(path_segment, &sm);
                let end = TextRange::at(range.end() - TextSize::from(1), 1.into());

                Report::error().with_labels(vec![
                    Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "'$root' must be a prefix".to_owned(),
                    },
                    Label {
                        style: LabelStyle::Secondary,
                        file_id,
                        range: end.into(),
                        message: ".<identifier> might be missing here".to_owned(),
                    },
                ])
            }

            SyntaxError::IllegalRootSegment { path_segment, prefix: Some(prefix) } => {
                let (file_id, [prefix, path_segment]) =
                    text_ranges_to_unified_spans(&sm, &parse, [prefix, path_segment]);

                let prefix = TextRange::at(prefix.start() - TextSize::from(1), 1.into());

                Report::error().with_labels(vec![
                    Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: path_segment.into(),
                        message: "$root must be a prefix".to_owned(),
                    },
                    Label {
                        style: LabelStyle::Secondary,
                        file_id,
                        range: prefix.into(),
                        message: "perhaps you meant to place '$root' here".to_owned(),
                    },
                ])
            }
            SyntaxError::BlockItemsAfterStmt { ref items, first_stmt } => {
                let ranges: Vec<_> =
                    once(first_stmt).chain(items.iter().map(|item| item.range())).collect();

                let (file_id, ranges) = text_range_list_to_unified_spans(&sm, &parse, &ranges);

                let first_stmt = ranges[0];
                let item_ranges = &ranges[1..];

                let mut labels: Vec<_> = zip(item_ranges, items)
                    .map(|(range, ast_ptr)| Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: (*range).into(),
                        message: format!(
                            "{}s are only allowed before the first stmt",
                            ast_ptr.syntax_kind()
                        ),
                    })
                    .collect();

                labels.push(Label {
                    style: LabelStyle::Secondary,
                    file_id,
                    range: first_stmt.into(),
                    message: "help: move all declarations before this statement".to_owned(),
                });

                Report::error().with_labels(labels)
            }
            SyntaxError::BlockItemsWithoutScope { ref items, begin_token } => {
                let ranges: Vec<_> =
                    once(begin_token).chain(items.iter().map(|item| item.range())).collect();

                let (file_id, ranges) = text_range_list_to_unified_spans(&sm, &parse, &ranges);

                let begin_token = TextRange::at(ranges[0].end() - TextSize::from(1), 1.into());
                let item_ranges = &ranges[1..];

                let mut labels: Vec<_> = zip(item_ranges, items)
                    .map(|(range, ast_ptr)| Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: (*range).into(),
                        message: format!("{}s require a scope", ast_ptr.syntax_kind()),
                    })
                    .collect();

                labels.push(Label {
                    style: LabelStyle::Secondary,
                    file_id,
                    range: begin_token.into(),
                    message: "help: add ':<scope>' here".to_owned(),
                });

                Report::error().with_labels(labels)
            }
            SyntaxError::FunItemsAfterBody { ref items, body } => {
                let ranges: Vec<_> =
                    once(body).chain(items.iter().map(|item| item.range())).collect();

                let (file_id, ranges) = text_range_list_to_unified_spans(&sm, &parse, &ranges);

                let body = ranges[0];
                let item_ranges = &ranges[1..];

                let mut labels: Vec<_> = zip(item_ranges, items)
                    .map(|(range, ast_ptr)| Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: (*range).into(),
                        message: format!(
                            "{}s are not allowed after the function body",
                            ast_ptr.syntax_kind()
                        ),
                    })
                    .collect();

                labels.push(Label {
                    style: LabelStyle::Secondary,
                    file_id,
                    range: body.into(),
                    message: "help: move all declarations before this statement".to_owned(),
                });

                Report::error().with_labels(labels)
            }
            SyntaxError::MultipleFunBodys { ref additional_bodys, ref body } => {
                let (range, message) = if body.syntax_kind() == BLOCK_STMT {
                    (body.range(), "help: add these statements to this block".to_owned())
                } else {
                    (
                        body.range().cover(*additional_bodys.last().unwrap()),
                        "help: surround with begin ... end to create a single function body"
                            .to_owned(),
                    )
                };

                let ranges: Vec<_> = once(range).chain(additional_bodys.iter().copied()).collect();

                let (file_id, ranges) = text_range_list_to_unified_spans(&sm, &parse, &ranges);

                let range = ranges[0];
                let item_ranges = &ranges[1..];

                let mut labels: Vec<_> = item_ranges
                    .iter()
                    .map(|range| Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: (*range).into(),
                        message: "only one body per function is allowed".to_owned(),
                    })
                    .collect();

                labels.push(Label {
                    style: LabelStyle::Secondary,
                    file_id,
                    range: range.into(),
                    message,
                });

                Report::error().with_labels(labels)
            }

            SyntaxError::FunWithoutBody { fun } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(fun, &sm);
                Report::error().with_labels(vec![Label {
                    style: LabelStyle::Primary,
                    file_id,
                    range: range.into(),
                    message: "function body is missing".to_owned(),
                }])
            }

            SyntaxError::IllegalBranchNodeCnt { arg_list, .. } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(arg_list, &sm);
                Report::error().with_labels(vec![Label {
                    style: LabelStyle::Primary,
                    file_id,
                    range: range.into(),
                    message: "expected 1 or 2 nets".to_owned(),
                }])
            }

            SyntaxError::IllegalBranchNodeExpr { single, ref illegal_nodes } => {
                let (file_id, illegal_nodes) =
                    text_range_list_to_unified_spans(&sm, &parse, illegal_nodes);

                let labels = illegal_nodes
                    .into_iter()
                    .map(|range| Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "unexpected expression".to_owned(),
                    })
                    .collect();

                let hint = if single {
                    "help: expected an identifier or a port flow expression (<port>)"
                } else {
                    "help: expected an identifier"
                };

                Report::error().with_labels(labels).with_notes(vec![hint.to_owned()])
            }
            // Enhancement-387: the expression-depth guard, reported as itself.
            SyntaxError::RealLiteralOverflow { span, negative } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(span, &sm);
                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: format!(
                            "this is {}infinity as a double, not a number",
                            if negative { "negative " } else { "" }
                        ),
                    }])
                    .with_notes(vec![
                        "a double holds magnitudes up to about 1.8e308; a larger literal \
                         becomes an infinity and every value computed from it follows"
                            .to_owned(),
                        "help: only the LITERAL is checked -- an expression that overflows \
                         at run time, such as `1e308*10.0`, is the model's own business"
                            .to_owned(),
                    ])
            }
            SyntaxError::ZeroWidthLiteral { span } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(span, &sm);
                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "size must be greater than zero".to_owned(),
                    }])
                    .with_notes(vec![
                        "IEEE 1364-2005 3.5.1: the size of a based literal shall be a \
                         non-zero unsigned decimal number"
                            .to_owned(),
                        "the size was being clamped to one bit, so the value bore no \
                         relation to the digits written -- `0'd5` evaluated to 1"
                            .to_owned(),
                    ])
            }
            SyntaxError::InvalidBasedLiteral { span } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(span, &sm);
                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "not a valid based literal".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: the digits must be legal for the base (LRM 2.6.1), e.g. \
                         only 0/1/_ after 'b"
                            .to_owned(),
                    ])
            }
            SyntaxError::MalformedRealLiteral { span } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(span, &sm);
                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "missing digit next to the decimal point".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: LRM 2.6.2: write `1.0` rather than `1.`, `0.5` rather than `.5`"
                            .to_owned(),
                    ])
            }
            SyntaxError::MultilineStringLiteral { span } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(span, &sm);
                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "string spans more than one line".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: LRM 2.7: a string shall be contained on a single line; use \\n \
                         for a line break, or end the line with a backslash to continue it"
                            .to_owned(),
                    ])
            }
            SyntaxError::CommaExpr { span } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(span, &sm);
                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "expected ')' -- Verilog-A has no comma expression"
                            .to_owned(),
                    }])
                    .with_notes(vec![
                        "only the FIRST element was ever used; everything after the comma \
                         was discarded before it could be checked, so an undeclared name \
                         or a wrong argument count hiding in one was never reported"
                            .to_owned(),
                        "help: if a sum was intended, write '+' -- a comma where an \
                         operator was meant silently drops the rest of the expression"
                            .to_owned(),
                    ])
            }
            SyntaxError::ExprTooDeep { span } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(span, &sm);
                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "expression nests too deeply".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: openvaf limits expression nesting (and operator-chain \
                         length) to 1000 to avoid overflowing the parser; split the \
                         expression across intermediate variables"
                            .to_owned(),
                    ])
            }
            SyntaxError::IllegalInfToken { range } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(range, &sm);
                Report::error().with_labels(vec![Label {
                    style: LabelStyle::Primary,
                    file_id,
                    range: range.into(),
                    message: "unexpected token".to_owned(),
                }]).with_notes(vec!["help: 'inf' is only allowed in ranges of parameter declarations (example: [0:inf])".to_owned()])
            }
            SyntaxError::UnitsExpectedStringLiteral { range } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(range, &sm);
                Report::error().with_labels(vec![Label {
                    style: LabelStyle::Primary,
                    file_id,
                    range: range.into(),
                    message: "expected string literal".to_owned(),
                }])
            }
            SyntaxError::IllegalDisciplineAttrIdent { range } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(range, &sm);
                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "illegal attribute path".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: expected one of the following".to_owned(),
                        "an identifier: abstol".to_owned(),
                        "an identifier precceded by potential or flow: potential.abstol".to_owned(),
                    ])
            }
            SyntaxError::IllegalNatureIdent { range } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(range, &sm);
                Report::error()
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "illegal nature identifier".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: expected one of the following".to_owned(),
                        "an identifier: voltage".to_owned(),
                        "an identifier followed by potential or flow: electrical.potential"
                            .to_owned(),
                    ])
            }
            SyntaxError::DiscreteDomainWithNatures { domain_range, nature_range } => {
                let domain = parse.to_file_span(domain_range, &sm);
                let nature = parse.to_file_span(nature_range, &sm);
                Report::error()
                    .with_labels(vec![
                        Label {
                            style: LabelStyle::Primary,
                            file_id: domain.file,
                            range: domain.range.into(),
                            message: "the domain is bound discrete here".to_owned(),
                        },
                        Label {
                            style: LabelStyle::Secondary,
                            file_id: nature.file,
                            range: nature.range.into(),
                            message: "... but a nature is bound here".to_owned(),
                        },
                    ])
                    .with_notes(vec![
                        "help: per LRM 3.6.2.2 nature bindings imply the continuous domain; \
                         drop the natures (for a digital discipline) or bind `domain continuous`"
                            .to_owned(),
                    ])
            }
            SyntaxError::IllegalAttriubte { expected, range, .. } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(range, &sm);
                Report::error().with_labels(vec![Label {
                    style: LabelStyle::Primary,
                    file_id,
                    range: range.into(),
                    message: format!("expected {}", expected),
                }])
            }
            SyntaxError::ReservedIdentifier { src, compat, ref name } => {
                let FileSpan { file, range } = parse.to_file_span(src.range(), &sm);

                let report = Report::error().with_labels(vec![Label {
                    style: LabelStyle::Primary,
                    file_id: file,
                    range: range.into(),
                    message: format!("'{}' is a keyword", name),
                }]);

                // TODO error code (doc)

                if compat {
                    report.with_notes(vec![
                        format!(
                        "'{}' will likely never be used in the implemented language subset so this use is allowed",
                        name
                        ),
                        "to maintain compatibility with the VAMS standard this should be renamed".to_owned()
                    ])
                } else {
                    report
                }
            }
            SyntaxError::DuplicatePort { ref pos, ref name } => {
                let spans: Vec<_> =
                    pos.iter().map(|range| parse.to_file_span(*range, &sm)).collect();
                let initial = spans[0];
                let spans = &spans[1..];

                let mut labels: Vec<_> = spans
                    .iter()
                    .map(|range| Label {
                        style: LabelStyle::Primary,
                        file_id: range.file,
                        range: range.range.into(),
                        message: "..redeclared here".to_owned(),
                    })
                    .collect();

                labels.push(Label {
                    style: LabelStyle::Secondary,
                    file_id: initial.file,
                    range: initial.range.into(),
                    message: format!("{} first declared here", name),
                });

                Report::error().with_labels(labels)
            }
            SyntaxError::MixedModuleHead { ref module_ports } => {
                let ports = module_ports.to_node(parse.tree().syntax());

                let name_cnt = ports.names().count();
                let name_ranges: Vec<_> = ports
                    .names()
                    .map(|name| name.syntax().text_range())
                    .chain(ports.declarations().map(|port| port.syntax().text_range()))
                    .collect();

                let (file_id, ranges) = text_range_list_to_unified_spans(&sm, &parse, &name_ranges);
                let names = &ranges[..name_cnt];
                let ports = &ranges[name_cnt..];

                let labels: Vec<_> = names
                    .iter()
                    .map(|range| Label {
                        style: LabelStyle::Secondary,
                        file_id,
                        range: (*range).into(),
                        message: "found reference here".to_owned(),
                    })
                    .chain(ports.iter().map(|range| Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: (*range).into(),
                        message: "port declaration not allowed".to_owned(),
                    }))
                    .collect();

                Report::error().with_labels(labels).with_notes(vec![
                    "either declare all ports directly in the header: module example(inout foo, inout bar);".to_owned(),
                    "or only reference ports in the header: module example(foo,bar);".to_owned(),
                ])
            }
            SyntaxError::IllegalBodyPorts { head, ref body_ports } => {
                let body_ports: Vec<_> =
                    body_ports.iter().map(|range| parse.to_file_span(*range, &sm)).collect();
                let head = parse.to_file_span(head, &sm);

                let mut labels: Vec<_> = body_ports
                    .iter()
                    .map(|span| Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "illegal port declaration".to_owned(),
                    })
                    .collect();

                labels.push(Label {
                    style: LabelStyle::Secondary,
                    file_id: head.file,
                    range: head.range.into(),
                    message: "info: ports already declared in header...".to_owned(),
                });

                Report::error().with_labels(labels).with_notes(vec![
                    "help: either place all port declaration in the header".to_owned(),
                    "or place all port declarations in the body ".to_owned(),
                ])
            }
            SyntaxError::IllegalNetType { range, .. } => {
                let FileSpan { range, file: file_id } = parse.to_file_span(range, &sm);
                Report::error().with_labels(vec![Label {
                    style: LabelStyle::Primary,
                    file_id,
                    range: range.into(),
                    message: "unsupported net type".to_owned(),
                }])
            }
            SyntaxError::MultipleCaseDefaults { first, extra } => {
                let (file_id, [extra, first]) =
                    text_ranges_to_unified_spans(&sm, &parse, [extra, first]);
                Report::error()
                    .with_labels(vec![
                        Label {
                            style: LabelStyle::Primary,
                            file_id,
                            range: extra.into(),
                            message: "second `default` arm".to_owned(),
                        },
                        Label {
                            style: LabelStyle::Secondary,
                            file_id,
                            range: first.into(),
                            message: "help: the first `default` is here".to_owned(),
                        },
                    ])
                    .with_notes(vec![
                        "IEEE 1364-2005 9.5: at most one `default` arm per case \
                         statement"
                            .to_owned(),
                        "the FIRST `default` is the one that runs, so the later arm is \
                         unreachable"
                            .to_owned(),
                    ])
            }
            SyntaxError::RangeConstraintForNonNumericParameter { range, ty, .. } => {
                let (file_id, [range, ty]) = text_ranges_to_unified_spans(&sm, &parse, [range, ty]);
                Report::error().with_labels(vec![
                    Label {
                        style: LabelStyle::Primary,
                        file_id,
                        range: range.into(),
                        message: "illegal range bounds".to_owned(),
                    },
                    Label {
                        style: LabelStyle::Secondary,
                        file_id,
                        range: ty.into(),
                        message: "help: expected real or integer".to_owned(),
                    },
                ])
            }
            SyntaxError::PortNotDeclaredInModule { head, pos, ref name } => {
                let pos = parse.to_file_span(pos, &sm);
                let head = parse.to_file_span(head, &sm);

                let labels: Vec<_> = vec![
                    Label {
                        style: LabelStyle::Secondary,
                        file_id: head.file,
                        range: head.range.into(),
                        message: format!("help: add {name} here"),
                    },
                    Label {
                        style: LabelStyle::Primary,
                        file_id: pos.file,
                        range: pos.range.into(),
                        message: "port not declared in module head".to_owned(),
                    },
                ];

                Report::error().with_labels(labels)
            }
        };

        report.with_message(self.to_string())
    }
}
