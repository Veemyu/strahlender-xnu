#[path = "../components.rs"]
mod components;
#[path = "../dependencies.rs"]
mod dependencies;
#[allow(dead_code)]
#[path = "../runtime.rs"]
mod runtime;
#[allow(dead_code)]
#[path = "../source_download.rs"]
mod source_download;

fn main() {
    let log = dependencies::read_setup_log();
    if !log.is_empty() {
        eprintln!("{log}");
    }
    let args: Vec<_> = std::env::args().skip(1).collect();
    if args
        .iter()
        .any(|a| !["--install", "--ios"].contains(&a.as_str()))
    {
        eprintln!("Usage: installer_setup [--ios] [--install]");
        std::process::exit(2);
    }
    let result = dependencies::inspect(if args.iter().any(|a| a == "--ios") {
        "ios"
    } else {
        "native"
    });
    match result {
        Ok(plan) => {
            println!("{}", serde_json::to_string_pretty(&plan).unwrap());
            if args.iter().any(|a| a == "--install") && !plan.ready() {
                eprintln!("{}", plan.description());
                if let Err(error) = dependencies::install(&plan) {
                    eprintln!("{error}");
                    std::process::exit(1);
                }
            } else if !plan.ready() {
                std::process::exit(3);
            }
        }
        Err(error) => {
            eprintln!("{error}");
            std::process::exit(1);
        }
    }
}
