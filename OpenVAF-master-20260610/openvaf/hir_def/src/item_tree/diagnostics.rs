use basedb::diagnostics::{Diagnostic, Label, LabelStyle, Report};
use basedb::{AstIdMap, BaseDB, FileId};
use syntax::sourcemap::SourceMap;
use syntax::{Parse, SourceFile};

use super::ItemTreeDiagnostic;

pub struct ItemTreeDiagnosticWrapped<'a> {
    pub diag: &'a ItemTreeDiagnostic,
    pub parse: &'a Parse<SourceFile>,
    pub sm: &'a SourceMap,
    pub ast_id_map: &'a AstIdMap,
}

impl Diagnostic for ItemTreeDiagnosticWrapped<'_> {
    fn build_report(&self, _root_file: FileId, _db: &dyn BaseDB) -> Report {
        match self.diag {
            ItemTreeDiagnostic::NonConstantBusWidth { ast_id } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message("bus width `[msb:lsb]` is not a constant expression")
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "expected a constant integer expression on both sides of ':'"
                            .to_owned(),
                    }])
                    .with_notes(vec![
                        "help: only integer literals (optionally unary-negated) are supported \
                         here; the declaration was treated as a single scalar net/port"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::ArrayTooLarge { ast_id, size } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!(
                        "array declaration expands to {size} elements, exceeding the limit"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "array is too large to materialize".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: each element is expanded into its own scalar; use a smaller \
                         range (the declaration was treated as a single scalar)"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::BareBusReferenceInBranch { ast_id, bus_name } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!(
                        "bus '{bus_name}' requires a bit-select [i]"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: format!(
                            "'{bus_name}' is a vectored net; a single bit must be selected"
                        ),
                    }])
                    .with_notes(vec![format!(
                        "help: use '{bus_name}[i]' to select a single bit of the bus"
                    )])
            }
            ItemTreeDiagnostic::NonConstantBranchBitSelect { ast_id } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message("bit-select index is not a constant expression")
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "expected a constant integer literal index".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: only integer literals (optionally unary-negated) are supported \
                         as bit-select indices"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::BranchBitSelectOutOfRange { ast_id, bus_name, index, msb, lsb } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!(
                        "bit-select index {index} is out of range for bus '{bus_name}[{msb}:{lsb}]'"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: format!(
                            "'{bus_name}' was declared with range [{msb}:{lsb}]"
                        ),
                    }])
                    .with_notes(vec![format!(
                        "help: valid bit-select indices for '{bus_name}' are between {} and {}",
                        msb.min(lsb),
                        msb.max(lsb)
                    )])
            }
            ItemTreeDiagnostic::NonConstantInstanceArrayWidth { ast_id } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message("instance-array range `[msb:lsb]` is not a constant expression")
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "expected a constant integer expression on both sides of ':'"
                            .to_owned(),
                    }])
                    .with_notes(vec![
                        "help: only integer literals (optionally unary-negated) are supported \
                         here; the instantiation was treated as a single (non-arrayed) instance"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::ParamsetUnknownParam { ast_id, name, target } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!(
                        "paramset assigns '{name}', which module '{target}' does not declare"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "no such parameter in the target module".to_owned(),
                    }])
                    .with_notes(vec![
                        "the assignment would be dropped in silence; the same value written \
                         on a model card is reported"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::ParamsetDuplicateOverride { ast_id, name } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!("paramset assigns '{name}' more than once"))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "assigned again here".to_owned(),
                    }])
                    .with_notes(vec![
                        "the FIRST assignment is the one that takes effect".to_owned(),
                    ])
            }
            ItemTreeDiagnostic::ParamRangeEmpty { ast_id, name, constraint, why } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!(
                        "parameter '{name}' declares the range {constraint}, which no \
                         value can satisfy"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: format!("empty range: {why}"),
                    }])
                    .with_notes(vec![
                        "the parameter keeps its default, but every value supplied from a \
                         netlist is rejected at run time"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::ParamExcludeEmpty { ast_id, name, constraint, why } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!(
                        "parameter '{name}' declares {constraint}, which excludes nothing"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: format!("empty exclusion: {why}"),
                    }])
                    .with_notes(vec![
                        "no value is kept out, so every value the declaration appears to \
                         forbid is accepted"
                            .to_owned(),
                        "the same bounds written as a `from` range are rejected; this \
                         spelling was not"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::ParamExcludeCoversRange { ast_id, name, from, excluded } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!(
                        "parameter '{name}' excludes every value its range allows"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: format!("{from} is covered by {excluded}"),
                    }])
                    .with_notes(vec![
                        "the parameter keeps its default, but every value supplied from a \
                         netlist is rejected at run time"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::AliasParamCycle { ast_id, name, chain } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!(
                        "aliasparam '{name}' never reaches a parameter: its target \
                         chain closes on itself"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: format!("cycle: {chain}"),
                    }])
                    .with_notes(vec![
                        "an aliasparam must name a parameter (or a system parameter), \
                         directly or through other aliases"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::ParamsetOverrideOutOfRange {
                ast_id, name, value, constraint,
            } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                // `from` and `exclude` need different English: "its declared range
                // exclude 5 forbids" is not a sentence.
                let (msg, label) = match constraint.strip_prefix("exclude ") {
                    Some(v) => (
                        format!(
                            "paramset assigns '{name}' the value {value}, which its \
                             declaration excludes"
                        ),
                        format!("excluded by `exclude {v}`"),
                    ),
                    None => (
                        format!(
                            "paramset assigns '{name}' the value {value}, which its declared \
                             range {constraint} forbids"
                        ),
                        format!("outside {constraint}"),
                    ),
                };
                Report::error()
                    .with_message(msg)
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: label,
                    }])
                    .with_notes(vec![
                        "every other way of supplying this value is range-checked -- a model \
                         card, an instance line, alter/altermod, a .param, or a subcircuit \
                         parameter"
                            .to_owned(),
                        "checked when the override is written as a constant; an expression \
                         built from the paramset's own parameters is not folded here"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::PortRangeMismatch {
                ast_id, name, dir_msb, dir_lsb, net_msb, net_lsb,
            } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!(
                        "port '{name}' is declared [{dir_msb}:{dir_lsb}] as a port but \
                         [{net_msb}:{net_lsb}] as a net"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: format!("declared [{net_msb}:{net_lsb}] here"),
                    }])
                    .with_notes(vec![
                        "the two declarations of a bus port must state the same range".to_owned(),
                        "help: the port range used to win silently, so the net's extra bits \
                         were discarded and the module had fewer terminals than it declared"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::ArrayInitializerLengthMismatch { ast_id, name, expected, found } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!(
                        "array initializer for '{name}' has {found} element{} but the array \
                         has {expected}",
                        if *found == 1 { "" } else { "s" }
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: format!("expected {expected} leaf elements, found {found}"),
                    }])
                    .with_notes(vec![
                        "help: the `'{...}` literal must supply exactly one value per array \
                         element (row-major for multi-dimensional arrays)"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::UnelaboratedGenerate { ast_id } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message("`generate`/`genvar` construct could not be elaborated")
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "loop bounds must constant-fold to integers at compile time"
                            .to_owned(),
                    }])
                    .with_notes(vec![
                        "help: `generate for` requires a genvar loop of the form \
                         `for (i = <const>; i <op> <const>; i = i +/- <const>)`, with only \
                         structural items (nets, instances, vars, params) in its body"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::ArrayVarUnsupportedScope { ast_id } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(
                        "array-variable declarations are only supported at module body scope",
                    )
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "`[msb:lsb]` width clause not supported here".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: declare the array directly in the module body (not inside an \
                         analog function or a nested begin..end block); the declaration was \
                         treated as a single scalar variable"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::NonConstantNodeset { ast_id } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message("net nodeset initializer is not a constant")
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "expected a numeric literal (optionally negated)".to_owned(),
                    }])
                    .with_notes(vec![
                        "help: a net initializer (`electrical a = 5.0;`) is used as a nodeset \
                         value for the net's potential and must be a numeric constant here"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::InvalidParamsetSysParam { ast_id, name } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!(
                        "'{name}' is not a hierarchical system parameter"
                    ))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: "only hierarchical system parameters can be set by a paramset"
                            .to_owned(),
                    }])
                    .with_notes(vec![
                        "help: a paramset can bind target-module parameters (`.r = 2k;`) and the \
                         hierarchical system parameters $mfactor, $xposition, $yposition, \
                         $angle, $hflip and $vflip"
                            .to_owned(),
                    ])
            }
            ItemTreeDiagnostic::UnknownParamsetTarget { ast_id, target } => {
                let range = self.ast_id_map.get_syntax(*ast_id).range();
                let span = self.parse.to_file_span(range, self.sm);
                Report::error()
                    .with_message(format!("unknown paramset target module '{target}'"))
                    .with_labels(vec![Label {
                        style: LabelStyle::Primary,
                        file_id: span.file,
                        range: span.range.into(),
                        message: format!("no module named '{target}' is declared in this file"),
                    }])
                    .with_notes(vec![
                        "help: a `paramset <name> <module>;` must name a module declared in the \
                         same file; the paramset was dropped"
                            .to_owned(),
                    ])
            }
        }
    }
}
