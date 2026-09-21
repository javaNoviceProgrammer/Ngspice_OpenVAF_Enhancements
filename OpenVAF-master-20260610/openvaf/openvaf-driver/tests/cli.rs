use std::env;
use std::path::PathBuf;

use mini_harness::{harness, Result};
use stdx::{ignore_never, project_root};

// Adapted from
// https://github.com/rust-lang/cargo/blob/485670b3983b52289a2f353d589c57fae2f60f82/tests/testsuite/support/mod.rs#L507
pub fn target_dir() -> PathBuf {
    env::current_exe()
        .ok()
        .map(|mut path| {
            path.pop();
            if path.ends_with("deps") {
                path.pop();
            }
            path
        })
        .unwrap()
}

/// Returns the path of a binary build by cargo
pub fn cargo_bin(name: &str) -> PathBuf {
    let env_var = format!("CARGO_BIN_EXE_{}", name);
    std::env::var_os(env_var)
        .map(|p| p.into())
        .unwrap_or_else(|| target_dir().join(format!("{}{}", name, env::consts::EXE_SUFFIX)))
}

fn smoke_test(args: &str) -> Result {
    let args = args.split(' ');
    let sh = xshell::Shell::new().unwrap();
    sh.change_dir(project_root());
    let openvaf = cargo_bin("openvaf-r");
    xshell::cmd!(sh, "{openvaf} --dry-run {args...} integration_tests/DIODE/diode.va").run()?;
    Ok(())
}

fn link_diode() -> Result {
    let sh = xshell::Shell::new().unwrap();
    sh.change_dir(project_root());
    let openvaf = cargo_bin("openvaf-r");
    xshell::cmd!(sh, "{openvaf} -O 0 integration_tests/DIODE/diode.va").run()?;
    sh.remove_path("integration_tests/DIODE/diode.osdi").unwrap();
    Ok(())
}

/// Enhancement-695 (hunt F5 of 2026-09-21): `--target_cpu bogus` compiled with
/// exit 0 for a generic CPU behind 33 interleaved copies of LLVM's own
/// "'bogus' is not a recognized processor for this target (ignoring processor)".
/// It is refused before any work, once, in the compiler's words, with LLVM's
/// line captured rather than printed. Unix only: the capture needs `dup2`.
#[cfg(unix)]
fn target_cpu_unknown() -> Result {
    let sh = xshell::Shell::new().unwrap();
    sh.change_dir(project_root());
    let openvaf = cargo_bin("openvaf-r");
    let out = xshell::cmd!(sh, "{openvaf} --dry-run --target_cpu bogus_cpu integration_tests/DIODE/diode.va")
        .ignore_status()
        .output()?;
    let stderr = String::from_utf8_lossy(&out.stderr);
    assert!(!out.status.success(), "an unknown --target_cpu must be refused, got {stderr}");
    assert!(
        stderr.contains("--target_cpu 'bogus_cpu' is not a processor LLVM knows for"),
        "the refusal must name the flag and the value: {stderr}"
    );
    assert!(stderr.contains("'native'") && stderr.contains("'generic'"), "the help line: {stderr}");
    assert!(
        !stderr.lines().any(|l| l.starts_with("'bogus_cpu' is not a recognized processor")),
        "LLVM's own line leaked: {stderr}"
    );
    Ok(())
}

harness! {
    Test::new("cli::link_diode", &link_diode),
    #[cfg(unix)]
    Test::new("cli::target_cpu_unknown", &target_cpu_unknown),
    Test::from_list(
        "cli::smoke_test",
         &smoke_test,
         &ignore_never,
         &[
            "--target_cpu generic",
            "--target_cpu native",
            // Enhancement-695: an unknown processor is refused now, so the
            // named one has to exist for the host's architecture (skylake is
            // an x86 processor; on an Apple Silicon host LLVM used to ignore it
            // with a warning and the build went on).
            #[cfg(target_arch = "x86_64")]
            "--target_cpu skylake",
            #[cfg(target_arch = "aarch64")]
            "--target_cpu cortex-a72",
             // "--dump-json",
             "--supported-targets",
             "--batch",
             "--batch --cache-dir sourcegen",
             "-O 0",
             "-O 1",
             "-O 2",
             "-O 3",
             "-I sourcegen",
             "-D foo",
             "--print-expansion",
             "--supported-targets",
             "--lints",
             "-D all",
             "-D warnings",
             "-D macro_overwritten",
             "-W errors",
             "-W all",
             "-W macro_overwritten",
             "-A errors",
             "-A warnings",
             "-A all",
             "-A macro_overwritten",
        ]
    )
}
