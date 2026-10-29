fn main() -> std::process::ExitCode {
    std::process::ExitCode::from(bdsp_extract::cli(std::env::args_os().skip(1).collect()) as u8)
}
