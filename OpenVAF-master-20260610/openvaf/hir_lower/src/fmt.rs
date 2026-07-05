use hir::{ExprId, Literal, Type};
use mir::{Value, GRAVESTONE};

use crate::body::BodyLoweringCtx;
use crate::callbacks::{CallBackKind, PrintDst};

#[derive(Debug, Clone, Hash, Eq, PartialEq, Copy)]
pub enum DisplayKind {
    Debug,
    Display,
    Info,
    Warn,
    Error,
    Fatal,
    Monitor,
}

#[derive(Debug, Clone, Hash, Eq, PartialEq)]
pub enum FmtArgKind {
    Binary,
    EngineerReal,
    Other,
}

impl From<Type> for FmtArg {
    fn from(ty: Type) -> FmtArg {
        FmtArg { ty, kind: FmtArgKind::Other }
    }
}

#[derive(Debug, Clone, Hash, Eq, PartialEq)]
pub struct FmtArg {
    pub ty: Type,
    pub kind: FmtArgKind,
}

impl BodyLoweringCtx<'_, '_, '_> {
    /// Lowers a `$display`-family call. `dst` selects the sink:
    /// - `Console`: prints to the simulator log (`fd` must be `None`).
    /// - `File`: `$fdisplay`/`$fwrite`/... -- `fd` (`Some`) is passed as the
    ///   second call argument (right after the format string).
    /// - `String`: `$swrite`/`$sformat` -- the callback returns the freshly
    ///   formatted string, which is returned here as `Some(value)` for the
    ///   caller to store into the destination string variable.
    ///
    /// Returns the formatted string only for `PrintDst::String`.
    pub fn ins_display(
        &mut self,
        kind: DisplayKind,
        newline: bool,
        args: &[ExprId],
        dst: PrintDst,
        fd: Option<Value>,
    ) -> Option<Value> {
        let mut fmt_lit = String::new();
        // call_args[0] is the format string (filled in at the end). For file
        // variants call_args[1] is the descriptor; the formatted values follow.
        let mut call_args = vec![GRAVESTONE];
        if let Some(fd) = fd {
            call_args.push(fd);
        }
        let mut arg_tys = Vec::new();

        let mut i = 0;

        while let Some(&expr) = args.get(i) {
            i += 1;
            // For $fatal skip the first argument
            if i == 1 && kind == DisplayKind::Fatal {
                continue;
            }
            if let Some(Literal::String(ref lit)) = self.body.as_literal(expr) {
                fmt_lit.reserve(lit.len());
                let mut chars = lit.chars();
                while let Some(mut c) = chars.next() {
                    if c == '%' {
                        c = chars.next().unwrap();
                        // escape / no-argument specifiers
                        match c {
                            '%' => {
                                fmt_lit.push_str("%%");
                                continue;
                            }
                            'm' | 'M' => {
                                fmt_lit.push_str(self.path);
                                continue;
                            }
                            'l' | 'L' => {
                                // TODO support properly
                                fmt_lit.push_str("__.__");
                                continue;
                            }
                            _ => {}
                        }
                        // Enhancement-71: a general `[flags][width][.prec]`
                        // prefix is legal for EVERY conversion (inference
                        // validated it); collect it verbatim, consuming one
                        // extra integer argument per dynamic `*`, then
                        // translate the conversion character to its C
                        // equivalent with the prefix preserved.
                        let mut prefix = String::new();
                        while matches!(c, '-' | '+' | ' ' | '#' | '0'..='9' | '.' | '*') {
                            if c == '*' {
                                arg_tys.push(Type::Integer.into());
                                call_args.push(self.lower_expr(args[i]));
                                i += 1;
                            }
                            prefix.push(c);
                            c = chars.next().unwrap()
                        }
                        fmt_lit.push('%');
                        fmt_lit.push_str(&prefix);
                        let ty = match c {
                            'h' => {
                                fmt_lit.push('x');
                                Type::Integer.into()
                            }
                            'H' => {
                                fmt_lit.push('X');
                                Type::Integer.into()
                            }
                            'b' | 'B' => {
                                // rendered via a pre-formatted binary string
                                fmt_lit.push('s');
                                FmtArg { ty: Type::Integer, kind: FmtArgKind::Binary }
                            }
                            'd' | 'D' => {
                                fmt_lit.push('d');
                                Type::Integer.into()
                            }
                            'o' | 'O' => {
                                fmt_lit.push('o');
                                Type::Integer.into()
                            }
                            'c' | 'C' => {
                                fmt_lit.push('c');
                                Type::Integer.into()
                            }
                            's' | 'S' => {
                                fmt_lit.push('s');
                                Type::String.into()
                            }
                            'r' | 'R' => {
                                fmt_lit.push_str("f%c");
                                FmtArg { ty: Type::Real, kind: FmtArgKind::EngineerReal }
                            }
                            _ => {
                                // e/E/f/F/g/G (validated by inference)
                                fmt_lit.push(c);
                                FmtArg { ty: Type::Real, kind: FmtArgKind::Other }
                            }
                        };

                        arg_tys.push(ty);
                        call_args.push(self.lower_expr(args[i]));
                        i += 1;
                    } else {
                        fmt_lit.push(c)
                    }
                }
            } else {
                let ty = self.resolved_ty(expr);
                let has_whitespace = fmt_lit.chars().last().map_or(false, |c| c.is_whitespace());
                if !has_whitespace {
                    fmt_lit.push(' ')
                }
                match ty {
                    Type::Real => fmt_lit.push_str("%g"),
                    Type::Integer => fmt_lit.push_str("%d"),
                    Type::String => fmt_lit.push_str("%s"),
                    Type::Void => {
                        fmt_lit.push(' ');
                        continue;
                    }
                    _ => unreachable!(),
                }

                arg_tys.push(ty.into());
                call_args.push(self.lower_expr(expr));
            }
        }
        if newline {
            fmt_lit.push('\n');
        }

        call_args[0] = self.ctx.sconst(&fmt_lit);
        let cb = CallBackKind::Print { kind, arg_tys: arg_tys.into_boxed_slice(), dst };
        if dst == PrintDst::String {
            // The callback returns the formatted string.
            Some(self.ctx.call1(cb, &call_args))
        } else {
            self.ctx.call(cb, &call_args);
            None
        }
    }

    /// Enhancement-34: lowers a *string* `{...}` concatenation / `{n{...}}` replication
    /// to a runtime string value, reusing the `$swrite`/`$sformat` machinery: the
    /// operands are passed as `%s` arguments to a `PrintDst::String` print callback
    /// (which returns the freshly formatted string). Every operand is a *value* — it is
    /// never interpreted as a format string, so `%` characters in the data are safe.
    pub fn lower_string_concat(&mut self, rep: Option<ExprId>, elems: &[ExprId]) -> Value {
        let rep_cnt = rep
            .and_then(|r| match self.body.as_literal(r) {
                Some(Literal::Int(n)) => Some(*n as usize),
                _ => None,
            })
            .unwrap_or(1);

        let unit: Vec<Value> = elems.iter().map(|&e| self.lower_expr(e)).collect();
        let n = unit.len() * rep_cnt;

        let mut call_args = Vec::with_capacity(n + 1);
        call_args.push(self.ctx.sconst(&"%s".repeat(n)));
        for _ in 0..rep_cnt {
            call_args.extend(unit.iter().copied());
        }
        let arg_tys = vec![FmtArg { ty: Type::String, kind: FmtArgKind::Other }; n];

        let cb = CallBackKind::Print {
            kind: DisplayKind::Display,
            arg_tys: arg_tys.into_boxed_slice(),
            dst: PrintDst::String,
        };
        self.ctx.call1(cb, &call_args)
    }
}
