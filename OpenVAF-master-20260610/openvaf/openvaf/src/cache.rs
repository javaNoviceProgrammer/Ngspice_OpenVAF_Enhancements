use core::slice;
use std::mem::{size_of, size_of_val};

use basedb::lints::LintLevel;
use basedb::{BaseDB, VfsStorage};
use hir::CompilationDB;

use crate::{LLVMCodeGenOptLevel, Opts};

/// Enhancement-453: the batch-mode cache key must cover every input that changes
/// the machine code, not just the source.
///
/// The key was the source text plus the defines, lints and compiler version. The
/// *codegen* settings were absent, so the cache answered a request that differed
/// only in those settings with whatever artifact happened to be there already:
///
///   * `-O`: `openvaf-r m.va -b -O 0` then `openvaf-r m.va -b -O 3` produced ONE
///     cache entry. The second run reported success and handed back the `-O 0`
///     build -- 113424 bytes where a real `-O 3` build is 36936. Debug once,
///     and every later optimized build is silently the debug one.
///
///   * `--target`: a cross-target request was answered with the HOST artifact.
///     `--target x86_64-unknown-linux` on an arm64 mac exited 0 with a Mach-O
///     arm64 `.osdi` in hand -- a Linux build that is not a Linux build.
///
/// `--target-cpu` and `-C` are the same class of input (both change the emitted
/// code: `--target-cpu native` and `--target-cpu generic` produce different
/// binaries here), so they are hashed too.
fn hash(db: &CompilationDB, opts: &Opts) -> md5::Digest {
    let defines = &opts.defines;
    let mut hash_builder = md5::Context::new();
    let cu = db.compilation_unit();

    // hash settings
    hash_builder.consume(cu.root_file().0.to_ne_bytes());

    hash_builder.consume(defines.len().to_ne_bytes());
    for def in defines {
        hash_builder.consume(def)
    }

    // Enhancement-453: the codegen settings. Lengths are hashed alongside the
    // strings so that neighbouring fields cannot run together and alias.
    hash_builder.consume([match opts.opt_lvl {
        LLVMCodeGenOptLevel::LLVMCodeGenLevelNone => 0u8,
        LLVMCodeGenOptLevel::LLVMCodeGenLevelLess => 1,
        LLVMCodeGenOptLevel::LLVMCodeGenLevelDefault => 2,
        LLVMCodeGenOptLevel::LLVMCodeGenLevelAggressive => 3,
    }]);

    let triple: &str = &opts.target.llvm_target;
    hash_builder.consume(triple.len().to_ne_bytes());
    hash_builder.consume(triple);

    hash_builder.consume(opts.target_cpu.len().to_ne_bytes());
    hash_builder.consume(&opts.target_cpu);

    hash_builder.consume(opts.codegen_opts.len().to_ne_bytes());
    for opt in &opts.codegen_opts {
        hash_builder.consume(opt.len().to_ne_bytes());
        hash_builder.consume(opt)
    }

    hash_builder.consume(env!("CARGO_PKG_VERSION"));
    let lints = db.global_lint_overwrites(cu.root_file());
    if cfg!(debug_assertions) && !lints.is_empty() {
        assert_eq!(size_of::<Option<LintLevel>>(), size_of_val(&lints.raw[0]));
    }
    let lints = unsafe {
        slice::from_raw_parts(
            lints.as_ptr() as *const u8,
            size_of::<Option<LintLevel>>() * lints.len(),
        )
    };
    hash_builder.consume(lints);

    // Hash the full preprocessor result
    let preprocess = cu.preprocess(db);
    let vfs = db.vfs().read();
    for token in &*preprocess.ts {
        if !token.kind.is_trivia() {
            let filespan = token.span.to_file_span(&preprocess.sm);
            let src = vfs.file_contents_unchecked(filespan.file);
            hash_builder.consume(&src[filespan.range]);
            hash_builder.consume(" ");
        }
    }

    hash_builder.compute()
}

pub fn file_name(db: &CompilationDB, opts: &Opts) -> String {
    let hash = u128::from_ne_bytes(*hash(db, opts));
    let hash = base_n::encode(hash, base_n::CASE_INSENSITIVE);
    format!("{}.osdi", hash)
}
