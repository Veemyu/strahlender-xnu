fn main() {
    if std::env::var("CARGO_CFG_TARGET_FAMILY")
        .is_ok_and(|family| family.split(',').any(|part| part == "unix"))
    {
        let source = "../scripts/recomp/rt-bdsp/mods.c";
        println!("cargo:rerun-if-changed={source}");
        println!("cargo:rerun-if-changed=../scripts/recomp/rt-bdsp/mods.h");
        cc::Build::new().file(source).compile("bdsp_mod_scan");
    }
}
