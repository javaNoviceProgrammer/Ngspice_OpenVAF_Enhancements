use std::fs::{read_dir, read_to_string, DirEntry};
use std::mem::swap;

use ahash::RandomState;
use indexmap::IndexMap;
use proc_macro2::{Ident, Span, TokenStream};
use quote::{format_ident, quote, ToTokens, TokenStreamExt};
use target::spec::get_targets;

use heck::ToUpperCamelCase;

use crate::{add_preamble, ensure_file_contents, project_root, reformat, to_lower_snake_case};

/// REPAIRED AND RE-ENABLED (Enhancement-389; quarantined by Enhancement-379).
///
/// Two things had put this generator behind the header it generates, and only one
/// of them was about the header having grown:
///
///   * `trim` skipped whitespace but not COMMENTS, so the first `/* ... */`
///     written inside a struct body left `parse_ty` looking at `/`, `eat_ident`
///     returned `None`, and the `unwrap()` panicked. Documenting a header field is
///     ordinary practice; the parser simply could not read it.
///   * comments were then DISCARDED, so regenerating deleted the documentation the
///     checked-in files carried -- which is why running it always looked
///     destructive. They are now carried onto the generated item as doc comments,
///     from the header, which is where a field's explanation belongs.
///
/// Running it also surfaced what the drift had hidden: `EVAL_RET_FLAG_DISCONT` was
/// in the header but missing from the generated Rust, and `OSDI_VERSION_MINOR_CURR`
/// read 4 in the header and 5 in the generated file while the compiler stamped 7
/// (`OSDI_VERSION` in `osdi/src/lib.rs`, which is the value ngspice gates on and
/// the only one that is live -- nothing reads the generated constant). The header
/// now says 7 too.
///
/// Enhancement-379's own fix is kept: `Header::new` skips any name that is not
/// `osdi_<major>_<minor>.h`, so an archived snapshot beside the live header no
/// longer kills the generator with a bare `ParseIntError`.
#[test]
fn gen_osdi_structs() {
    let header_dir = project_root().join("openvaf").join("osdi").join("header");
    let headers: Vec<_> = read_dir(header_dir)
        .unwrap()
        .filter_map(|entry| {
            let entry = entry.ok()?;
            Header::new(entry)
        })
        .collect();

    let osdi_src_dir = project_root().join("openvaf").join("osdi").join("src").join("metadata");
    let osdi_test_dir = project_root().join("openvaf").join("openvaf").join("tests").join("load");
    let melange_src_dir = project_root().join("melange").join("core").join("src").join("veriloga");

    for header in &headers {
        let res = HeaderParser { header, res: ParseResults::default(), off: 0 }.run();
        let tys = gen_llvm_tys(&res.tys);
        let consts = gen_defines(&res.defines);
        let file_header = "use mir_llvm::CodegenCx;\n";
        let version_str = format!("{}_{}", header.version_major, header.version_minor);
        let targets = get_targets().map(|target| target.llvm_target);
        let stdlibs = targets.clone().map(|target| format!("/stdlib_{version_str}_{target}.bc"));
        let stdlib_idents_: Vec<_> = targets
            .clone()
            .map(|target| {
                format_ident!("STDLIB_BITCODE_{}", target.to_uppercase().replace(['-', '.'], "_"))
            })
            .collect();
        let stdlib_idents = &stdlib_idents_;
        let targets = targets.clone();
        let stdlib = quote! {
            #(
                const #stdlib_idents: &[u8] = include_bytes!(concat!(env!("OUT_DIR"), #stdlibs));
            )*
            pub fn stdlib_bitcode(target: &target::spec::Target) -> &'static [u8]{
                match &*target.llvm_target {
                    #(#targets => #stdlib_idents,)*
                    triple => unreachable!("unknown target triple {triple}")
                }
            }
        };

        // osdi*.rs file for compiler (unions are enums), used for lowering
        let file_string = format!("{file_header}\n{stdlib}\n{consts}\n\n{tys}");
        let file_string = add_preamble("gen_osdi_structs", reformat(file_string));
        let file_name = format!("osdi_{}_{}.rs", header.version_major, header.version_minor);
        ensure_file_contents(&osdi_src_dir.join(file_name), &file_string);

        // osdi*.rs file for melange and tests (unions are c-style unions),
        // used for importing a dynamic library
        let bindings = gen_bindings(&res.tys);
        let file_header = "use std::os::raw::{c_char, c_void};";
        let file_string = format!("{file_header}\n\n{consts}\n\n{bindings}");
        let file_string = add_preamble("gen_osdi_structs", reformat(file_string));
        let file_name = format!("osdi_{}_{}.rs", header.version_major, header.version_minor);

        ensure_file_contents(&melange_src_dir.join(&file_name), &file_string);
        ensure_file_contents(&osdi_test_dir.join(&file_name), &file_string);
    }
}

struct Header {
    version_minor: u32,
    version_major: u32,
    src: String,
}

impl Header {
    fn new(entry: DirEntry) -> Option<Self> {
        if entry.file_type().map_or(true, |it| !it.is_file()) {
            return None;
        }
        let name = entry.file_name().to_str()?.to_owned();
        if &name[0..5] != "osdi_" {
            return None;
        }

        let name = &name[5..];
        // Enhancement-379: SKIP anything that is not `osdi_<major>_<minor>.h`
        // rather than unwrapping. Archived snapshots live in this directory
        // alongside the live header -- `osdi_0_4_enhancement1.h` strips to
        // "4_enhancement1", and the version parse panicked the whole generator
        // with a bare `ParseIntError { kind: InvalidDigit }`. `new` already
        // returns None for non-files and non-`osdi_` names; an unparseable
        // version belongs in the same category.
        let (version_major, name) = name.split_once('_')?;
        let version_minor = name.split_once(".h")?.0;

        let version_major = version_major.parse().ok()?;
        let version_minor = version_minor.parse().ok()?;

        let path = entry.path();
        let src = read_to_string(path).unwrap();
        Some(Header { version_minor, version_major, src })
    }
}

#[derive(Default)]
struct ParseResults<'a> {
    tys: IndexMap<&'a str, OsdiStruct<'a>, RandomState>,
    defines: Vec<(&'a str, &'a str, Option<Vec<String>>)>,
}

struct HeaderParser<'a> {
    header: &'a Header,
    off: usize,
    res: ParseResults<'a>,
}

impl<'a> HeaderParser<'a> {
    fn src(&self) -> &'a str {
        &self.header.src[self.off..]
    }

    /// Skip whitespace AND C comments.
    ///
    /// Enhancement-389: comments were not skipped, which is what put this generator
    /// behind the header it generates. A `/* ... */` between two struct fields left
    /// `parse_ty` looking at `/`, `eat_ident` returned `None` and the `unwrap()`
    /// panicked -- so the first explanatory comment added inside a struct body (the
    /// nodeset field, and later the `ac_stim` block) silently disqualified the whole
    /// generator. Commenting a header field is ordinary practice, so this was a gap
    /// in the parser, not a constraint the header should have honoured.
    fn trim(&mut self) {
        loop {
            let src = self.src();
            let (off, _) =
                src.char_indices().find(|(_, c)| !c.is_whitespace()).unwrap_or((src.len(), '\0'));
            self.off += off;
            let src = self.src();
            if src.starts_with("/*") {
                // an unterminated comment runs to EOF rather than panicking
                let end = src[2..].find("*/").map_or(src.len(), |i| i + 4);
                self.off += end;
            } else if src.starts_with("//") {
                let end = src.find('\n').unwrap_or(src.len());
                self.off += end;
            } else {
                return;
            }
        }
    }

    fn eat(&mut self, kw: &str) -> bool {
        self.trim();
        if &self.src()[..kw.len()] == kw {
            self.off += kw.len();
            true
        } else {
            false
        }
    }

    fn eat_ident(&mut self) -> Option<&'a str> {
        self.trim();
        let src = self.src();
        let off = src.find(|c| !is_ident_char(c)).unwrap_or(src.len());
        if off != 0 {
            self.off += off;
            Some(&src[..off])
        } else {
            None
        }
    }

    fn run(mut self) -> ParseResults<'a> {
        loop {
            let typedef_pos = self.src().find("typedef");
            let define_pos = self.src().find("#define");
            if let Some(pos) = typedef_pos {
                if define_pos.map_or(true, |define_pos| pos < define_pos) {
                    self.off += pos;
                    // Enhancement-389: capture the introducing comment BEFORE the
                    // keyword is consumed -- `preceding_doc` looks backward from the
                    // cursor, so once `typedef` is eaten the comment is no longer
                    // the last thing behind it.
                    let doc = self.preceding_doc();
                    assert!(self.eat("typedef"));
                    if self.eat("struct") {
                        self.parse_struct(false, doc);
                    } else if self.eat("union") {
                        self.parse_struct(true, doc);
                    }
                    continue;
                }
            }

            if let Some(pos) = define_pos {
                self.off += pos;
                let doc = self.preceding_doc();
                assert!(self.eat("#define"));
                self.parse_define(doc);
                continue;
            }

            if typedef_pos.is_none() {
                break;
            }
        }

        self.res
    }

    /// Enhancement-389: the comment block immediately before the current position,
    /// as doc-comment lines.
    ///
    /// The generated files carried hand-written documentation that regeneration
    /// deleted, because the parser dropped comments on the floor -- so the generator
    /// could only ever be run by accepting a documentation loss. The header already
    /// holds those same comments; carrying them through makes a regeneration
    /// faithful, and keeps the header the single place a field is explained.
    ///
    /// Only a block separated from here by whitespace alone counts, so a comment
    /// that follows an item on its own line documents the NEXT item.
    fn preceding_doc(&self) -> Option<Vec<String>> {
        let before = self.header.src[..self.off].trim_end();
        let raw: String = if before.ends_with("*/") {
            let start = before.rfind("/*")?;
            before[start + 2..before.len() - 2].to_owned()
        } else {
            let mut lines: Vec<&str> = Vec::new();
            for line in before.lines().rev() {
                match line.trim().strip_prefix("//") {
                    Some(rest) => lines.push(rest),
                    None => break,
                }
            }
            if lines.is_empty() {
                return None;
            }
            lines.reverse();
            lines.join("\n")
        };

        let doc: Vec<String> = raw
            .lines()
            .map(|l| l.trim().trim_start_matches('*').trim().to_owned())
            .skip_while(|l| l.is_empty())
            .collect();
        let end = doc.iter().rposition(|l| !l.is_empty())? + 1;
        Some(doc[..end].to_vec())
    }

    fn parse_define(&mut self, doc: Option<Vec<String>>) {
        let ident = self.eat_ident().unwrap();
        let end = self.src().find('\n').unwrap_or_else(|| self.src().len());
        let val = self.src()[..end].trim();
        self.res.defines.push((ident, val, doc));
    }

    fn parse_ty(&mut self) -> Ty<'a> {
        let base_ty = match self.eat_ident().unwrap() {
            "double" => BaseTy::F64,
            "int" | "int32_t" => BaseTy::I32,
            "uint32_t" => BaseTy::U32,
            "size_t" => BaseTy::Usize,
            "char" => BaseTy::Char,
            "void" => BaseTy::Void,
            "bool" => BaseTy::Bool,
            name => {
                let struct_data = self.res.tys.get(name).unwrap();
                if struct_data.is_union {
                    BaseTy::Union(name)
                } else {
                    BaseTy::Struct(name)
                }
            }
        };

        let mut indirection = 0;
        while self.eat("*") {
            indirection += 1;
        }
        Ty { indirection, base: base_ty, func_args: None }
    }

    fn parse_struct(&mut self, is_union: bool, doc: Option<Vec<String>>) {
        let ident = self.eat_ident().unwrap();
        assert!(self.eat("{"));

        let mut fields = Vec::new();
        let mut field_docs = Vec::new();
        loop {
            if self.eat("}") {
                break;
            }

            // Enhancement-389: `eat("}")` above has already run `trim`, so any comment
            // introducing this field is behind us and `preceding_doc` can see it.
            let doc = self.preceding_doc();
            let mut ty = self.parse_ty();

            let is_func_ptr = self.eat("(") && self.eat("*");
            let field_ident = self.eat_ident().unwrap();
            if is_func_ptr {
                assert!(self.eat(")"));
                assert!(self.eat("("));
                let mut args = Vec::new();
                while !self.eat(")") {
                    let ty = self.parse_ty();
                    let name = self.eat_ident().unwrap();
                    args.push((name, ty));
                    self.eat(",");
                }
                ty.func_args = Some(args);
            }

            self.eat(";");
            fields.push((field_ident, ty));
            field_docs.push(doc);
        }

        self.res.tys.insert(
            ident,
            OsdiStruct {
                ident,
                llvm_ty_ident: to_lower_snake_case(ident),
                fields,
                field_docs,
                doc,
                is_union,
            },
        );
    }
}

fn is_ident_char(c: char) -> bool {
    matches!(c, '_'| 'a'..='z' | 'A' ..='Z' | '0' ..='9')
}

#[derive(PartialEq, Eq, Clone, Copy, Debug)]
enum BaseTy<'a> {
    F64,
    I32,
    U32,
    Usize,
    Char,
    Bool,
    Void,
    Struct(&'a str),
    Union(&'a str),
}

impl ToTokens for BaseTy<'_> {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        let ident = match self {
            BaseTy::F64 => "f64",
            BaseTy::I32 => "i32",
            BaseTy::U32 => "u32",
            BaseTy::Usize => "usize",
            BaseTy::Bool => "bool",
            BaseTy::Char => {
                quote!(String).to_tokens(tokens);
                return;
            }
            BaseTy::Void => "c_void",
            BaseTy::Struct(name) => name,
            BaseTy::Union(name) => name,
        };

        tokens.append(Ident::new(ident, Span::call_site()));
    }
}

struct Ty<'a> {
    base: BaseTy<'a>,
    indirection: u32,
    func_args: Option<Vec<(&'a str, Ty<'a>)>>,
}

struct BaseTyInterpolater<'b, 'a> {
    indirection: u32,
    base: BaseTy<'a>,
    lut: &'b IndexMap<&'a str, OsdiStruct<'a>, RandomState>,
}

impl ToTokens for BaseTyInterpolater<'_, '_> {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        if self.indirection == 0 || self.indirection == 1 && self.base == BaseTy::Char {
            self.base.to_tokens(tokens);
            if let BaseTy::Struct(ty) = self.base {
                let ty = &self.lut[ty];
                let has_ll = ty.fields.iter().any(|(_, ty)| ty.func_args.is_some());
                if has_ll {
                    quote!(<'ll>).to_tokens(tokens)
                }
            }
        } else {
            let next = BaseTyInterpolater { indirection: self.indirection - 1, ..*self };
            quote!(Vec<#next>).to_tokens(tokens)
        }
    }
}

struct TyInterpolater<'b, 'a> {
    ty: &'b Ty<'a>,
    lut: &'b IndexMap<&'a str, OsdiStruct<'a>, RandomState>,
}
impl ToTokens for TyInterpolater<'_, '_> {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        if self.ty.func_args.is_some() || self.ty.base == BaseTy::Void {
            quote!(&'ll llvm_sys::LLVMValue).to_tokens(tokens);
            return;
        }

        // let mut indirection = self.ty.indirection;
        // if self.ty.base == BaseTy::Char {
        //     indirection -= 1;
        // }

        BaseTyInterpolater { indirection: self.ty.indirection, base: self.ty.base, lut: self.lut }
            .to_tokens(tokens);
    }
}

struct OsdiStruct<'a> {
    is_union: bool,
    ident: &'a str,
    llvm_ty_ident: String,
    fields: Vec<(&'a str, Ty<'a>)>,
    /// Enhancement-389: doc lines for `fields[i]`, taken from the header comment
    /// preceding that field. Parallel to `fields` so the many existing
    /// `(name, ty)` destructurings keep working.
    field_docs: Vec<Option<Vec<String>>>,
    /// Enhancement-389: the header comment introducing the `typedef` itself.
    doc: Option<Vec<String>>,
}

struct OsdiStructInterp<'a, 'b> {
    info: &'b OsdiStruct<'a>,
    lut: &'b IndexMap<&'a str, OsdiStruct<'a>, RandomState>,
}

struct LLVMTyInterp<'a, 'b> {
    ty: &'b Ty<'a>,
    lut: &'b IndexMap<&'a str, OsdiStruct<'a>, RandomState>,
}

impl ToTokens for LLVMTyInterp<'_, '_> {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        let indirection = self.ty.indirection;
        let ty = if indirection == 0 && self.ty.func_args.is_none() {
            match self.ty.base {
                BaseTy::F64 => quote!(ctx.ty_double()),
                BaseTy::I32 | BaseTy::U32 => quote!(ctx.ty_int()),
                BaseTy::Usize => quote!(ctx.ty_size()),
                BaseTy::Char => {
                    quote!(ctx.ty_char())
                }
                BaseTy::Bool => quote!(ctx.ty_c_bool()),
                BaseTy::Void => quote!(ctx.ty_void()),
                BaseTy::Struct(ty) => {
                    let ty = &self.lut[ty].llvm_ty_ident;
                    let ty = Ident::new(ty, Span::call_site());
                    quote!(self.#ty.unwrap())
                }
                BaseTy::Union(ty) => {
                    let ty = &self.lut[ty].llvm_ty_ident;
                    let ty = Ident::new(ty, Span::call_site());
                    quote!(self.#ty.unwrap())
                }
            }
        } else {
            quote!(ctx.ty_ptr())
        };

        ty.to_tokens(tokens)

        // if let Some(_args) = &self.ty.func_args {
        // let args = args.iter().map(|(_, ty)| LLVMTyInterp { ty, lut: self.lut });
        // quote!(ctx.ty_ptr()).to_tokens(tokens)
        // } else {
        //     ty.to_tokens(tokens)
        // }
    }
}

struct LLVMValInterp<'a, 'b> {
    ty: &'b Ty<'a>,
    name: &'a str,
    pos: u32,
    lut: &'b IndexMap<&'a str, OsdiStruct<'a>, RandomState>,
}

impl ToTokens for LLVMValInterp<'_, '_> {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        let ident = Ident::new(self.name, Span::call_site());
        let src = quote!(self.#ident);
        if self.ty.func_args.is_some() || self.ty.base == BaseTy::Void {
            src.to_tokens(tokens);
            return;
        }
        let mut indirection = self.ty.indirection;
        if self.ty.base == BaseTy::Char {
            indirection -= 1;
        }
        if indirection != 0 {
            let base_ty = if indirection == 1 {
                match self.ty.base {
                    BaseTy::F64 => quote!(ctx.ty_double()),
                    BaseTy::I32 | BaseTy::U32 => quote!(ctx.ty_int()),
                    BaseTy::Usize => quote!(ctx.ty_size()),
                    BaseTy::Char => {
                        quote!(ctx.ty_ptr())
                    }
                    BaseTy::Bool => quote!(ctx.ty_c_bool()),
                    BaseTy::Void => unreachable!(),
                    BaseTy::Struct(ty) => {
                        let ty = &self.lut[ty].llvm_ty_ident;
                        let ty = Ident::new(ty, Span::call_site());
                        quote!(tys.#ty)
                    }
                    BaseTy::Union(ty) => {
                        let ty = &self.lut[ty].llvm_ty_ident;
                        let ty = Ident::new(ty, Span::call_site());
                        quote!(tys.#ty)
                    }
                }
            } else {
                quote!(ctx.ty_ptr())
            };
            let pos = self.pos;
            let ident = format_ident!("arr_{pos}");
            quote!(ctx.const_arr_ptr(#base_ty, &#ident)).to_tokens(tokens);
            return;
        }

        let val = match self.ty.base {
            BaseTy::F64 => quote!(ctx.const_real(#src)),
            BaseTy::I32 => quote!(ctx.const_int(#src)),
            BaseTy::U32 => quote!(ctx.const_unsigned_int(#src)),
            BaseTy::Usize => quote!(ctx.const_usize(#src)),
            BaseTy::Char => {
                quote!(ctx.const_str_uninterned(&#src))
            }
            BaseTy::Bool => quote!(ctx.const_c_bool(#src)),
            BaseTy::Void => unreachable!(),
            BaseTy::Struct(_) => {
                quote!(#src.to_ll_val(ctx, tys))
            }
            BaseTy::Union(_) => {
                quote!(#src.to_ll_val(ctx, tys))
            }
        };

        val.to_tokens(tokens)
    }
}

struct LLVMValPreInterp<'a, 'b> {
    ty: &'b Ty<'a>,
    name: &'a str,
    pos: u32,
}

impl ToTokens for LLVMValPreInterp<'_, '_> {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        let ident = Ident::new(self.name, Span::call_site());
        let src = quote!(self.#ident);
        let mut indirection = self.ty.indirection;
        if self.ty.base == BaseTy::Char {
            indirection -= 1;
        }

        if indirection == 0 || self.ty.func_args.is_some() {
            return;
        };

        let calc_src = quote!(it);

        let val = match self.ty.base {
            BaseTy::F64 => quote!(ctx.const_real(*#calc_src)),
            BaseTy::I32 => quote!(ctx.const_int(*#calc_src)),
            BaseTy::U32 => quote!(ctx.const_unsigned_int(*#calc_src)),
            BaseTy::Usize => quote!(ctx.const_usize(*#calc_src)),
            BaseTy::Char => {
                quote!(ctx.const_str_uninterned(#calc_src))
            }
            BaseTy::Bool => quote!(ctx.const_c_bool(*#calc_src)),
            BaseTy::Void if indirection == 1 => {
                return;
            }
            BaseTy::Void => unreachable!(),
            BaseTy::Struct(_) => {
                quote!(#calc_src.to_ll_val(ctx, tys))
            }
            BaseTy::Union(_) => {
                quote!(#calc_src.to_ll_val(ctx, tys, self))
            }
        };

        assert!(indirection <= 1);
        let pos = self.pos;
        let ident = format_ident!("arr_{pos}");
        quote! {
            let #ident: Vec<_> = #src.iter().map(|it| #val).collect();
        }
        .to_tokens(tokens)
    }
}

impl ToTokens for OsdiStructInterp<'_, '_> {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        let llvm_ty_ident = Ident::new(&self.info.llvm_ty_ident, Span::call_site());
        let OsdiStruct { ident, fields, .. } = self.info;
        if !matches!(
            *ident,
            "OsdiInitError"
                | "OsdiSimParas"
                | "OsdiInitInfo"
                | "OsdiInitErrorPayload"
                | "OsdiSimInfo"
        ) {
            // assert!(!self.info.is_union, "union code generation is not implemented (yet)");
            {
                let ident = Ident::new(ident, Span::call_site());
                let field_names =
                    fields.iter().map(|(name, _)| Ident::new(name, Span::call_site()));
                // Enhancement-389: carry each field's header comment onto the
                // generated field, so regenerating no longer deletes documentation.
                let field_doc_attrs: Vec<TokenStream> =
                    self.info.field_docs.iter().map(doc_attrs).collect();
                let struct_doc_attrs = doc_attrs(&self.info.doc);
                let field_tys = fields.iter().map(|(_, ty)| TyInterpolater { ty, lut: self.lut });
                let field_ll_arrays = fields
                    .iter()
                    .enumerate()
                    .map(|(pos, (name, ty))| LLVMValPreInterp { ty, name, pos: pos as u32 });
                let field_ll_vals = fields.iter().enumerate().map(|(pos, (name, ty))| {
                    LLVMValInterp { ty, name, pos: pos as u32, lut: self.lut }
                });
                let has_ll =
                    fields.iter().any(|(_, ty)| ty.func_args.is_some() || ty.base == BaseTy::Void);

                let mut lt = quote!();
                let mut func_lt = quote!(<'ll>);
                if has_ll {
                    swap(&mut lt, &mut func_lt);
                }

                // Capitalize field names to be used in enum
                let mut v: Vec<String> = Vec::new();
                let capitalized_field_names = fields.iter().map(|(name, _)| {
                    v.push(name.to_upper_camel_case());
                    let s: &str = &v.last().unwrap();
                    Ident::new(s, Span::call_site())
                });

                if self.info.is_union {
                    quote! {
                        // In compiler unions are represented as enums
                        pub enum #ident #lt{
                            #( #capitalized_field_names ( #field_tys) ),*
                        }

                        // Will have to write fn to_ll_val() manually for each union type
                    }
                } else {
                    quote! {
                        #struct_doc_attrs
                        pub struct #ident #lt{
                            #(#field_doc_attrs pub #field_names: #field_tys),*
                        }

                        impl #lt #ident #lt{
                            pub fn to_ll_val #func_lt (&self, ctx: &CodegenCx<'_,'ll>, tys: &'ll OsdiTys) -> &'ll llvm_sys::LLVMValue{
                                #(#field_ll_arrays)*
                                let fields = [#(#field_ll_vals),*];
                                let ty = tys.#llvm_ty_ident;
                                ctx.const_struct(ty, &fields)
                            }
                        }
                    }
                }
                .to_tokens(tokens);
            }
        }

        let field_ll_tys =
            self.info.fields.iter().map(|(_, ty)| LLVMTyInterp { ty, lut: self.lut });
        let ident = self.info.ident;
        if self.info.is_union {
            let field_ll_tys2 = field_ll_tys.clone();
            // Use ty_aint() with element size=alignment*8 bits so that
            // llvm will correctly align the union and its parent.
            // The number of chunks of size align*8 bits is given by size.
            quote! {
                impl OsdiTyBuilder<'_, '_, '_>{
                    fn #llvm_ty_ident(&mut self){
                        let ctx = self.ctx;
                        unsafe{
                            let align = [#(llvm_sys::target::LLVMABIAlignmentOfType(self.target_data.clone(), core::ptr::NonNull::from(#field_ll_tys).as_ptr())),*].into_iter().max().unwrap();
                            let mut size = [#(llvm_sys::target::LLVMABISizeOfType(self.target_data.clone(), core::ptr::NonNull::from(#field_ll_tys2).as_ptr())),*].into_iter().max().unwrap() as u32;
                            size = (size + align - 1) / align;
                            let elem = ctx.ty_aint(align*8);
                            let ty = ctx.ty_array(elem, size);
                            self.#llvm_ty_ident = Some(ty);
                        }
                    }
                }
            }
            .to_tokens(tokens);
        } else {
            quote! {
                impl OsdiTyBuilder<'_, '_, '_>{
                    fn #llvm_ty_ident(&mut self){
                        let ctx = self.ctx;
                        let fields = [#(#field_ll_tys),*];
                        let ty = ctx.ty_struct(#ident, &fields);
                        self.#llvm_ty_ident = Some(ty);
                    }
                }
            }
            .to_tokens(tokens);
        }
    }
}

struct RustStruct<'a>(&'a OsdiStruct<'a>);
impl ToTokens for RustStruct<'_> {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        let OsdiStruct { is_union, ident, ref fields, ref field_docs, ref doc, .. } = *self.0;
        let private =
            if matches!(ident, "OsdiDescriptor") { quote!(#[non_exhaustive]) } else { quote!() };
        let ident = format_ident!("{ident}");
        let kind = if is_union { quote!(union) } else { quote!(struct) };
        let field_names = fields.iter().map(|(name, _)| format_ident!("{name}"));
        let field_tys = fields.iter().map(|(_, ty)| RustTy(ty));
        let field_doc_attrs: Vec<TokenStream> = field_docs.iter().map(doc_attrs).collect();
        let struct_doc_attrs = doc_attrs(doc);
        quote! {
            #struct_doc_attrs
            #[repr(C)]
            #private
            pub #kind #ident {
                #(#field_doc_attrs pub #field_names: #field_tys,)*
            }
        }
        .to_tokens(tokens);

        let funcs: Vec<_> = fields
            .iter()
            .filter_map(|(name, ty)| {
                Some(RustFunc {
                    name,
                    ret_ty: RustReturnTy(RustBasicTy {
                        base: ty.base,
                        indirection: ty.indirection,
                    }),
                    args: ty.func_args.as_ref()?,
                })
            })
            .collect();
        if !funcs.is_empty() {
            quote! {
                impl #ident{
                    #(#funcs)*
                }
            }
            .to_tokens(tokens)
        }
    }
}

struct RustBasicTy<'a> {
    base: BaseTy<'a>,
    indirection: u32,
}

impl ToTokens for RustBasicTy<'_> {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        let RustBasicTy { base, indirection } = *self;
        let ident = match base {
            BaseTy::F64 => "f64",
            BaseTy::I32 => "i32",
            BaseTy::U32 => "u32",
            BaseTy::Usize => "usize",
            BaseTy::Bool => "bool",
            BaseTy::Char => "c_char",
            BaseTy::Void => "c_void",
            BaseTy::Struct(name) => name,
            BaseTy::Union(name) => name,
        };

        let base = Ident::new(ident, Span::call_site());
        let ptr = (0..indirection).map(|_| quote!(*mut));
        quote!(#(#ptr)* #base).to_tokens(tokens)
    }
}

struct RustReturnTy<'a>(RustBasicTy<'a>);

impl ToTokens for RustReturnTy<'_> {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        let ty = &self.0;
        if ty.indirection != 0 || ty.base != BaseTy::Void {
            quote!(-> #ty).to_tokens(tokens)
        }
    }
}
struct RustTy<'a>(&'a Ty<'a>);

impl ToTokens for RustTy<'_> {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        let Ty { base, indirection, ref func_args } = *self.0;
        let base = RustBasicTy { base, indirection };
        match func_args {
            Some(args) => {
                let base = RustReturnTy(base);
                let arg_tys = args.iter().map(|(_, ty)| RustTy(ty));
                quote!(fn(#(#arg_tys),*) #base).to_tokens(tokens)
            }
            None => base.to_tokens(tokens),
        }
    }
}

struct RustFunc<'a> {
    name: &'a str,
    ret_ty: RustReturnTy<'a>,
    args: &'a [(&'a str, Ty<'a>)],
}

impl ToTokens for RustFunc<'_> {
    fn to_tokens(&self, tokens: &mut TokenStream) {
        let RustFunc { name, ret_ty, args } = self;
        let name = format_ident!("{name}");
        let arg_names = args.iter().map(|(name, _)| format_ident!("{name}"));
        let arg_tys = args.iter().map(|(_, ty)| RustTy(ty));
        let arg_name_refs = args.iter().map(|(name, _)| format_ident!("{name}"));
        quote! {
            pub fn #name(&self, #(#arg_names: #arg_tys),*) #ret_ty{
                (self.#name)(#(#arg_name_refs),*)
            }
        }
        .to_tokens(tokens)
    }
}

fn gen_bindings<'a>(tys: &IndexMap<&'a str, OsdiStruct<'a>, RandomState>) -> String {
    let tys = tys.iter().map(|(_, ty)| RustStruct(ty));
    quote!(#(#tys)*).to_string()
}

fn gen_llvm_tys<'a>(tys: &IndexMap<&'a str, OsdiStruct<'a>, RandomState>) -> String {
    let fields = tys.values().map(|it| Ident::new(&it.llvm_ty_ident, Span::call_site()));
    let fields2 = fields.clone();
    let fields3 = fields.clone();
    let fields4 = fields.clone();
    let fields5 = fields.clone();
    let structs = tys.values().map(|it| OsdiStructInterp { info: it, lut: tys });
    quote!(
        #(#structs)*

        #[derive(Clone)]
        pub struct OsdiTys<'ll>{
            #(pub #fields : &'ll llvm_sys::LLVMType),*
        }

        impl<'ll> OsdiTys<'ll>{
            pub fn new(ctx: &CodegenCx<'_, 'll>, target_data: llvm_sys::target::LLVMTargetDataRef) -> Self{
                let mut builder = OsdiTyBuilder{
                    ctx,
                    target_data,
                    #(#fields4: None),*
                };
                #(builder.#fields5();)*
                builder.finish()
            }

        }


        struct OsdiTyBuilder<'a, 'b, 'll>{
            ctx: &'a CodegenCx<'b, 'll>,
            target_data:  llvm_sys::target::LLVMTargetDataRef,
            #(#fields2 : Option<&'ll llvm_sys::LLVMType>),*
        }

        impl<'ll> OsdiTyBuilder<'_, '_, 'll>{
            fn finish(self) -> OsdiTys<'ll>{
                OsdiTys{
                    #(#fields3: self.#fields3.unwrap()),*
                }
            }
        }
    )
    .to_string()
}

fn gen_defines(defines: &[(&str, &str, Option<Vec<String>>)]) -> String {
    defines
        .iter()
        .map(|(ident, val, doc)| {
            let doc = render_doc(doc.as_deref(), "");
            format!("{doc}pub const {ident}: u32 = {val};")
        })
        .collect()
}

/// Enhancement-389: a field's header comment as `#[doc]` attributes.
fn doc_attrs(doc: &Option<Vec<String>>) -> TokenStream {
    match doc {
        None => quote!(),
        Some(lines) => {
            let lines = lines.iter().map(|l| format!(" {l}"));
            quote!(#(#[doc = #lines])*)
        }
    }
}

/// Enhancement-389: header comment lines as Rust doc comments, at `indent`.
fn render_doc(doc: Option<&[String]>, indent: &str) -> String {
    match doc {
        None => String::new(),
        Some(lines) => lines
            .iter()
            .map(|l| {
                if l.is_empty() {
                    format!("{indent}///\n")
                } else {
                    format!("{indent}/// {l}\n")
                }
            })
            .collect(),
    }
}
