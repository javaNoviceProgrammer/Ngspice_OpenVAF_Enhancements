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
