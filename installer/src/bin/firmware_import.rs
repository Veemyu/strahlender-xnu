#[path = "../firmware.rs"]
mod firmware;
fn main() {
    let args: Vec<_> = std::env::args_os().skip(1).collect();
    if args.len() != 5 {
        eprintln!(
            "Usage: firmware_import <ZIP-or-NCA-folder> <prod.keys> <hactool> <cache> <result.json>"
        );
        std::process::exit(2);
    }
    match firmware::import(
        args[0].as_ref(),
        args[1].as_ref(),
        args[2].as_ref(),
        args[3].as_ref(),
    ) {
        Ok(root) => {
            let value = serde_json::json!({"firmware":root});
            if std::fs::write(&args[4], serde_json::to_vec(&value).unwrap()).is_err() {
                eprintln!("Could not record firmware result.");
                std::process::exit(1);
            }
        }
        Err(error) => {
            eprintln!("Firmware import failed: {error}");
            std::process::exit(1);
        }
    }
}
