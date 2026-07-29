// build.rs for openvaf-driver

fn git_version() -> String {
    let output = std::process::Command::new("git")
        .args(["describe", "--tags", "--long", "--dirty", "--match", "_*"])
        .output();
    match output {
        Ok(o) if o.status.success() => {
            let s = String::from_utf8(o.stdout).unwrap_or_default();
            let s = s.trim();
            s.strip_prefix('_').unwrap_or(s).to_string()
        }
        _ => "unknown".to_string(),
    }
}

fn main() {
    println!("cargo:rustc-env=OPENVAF_GIT_VERSION={}", git_version());
    // Rebuild if HEAD or any tag changes.
    println!("cargo:rerun-if-changed=../../.git/HEAD");
    println!("cargo:rerun-if-changed=../../.git/refs/tags");
    // Add rpath for LLVM on macOS
    #[cfg(target_os = "macos")]
    {
        // Homebrew's LLVM lib directory ships its own `libunwind.1.dylib`. That
        // directory is on the link search path (llvm-sys puts it there), so when
        // ld resolves the libunwind re-export coming from the SYSTEM
        // /usr/lib/libc++.1.dylib it finds Homebrew's copy first. Its install
        // name cannot be matched to the re-exporting parent, so ld warns
        //   "reexported library with install name '.../llvm@18/lib/libunwind.1.dylib'
        //    ... couldn't be matched with any parent library and will be linked directly"
        // and links it directly. The binary then carries a needless Homebrew
        // dependency and, in principle, two unwinders in one process.
        //
        // Putting the SDK's system stub directory ahead of it lets ld resolve the
        // re-export to the system libunwind: the warning disappears AND the
        // spurious dependency disappears with it (verified with `otool -L`).
        if let Ok(out) = std::process::Command::new("xcrun").arg("--show-sdk-path").output() {
            if out.status.success() {
                let sdk = String::from_utf8_lossy(&out.stdout).trim().to_string();
                if !sdk.is_empty() {
                    println!("cargo:rustc-link-search=native={sdk}/usr/lib/system");
                }
            }
        }

        if let Ok(output) = std::process::Command::new("llvm-config").arg("--libdir").output() {
            if output.status.success() {
                let libdir = String::from_utf8_lossy(&output.stdout).trim().to_string();
                println!("cargo:rustc-link-arg=-Wl,-rpath,{}", libdir);
            }
        }
    }
}
