use crate::spec::{LinkerFlavor, Target};

use super::apple_base;

pub fn target() -> Target {
    let mut base = apple_base::opts();
    base.cpu = "core2".to_string();
    base.pre_link_args.insert(
        LinkerFlavor::Ld64,
        vec![
            "-Wl,-undefined,dynamic_lookup".to_string(),
        ],
    );

    // Enhancement-771: no explicit -lSystem. clang links libSystem into every
    // -dynamiclib itself (the arm64 target never passed it), and the second
    // copy made Apple's linker warn "ignoring duplicate libraries: '-lSystem'"
    // on every model.

    Target {
        llvm_target: "x86_64-apple-macosx10.15.0".to_owned(),
        arch: "x86_64".to_owned(),
        data_layout: "e-m:o-p270:32:32-p271:32:32-p272:64:64-i64:64-f80:128-n8:16:32:64-S128"
            .to_string(),
        options: base,
        pointer_width: 64,
    }
}
