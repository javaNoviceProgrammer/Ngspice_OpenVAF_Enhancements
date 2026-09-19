use rowan::TextSize;
use stdx::{impl_display, pretty};
use text_size::TextRange;

use crate::{ast, AstPtr, SyntaxKind, SyntaxNodePtr};

#[derive(Eq, PartialEq, Debug, Clone, Hash)]
pub enum SyntaxError {
    UnexpectedToken {
        expected: pretty::List<Vec<SyntaxKind>>,
        found: SyntaxKind,
        span: TextRange,
        panic_end: Option<TextSize>,
        expected_at: Option<TextRange>,
        missing_delimiter: bool,
    },
    SurplusToken {
        found: SyntaxKind,
        span: TextRange,
    },
    /// Enhancement-387: expression nested deeper than `MAX_EXPR_DEPTH`
    /// (Enhancement-148's guard). Reported in its own right so the message
    /// describes the actual limit instead of a token that is not the problem.
    ExprTooDeep {
        span: TextRange,
    },
    /// Enhancement-423: a parenthesised comma list used as an expression.
    CommaExpr {
        span: TextRange,
    },
    /// Enhancement-665 (hunt F11): a bare identifier before `begin` (`forever`)
    IdentBeforeBlock {
        span: TextRange,
    },
    /// Enhancement-665 (hunt F11): `(* desc= *)`, an attribute without a value
    AttrWithoutValue {
        span: TextRange,
    },
    /// Enhancement-665 (hunt F11): a number immediately followed by letters the
    /// lexer could not take into it -- `1e3n`, `0.5e`, `1meg`
    NumberSuffix {
        span: TextRange,
        text: String,
    },
    /// Enhancement-589: a case statement without a single item
    EmptyCase {
        span: TextRange,
    },
    /// Enhancement-640: a statement at module scope, outside any `analog` block
    StmtOutsideAnalog {
        span: TextRange,
    },
    /// Enhancement-425: a real literal whose value does not fit in a double and
    /// silently became an infinity.
    RealLiteralOverflow {
        span: TextRange,
        negative: bool,
    },
    /// Enhancement-425: a based integer literal with a ZERO size. IEEE 1364-2005
    /// 3.5.1 requires a non-zero size; `parse_based_int_masked` clamped it to 1,
    /// so `0'd5` evaluated to 1.
    ZeroWidthLiteral {
        span: TextRange,
    },
    /// A (possibly white-space-separated, LRM 2.6.1) based integer literal
    /// whose digits are not valid for its base -- e.g. `'b 29`. Reported here
    /// because the multi-token form otherwise degrades to 0 silently.
    InvalidBasedLiteral {
        span: TextRange,
    },
    /// LRM 2.6.2: a real constant needs at least one digit on each side of the
    /// decimal point (`1.` and `.5` are the LRM's own illegal examples).
    MalformedRealLiteral {
        span: TextRange,
    },
    /// Enhancement-650 (hunt F6): `\ddd` in a string names one 8-bit character
    /// (IEEE 1364-2005 2.6.3, LRM 2.7.1), so an escape above `\377` has no
    /// character to name. `"\777"` used to print U+01FF.
    OctalEscapeTooLarge {
        span: TextRange,
    },
    /// Enhancement-650: an escape the LRM does not define (`\q`, `\x41`). The
    /// backslash is kept verbatim (Enhancement-48's contract); this says so.
    UnknownStringEscape {
        span: TextRange,
        src: SyntaxNodePtr,
        escape: String,
    },
    /// LRM 2.7: a string literal shall be contained on a single line.
    MultilineStringLiteral {
        span: TextRange,
    },
    MissingToken {
        expected: SyntaxKind,
        span: TextRange,
        expected_at: TextRange,
    },
    IllegalRootSegment {
        path_segment: TextRange,
        prefix: Option<TextRange>,
    },
    BlockItemsAfterStmt {
        items: Vec<AstPtr<ast::BlockItem>>,
        first_stmt: TextRange,
    },
    BlockItemsWithoutScope {
        items: Vec<AstPtr<ast::BlockItem>>,
        begin_token: TextRange,
    },
    FunItemsAfterBody {
        items: Vec<AstPtr<ast::FunctionItem>>,
        body: TextRange,
    },
    MultipleFunBodys {
        additional_bodys: Vec<TextRange>,
        body: AstPtr<ast::Stmt>,
    },
    FunWithoutBody {
        fun: TextRange,
    },
    IllegalBranchNodeCnt {
        arg_list: TextRange,
        cnt: usize,
    },
    IllegalBranchNodeExpr {
        single: bool,
        illegal_nodes: Vec<TextRange>,
    },
    IllegalInfToken {
        range: TextRange,
    },
    UnitsExpectedStringLiteral {
        range: TextRange,
    },
    IllegalDisciplineAttrIdent {
        range: TextRange,
    },

    IllegalNatureIdent {
        range: TextRange,
    },
    IllegalAttriubte {
        range: TextRange,
        attr: &'static str,
        expected: &'static str,
    },

    /// LRM 3.6.2.2: a discipline with nature bindings must not bind
    /// `domain discrete` (Enhancement-50).
    DiscreteDomainWithNatures {
        domain_range: TextRange,
        nature_range: TextRange,
    },

    ReservedIdentifier {
        src: SyntaxNodePtr,
        compat: bool,
        name: String,
    },

    DuplicatePort {
        pos: Vec<TextRange>,
        name: String,
    },

    PortNotDeclaredInModule {
        head: TextRange,
        pos: TextRange,
        name: String,
    },

    MixedModuleHead {
        module_ports: AstPtr<ast::ModulePorts>,
    },

    IllegalBodyPorts {
        head: TextRange,
        body_ports: Vec<TextRange>,
    },
    IllegalNetType {
        found: String,
        range: TextRange,
    },

    RangeConstraintForNonNumericParameter {
        param: String,
        range: TextRange,
        ty: TextRange,
    },
    /// Enhancement-421: IEEE 1364-2005 9.5 -- "use of multiple default
    /// statements in one case statement shall be illegal". Two `default` arms
    /// were accepted in silence; the first wins, so the extra one is dead code.
    MultipleCaseDefaults {
        first: TextRange,
        extra: TextRange,
    },
}

use SyntaxError::*;

impl_display! {
    match SyntaxError{
        UnexpectedToken {expected,found,..} => "unexpected token {}; expected {}", found, expected;
        SurplusToken {found,..} => "unexpected token {}", found;
        ExprTooDeep{..} => "expression nests too deeply";
        CommaExpr{..} => "a parenthesised list is not an expression";
        IdentBeforeBlock{..} => "a bare identifier before `begin`: not an analog statement";
        AttrWithoutValue{..} => "the attribute has no value after '='";
        NumberSuffix{text,..} => "malformed number literal `{}`", text;
        EmptyCase{..} => "case statement has no items; a case needs at least one `value: statement` or `default:` item";
        StmtOutsideAnalog{..} => "statement outside an analog block";
        RealLiteralOverflow{..} => "real literal is too large to represent";
        ZeroWidthLiteral{..} => "a sized literal must have a non-zero size";
        InvalidBasedLiteral{..} => "based literal has no valid digits for its base";
        MalformedRealLiteral{..} => "a real constant needs a digit on each side of the decimal point";
        OctalEscapeTooLarge{..} => "an octal escape in a string exceeds \\377";
        UnknownStringEscape{escape,..} => "unknown escape sequence '{}' in a string", escape;
        MultilineStringLiteral{..} => "a string literal must be contained on a single line";
        MissingToken{expected, ..} => "unexpected token; expected {}", expected;
        IllegalRootSegment { ..} =>  "$root is only allowed as a prefix";
        BlockItemsAfterStmt{..}  => "declarations in blocks are only allowed before the first stmt";
        BlockItemsWithoutScope { ..} => "declarations in blocks require an explicit scope";
        FunItemsAfterBody{..} => "functions may not contain any items after the function body";
        MultipleFunBodys{..} => "functions may only contain one body";
        FunWithoutBody {..} => "function is missing a body";
        IllegalBranchNodeCnt { cnt,..} => "branch declaration require 1 or 2 nets; found {}", cnt;
        IllegalBranchNodeExpr{..} => "illegal expr was used to declare a branch node!";
        IllegalInfToken{..} => "unexpected token 'inf'; expected an expression";
        UnitsExpectedStringLiteral{..} => "'units' attribute must be a string literal";
        IllegalDisciplineAttrIdent{..} => "illegal discipline attribute identifier!";
        IllegalNatureIdent{..} => "illegal nature identifier";
        IllegalAttriubte{attr,..} => "illegal value provided for {} attribute", attr;
        DiscreteDomainWithNatures{..} => "a discipline with nature bindings cannot have a discrete domain";
        ReservedIdentifier{name,..} => "reserved keyword '{}' was used as an identifier",name;
        DuplicatePort{name,..} => "port '{}' was declared multiple times!",name;
        MixedModuleHead{..} => "module header contains mix of port references and port declarations";
        IllegalBodyPorts{..} => "ports declared in module head and body";
        IllegalNetType{found,..} => "{} nets are currently not supported!",found;
        RangeConstraintForNonNumericParameter{param,..} => "non-numeric parameter '{}' has range bounds", param;
        PortNotDeclaredInModule{name,..} => "port '{name}' was not declared in the module head";
        MultipleCaseDefaults{..} => "a case statement has more than one `default` arm";
    }
}

impl SyntaxError {
    /// Enhancement-672: the range the error is reported at, when it has one.
    pub fn primary_range(&self) -> Option<TextRange> {
        match self {
            SyntaxError::UnexpectedToken { span, .. }
            | SyntaxError::SurplusToken { span, .. }
            | SyntaxError::ExprTooDeep { span, .. }
            | SyntaxError::CommaExpr { span, .. }
            | SyntaxError::IdentBeforeBlock { span, .. }
            | SyntaxError::AttrWithoutValue { span, .. }
            | SyntaxError::NumberSuffix { span, .. }
            | SyntaxError::EmptyCase { span, .. }
            | SyntaxError::StmtOutsideAnalog { span, .. }
            | SyntaxError::RealLiteralOverflow { span, .. }
            | SyntaxError::ZeroWidthLiteral { span, .. }
            | SyntaxError::InvalidBasedLiteral { span, .. }
            | SyntaxError::MalformedRealLiteral { span, .. }
            | SyntaxError::OctalEscapeTooLarge { span, .. }
            | SyntaxError::UnknownStringEscape { span, .. }
            | SyntaxError::MultilineStringLiteral { span, .. }
            | SyntaxError::MissingToken { span, .. } => Some(*span),
            _ => None,
        }
    }
}
