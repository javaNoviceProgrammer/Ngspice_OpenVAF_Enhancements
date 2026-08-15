use std::io::Write;
use std::process::exit;

use anyhow::{bail, Context, Result};
use camino::Utf8PathBuf;
use clap::ArgMatches;
use openvaf::{
    builtin_lints, get_target_names, host_triple, AbsPathBuf, LLVMCodeGenOptLevel, LintLevel,
};
use termcolor::{Color, ColorChoice, ColorSpec, WriteColor};

use crate::cli_def::{
    ALLOW, BATCHMODE, CACHE_DIR, CODEGEN, DEFINE, DENY, DRYRUN, DUMPIR, DUMPMIR, DUMPUNOPTIR,
    DUMPUNOPTMIR, INCLUDE, INPUT, LINTS, OPT_LVL, OUTPUT, SUPPORTED_TARGETS, TARGET, TARGET_CPU,
    WARN,
};
use crate::{CompilationDestination, Opts};


/// Enhancement-452: reject an unusable `-o` destination up front.
///
/// Three ways a destination went wrong, all of them reaching the backend and
/// failing there rather than being reported here:
///
///   * `-o` naming the INPUT file. The compiled module was written straight over
///     the source and the run reported success -- `openvaf-r m.va -o m.va`
///     exited 0 with "Finished building" while turning a 111-byte Verilog-A file
///     into a 36 KB shared object. The source is simply gone. Reachable from a
///     shell loop whose output variable is the input one.
///
///   * an EMPTY `-o`. `dst.file_stem()` in osdi::compile is an `.expect()`, so
///     it panicked: exit 101, a crash banner, a crash-log file and a request to
///     open a GitHub issue -- for a typo.
///
///   * an UNWRITABLE directory. `emit_object` returns an error, and the caller
///     wraps it in `assert_eq!(.., Ok(()))`, so a permission problem panicked the
///     same way.
///
/// An ordinary user error should cost one line, not a crash report. The checks
/// live here because this is the last point that still knows both the input and
/// the requested output, and it runs before any parsing.
fn validate_output(lib_file: &Utf8PathBuf, input: &Utf8PathBuf) -> Result<()> {
    if lib_file.as_str().is_empty() || lib_file.file_name().is_none() {
        bail!(
            "the output path '{lib_file}' does not name a file\n\
             help: give -o a file name, for example -o model.osdi"
        );
    }

    // Writing the module over its own source destroys it. Compare resolved paths
    // where both exist, so `./m.va` and `m.va` are recognised as the same file.
    let same = match (input.canonicalize(), lib_file.canonicalize()) {
        (Ok(a), Ok(b)) => a == b,
        _ => input == lib_file,
    };
    if same {
        bail!(
            "the output path '{lib_file}' is the input file\n\
             help: the compiled module would be written over the source and the \
             source would be lost; choose a different -o"
        );
    }

    let dir = match lib_file.parent() {
        Some(p) if !p.as_str().is_empty() => p.to_owned(),
        _ => Utf8PathBuf::from("."),
    };
    if !dir.is_dir() {
        bail!(
            "the output directory '{dir}' does not exist\n\
             help: create it, or give -o a path inside an existing directory"
        );
    }

    // The backend writes the module AND one object file per module beside it, so
    // prove the directory is writable rather than discovering it at link time.
    let probe = dir.join(format!(".openvaf-write-probe-{}", std::process::id()));
    match std::fs::File::create(&probe) {
        Ok(_) => {
            let _ = std::fs::remove_file(&probe);
        }
        Err(err) => {
            bail!(
                "cannot write to the output directory '{dir}': {err}\n\
                 help: choose a directory you can write to with -o"
            );
        }
    }

    Ok(())
}

pub fn matches_to_opts(matches: ArgMatches) -> Result<Opts> {
    if matches.get_flag(LINTS) {
        print_lints();
        exit(0)
    }
    if matches.get_flag(SUPPORTED_TARGETS) {
        print_targets();
        exit(0)
    }

    let input: Utf8PathBuf = matches.get_one::<Utf8PathBuf>(INPUT).unwrap().clone();

    let mut lints = Vec::new();

    if let Some(allow) = matches.get_many::<String>(ALLOW) {
        lints.extend(allow.map(|lint| (lint.to_owned(), LintLevel::Allow)));
    }

    if let Some(warn) = matches.get_many::<String>(WARN) {
        lints.extend(warn.map(|lint| (lint.to_owned(), LintLevel::Warn)));
    }
    if let Some(deny) = matches.get_many::<String>(DENY) {
        lints.extend(deny.map(|lint| (lint.to_owned(), LintLevel::Deny)));
    }

    let output = if matches.get_flag(BATCHMODE) {
        let cache_dir = if let Some(val) = matches.get_one::<Utf8PathBuf>(CACHE_DIR) {
            val.clone()
        } else {
            let path = directories_next::ProjectDirs::from("com", "semimod", "openvaf")
                .context(
                    "failed to find cache directory\nhelp: use --cache-dir to specify it manually",
                )?
                .cache_dir()
                .to_owned();
            if let Ok(res) = Utf8PathBuf::from_path_buf(path) {
                res
            } else {
                bail!(
                    "failed to find cache directory\nhelp: use --cache-dir to specify it manually",
                )
            }
        };
        CompilationDestination::Cache { cache_dir }
    } else {
        let lib_file = if let Some(output) = matches.get_one::<Utf8PathBuf>(OUTPUT) {
            output.clone()
        } else {
            input.with_extension("osdi")
        };

        // Enhancement-452: check the destination BEFORE any compilation work.
        validate_output(&lib_file, &input)?;

        CompilationDestination::Path { lib_file }
    };

    let codegen_opts = matches
        .get_many::<String>(CODEGEN)
        .map_or_else(Vec::new, |values| values.cloned().collect());

    // Enhancement-460: `-D =1` names no macro. It was accepted and then silently
    // dropped, so the build behaved as though the define had never been passed and the
    // model failed later with "macro `FOO` has not been declared" -- pointing at the
    // source rather than at the command line that was wrong.
    let defines: Vec<String> = matches
        .get_many::<String>(DEFINE)
        .map_or_else(Vec::new, |values| values.cloned().collect());
    for def in &defines {
        let name = def.split_once('=').map_or(def.as_str(), |(name, _)| name);
        if name.trim().is_empty() {
            bail!("invalid value '{def}' for '-D <MACRO[=VALUE]>': the macro name is empty");
        }
    }

    let include: Result<_> = matches.get_many::<Utf8PathBuf>(INCLUDE).map_or_else(
        || Ok(Vec::new()),
        |include| include.map(|path| Ok(AbsPathBuf::assert(path.canonicalize()?))).collect(),
    );

    let include = include?;

    let opt_lvl = match &**matches.get_one::<String>(OPT_LVL).unwrap() {
        "0" => LLVMCodeGenOptLevel::LLVMCodeGenLevelNone,
        "1" => LLVMCodeGenOptLevel::LLVMCodeGenLevelLess,
        "2" => LLVMCodeGenOptLevel::LLVMCodeGenLevelDefault,
        "3" => LLVMCodeGenOptLevel::LLVMCodeGenLevelAggressive,
        lvl => bail!("unknown opt lvl {lvl}"),
    };

    let host = host_triple();
    let target = matches.get_one::<String>(TARGET).cloned().unwrap_or_else(|| host.to_owned());
    let default_cpu = if host != target { "generic" } else { "native" };

    let target = if let Some(target) = openvaf::Target::search(&target) {
        target
    } else {
        // should never happened but helpful to provide support just in case
        bail!("The target {target} is not supported by  this binary")
    };

    let target_cpu: String =
        matches.get_one(TARGET_CPU).cloned().unwrap_or_else(|| default_cpu.to_owned());

    Ok(Opts {
        input,
        lints,
        codegen_opts,
        defines,
        include,
        output,
        opt_lvl,
        target,
        target_cpu,
        dump_mir: matches.get_flag(DUMPMIR),
        dump_unopt_mir: matches.get_flag(DUMPUNOPTMIR),
        dump_ir: matches.get_flag(DUMPIR),
        dump_unopt_ir: matches.get_flag(DUMPUNOPTIR),
        dry_run: matches.get_flag(DRYRUN),
    })
}

fn print_lints() {
    let mut stdout = termcolor::StandardStream::stdout(ColorChoice::Auto);

    stdout.set_color(ColorSpec::new().set_fg(Some(Color::Red))).unwrap();
    writeln!(&mut stdout, "ERRORS:").unwrap();
    stdout.set_color(&ColorSpec::new()).unwrap();
    for lint in builtin_lints::ALL {
        if lint.default_lvl == LintLevel::Deny {
            writeln!(&mut stdout, "    {}", lint.name).unwrap();
        }
    }

    stdout.set_color(ColorSpec::new().set_fg(Some(Color::Yellow))).unwrap();
    writeln!(&mut stdout, "WARNINGS:").unwrap();
    stdout.set_color(&ColorSpec::new()).unwrap();

    for lint in builtin_lints::ALL {
        if lint.default_lvl == LintLevel::Warn {
            writeln!(&mut stdout, "    {}", lint.name).unwrap();
        }
    }

    stdout.set_color(ColorSpec::new().set_fg(Some(Color::Green))).unwrap();
    writeln!(&mut stdout, "ALLOWED:").unwrap();
    stdout.set_color(&ColorSpec::new()).unwrap();

    for lint in builtin_lints::ALL {
        if lint.default_lvl == LintLevel::Allow {
            writeln!(&mut stdout, "    {}", lint.name).unwrap();
        }
    }
}

fn print_targets() {
    let mut stdout = termcolor::StandardStream::stdout(ColorChoice::Auto);

    stdout.set_color(ColorSpec::new().set_fg(Some(Color::Yellow))).unwrap();
    writeln!(&mut stdout, "TARGETS:").unwrap();
    stdout.set_color(&ColorSpec::new()).unwrap();

    for target in get_target_names() {
        writeln!(&mut stdout, "    {}", target).unwrap();
    }
}
