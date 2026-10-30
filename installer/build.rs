#[path = "build_support/brand.rs"]
mod brand;

fn main() {
    println!("cargo:rerun-if-changed=assets/brand/icon.svg");
    println!("cargo:rerun-if-changed=build_support/brand.rs");
    let output = std::path::PathBuf::from(std::env::var_os("OUT_DIR").unwrap()).join("brand");
    brand::generate(&output).expect("Failed to render the bundled installer icon");
    if std::env::var("CARGO_CFG_TARGET_FAMILY")
        .is_ok_and(|family| family.split(',').any(|part| part == "unix"))
    {
        let source = "../scripts/recomp/runtime/mods.c";
        println!("cargo:rerun-if-changed={source}");
        println!("cargo:rerun-if-changed=../scripts/recomp/runtime/mods.h");
        cc::Build::new().file(source).compile("bdsp_mod_scan");
    }
}
