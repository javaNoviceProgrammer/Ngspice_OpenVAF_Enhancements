//! Defines input for code generation process.

use crate::to_upper_snake_case;

pub(crate) struct KindsSrc<'a> {
    pub(crate) punct: &'a [(&'a str, &'a str)],
    pub(crate) keywords: &'a [&'a str],
    /// Words that get a `_KW` SyntaxKind variant but are NOT in
    /// `from_keyword`: the plain identifier stays an IDENT (it is a legal
    /// Verilog-AMS name) and the keyword token is only produced by dedicated
    /// lexer/parser paths (`$root` -> ROOT_KW).
    pub(crate) contextual_keywords: &'a [&'a str],
    pub(crate) literals: &'a [&'a str],
    pub(crate) tokens: &'a [&'a str],
    pub(crate) nodes: &'a [&'a str],
}

pub(crate) const KINDS_SRC: KindsSrc = KindsSrc {
    punct: &[
        (";", "SEMICOLON"),
        (",", "COMMA"),
        ("(", "L_PAREN"),
        (")", "R_PAREN"),
        ("{", "L_CURLY"),
        ("}", "R_CURLY"),
        ("[", "L_BRACK"),
        ("]", "R_BRACK"),
        ("<", "L_ANGLE"),
        (">", "R_ANGLE"),
        ("@", "AT"),
        ("#", "POUND"),
        ("~", "TILDE"),
        ("?", "QUESTION"),
        ("$", "DOLLAR"),
        ("&", "AMP"),
        ("|", "PIPE"),
        ("+", "PLUS"),
        ("*", "STAR"),
        ("/", "SLASH"),
        ("^", "CARET"),
        ("%", "PERCENT"),
        ("_", "UNDERSCORE"),
        (".", "DOT"),
        (":", "COLON"),
        ("=", "EQ"),
        // case (in)equality (LRM 4.2.6) -- three chars, listed before the
        // two-char forms the way <<< precedes <<
        ("===", "EQ3"),
        ("!==", "NEQ2"),
        ("==", "EQ2"),
        ("!", "BANG"),
        ("!=", "NEQ"),
        ("-", "MINUS"),
        ("<=", "LTEQ"),
        (">=", "GTEQ"),
        ("&&", "AMP2"),
        ("||", "PIPE2"),
        ("<<<", "ASHL"),
        (">>>", "ASHR"),
        ("<<", "SHL"),
        (">>", "SHR"),
        ("(*", "L_ATTR_PAREN"),
        ("*)", "R_ATTR_PAREN"),
        ("'{", "ARR_START"),
        ("<+", "CONTR"),
        ("**", "POW"),
        ("~^", "L_NXOR"),
        ("^~", "R_NXOR"),
    ],
    keywords: &[
        "analog",
        "begin",
        "branch",
        "case",
        "casex",
        "casez",
        "default",
        "disable",
        "discipline",
        "else",
        "end",
        "endcase",
        "enddiscipline",
        "endfunction",
        "endgenerate",
        "endmodule",
        "endnature",
        "exclude",
        "for",
        "from",
        "function",
        "generate",
        "genvar",
        "if",
        "inf",
        "inout",
        "input",
        "integer",
        "module",
        "nature",
        "output",
        "parameter",
        "localparam",
        "real",
        "string",
        "while",
        "repeat",
        "do",
        "initial_step",
        "initial",
        "final_step",
        "aliasparam",
        "paramset",
        "endparamset",
        "defparam",
        "or",
        // VAMS-2023 jump statements (LRM 5.11); demoted to IDENT outside
        // statement positions in syntax/src/parsing.rs so legacy identifier
        // uses keep compiling (with the L012 keyword-compat lint).
        "break",
        "continue",
        "return",
    ],
    // `root` is a legal identifier (LRM Annex B does not reserve it); ROOT_KW
    // is produced only for the `$root` spelling (tokens/src/lib.rs).
    contextual_keywords: &["root"],
    literals: &["INT_NUMBER", "BASED_INT", "BASE_PREFIX", "STD_REAL_NUMBER", "SI_REAL_NUMBER", "STR_LIT"],
    tokens: &["ERROR", "IDENT", "SYSFUN", "NET_TYPE", "WHITESPACE", "COMMENT"],
    nodes: &[
        "ANALOG_BEHAVIOUR",
        "ARG",
        "ARG_LIST",
        "ARRAY_EXPR",
        "CONCAT_EXPR",
        "REPLICATION_EXPR",
        "ASSIGN",
        "ASSIGN_STMT",
        "ASSIGN_OR_EXPR",
        "ATTR",
        "ATTR_LIST",
        "BIN_EXPR",
        "BIT_SELECT_EXPR",
        "BLOCK_SCOPE",
        "BLOCK_STMT",
        "BRANCH_DECL",
        "CALL",
        "CASE",
        "CASE_STMT",
        "CONSTRAINT",
        "DIRECTION",
        "DISCIPLINE_DECL",
        "DISCIPLINE_ATTR",
        "EVENT_STMT",
        "FOR_STMT",
        "FUNCTION",
        "FUNCTION_ARG",
        "IF_STMT",
        "INSTANTIATION",
        "PARAM_OVERRIDES",
        "PARAM_ASSIGN",
        "INSTANCE_UNIT",
        "PORT_CONNS",
        "PORT_CONN",
        "GENVAR_DECL",
        "GENERATE_FOR",
        "GENERATE_BLOCK",
        "GENERATE_IF",
        "GENERATE_CASE",
        "GENERATE_CASE_ARM",
        "LITERAL",
        "MODULE_DECL",
        "MODULE_PORT",
        "MODULE_PORTS",
        "NAME",
        "NAME_REF",
        "SYS_FUN",
        "BODY_PORT_DECL",
        "NATURE_DECL",
        "NATURE_ATTR",
        "NET_DECL",
        "NETS",
        "PARAM",
        "ALIAS_PARAM",
        "PARAM_DECL",
        "DEFPARAM",
        "PAREN_EXPR",
        "PATH",
        "PATH_EXPR",
        "PORT_DECL",
        "PORTS",
        "PREFIX_EXPR",
        "RANGE",
        "SELECT_EXPR",
        "TYPE",
        "VAR",
        "VAR_DECL",
        "WHILE_STMT",
        "REPEAT_STMT",
        "DO_WHILE_STMT",
        "DISABLE_STMT",
        "JUMP_STMT",
        "EMPTY_STMT",
        "EXPR_STMT",
        "PORT_FLOW",
        "PARAMSET_DECL",
        "PARAMSET_OVERRIDE",
        "SOURCE_FILE",
    ],
};

#[derive(Default, Debug)]
pub(crate) struct AstSrc {
    pub(crate) tokens: Vec<String>,
    pub(crate) nodes: Vec<AstNodeSrc>,
    pub(crate) enums: Vec<AstEnumSrc>,
}

#[derive(Debug)]
pub(crate) struct AstNodeSrc {
    pub(crate) doc: Vec<String>,
    pub(crate) name: String,
    pub(crate) traits: Vec<String>,
    pub(crate) fields: Vec<Field>,
}

#[derive(Debug, Eq, PartialEq)]
pub(crate) enum Field {
    Token(String),
    Node { name: String, ty: String, cardinality: Cardinality },
}

#[derive(Debug, Eq, PartialEq)]
pub(crate) enum Cardinality {
    Optional,
    Many,
}

#[derive(Debug)]
pub(crate) struct AstEnumSrc {
    pub(crate) doc: Vec<String>,
    pub(crate) name: String,
    pub(crate) traits: Vec<String>,
    pub(crate) variants: Vec<AstEnumVariant>,
    pub(crate) nested_variant: Option<String>,
}

#[derive(Debug)]
pub(crate) enum AstEnumVariant {
    Node(String),
    Token(String),
}

impl AstEnumVariant {
    pub(crate) fn syntax_kind(&self) -> String {
        match self {
            AstEnumVariant::Token(ref name) => format!("{}_KW", to_upper_snake_case(name)),
            AstEnumVariant::Node(ref name) => to_upper_snake_case(name),
        }
    }

    pub(crate) fn name(&self) -> &str {
        match self {
            AstEnumVariant::Node(ref name) | AstEnumVariant::Token(ref name) => name,
        }
    }
}
