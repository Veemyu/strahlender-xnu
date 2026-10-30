mod app;
mod backend;
mod capture;
mod components;
mod dependencies;
mod drop_target;
#[allow(dead_code)]
mod firmware;
mod i18n;
mod icons;
mod ios_devices;
mod ios_profile;
mod ios_signing;
mod key_paths;
mod mod_support;
mod motion;
mod platform;
mod preferences;
mod progress;
mod project_link;
mod runtime;
mod source_download;
mod sources;
mod style;
mod updates;
mod window_layout;
mod workspace;
mod workspace_cleanup;

use app::Installer;

fn main() -> iced::Result {
    let args: Vec<_> = std::env::args().skip(1).collect();
    match args.as_slice() {
        [flag] if flag == "--check-source" => {
            match workspace::source_smoke() {
                Ok(root) => println!(
                    "Downloaded source revision: {}",
                    root.file_name().unwrap_or_default().to_string_lossy()
                ),
                Err(error) => {
                    eprintln!("{error}");
                    std::process::exit(1);
                }
            }
            return Ok(());
        }
        [flag, rest @ ..] if flag == "--cli" => {
            // Build steps without the window: `--cli extract ...` (see installer/extract).
            std::process::exit(bdsp_extract::cli(rest.iter().map(Into::into).collect()));
        }
        [flag] if flag == "--check-runtime" => {
            if let Err(error) = runtime::runtime_smoke() {
                eprintln!("{error}");
                std::process::exit(1);
            }
            return Ok(());
        }
        [flag] if flag == "--licenses" => {
            println!(
                "{}\n\n{}\n\n{}\n\n{}\n\n{}\n\n{}",
                include_str!("../assets/OCTICONS-LICENSE"),
                include_str!("../assets/lucide/LICENSE"),
                include_str!("../assets/FIRA-LICENSE"),
                include_str!("../vendor/iced_winit/LICENSE"),
                include_str!("../assets/firmware-import-licenses/ZIP-MIT.txt"),
                include_str!("../assets/firmware-import-licenses/TTF-PARSER-MIT.txt")
            );
            return Ok(());
        }
        [flag] if flag == "--help" || flag == "-h" => {
            println!(
                "strahlender-xnu-installer [--demo | --capture-dir DIRECTORY] [--platform mac|windows|linux]\n\n--demo         Explore all views with synthetic example files.\n--capture-dir  Save deterministic dark-mode screenshots and exit.\n--scenes       Comma-separated capture scenes (default: target; all: full matrix).\n--platform     Simulate host UI in demo/capture mode only.\n--licenses     Show the licenses for bundled UI icons and Fira Sans.\n--cli            Run a build step without the window: --cli extract|check|unpack (see installer/extract).\n--check-runtime  Exercise the private Python runtime without starting a game.\n--check-source   Download current main into a new workspace without building a game."
            );
            return Ok(());
        }
        _ => {}
    }
    let options = platform::Options::parse(&args).unwrap_or_else(|error| {
        eprintln!("{error}. See --help.");
        std::process::exit(2);
    });
    iced::application(
        move || Installer::with_options(options.clone()),
        Installer::update,
        Installer::view,
    )
    .title("strahlender · Installer")
    .theme(Installer::theme)
    .subscription(Installer::subscription)
    .window(iced::window::Settings {
        size: iced::Size::new(window_layout::WIDTH, window_layout::HEIGHT),
        resizable: false,
        #[cfg(target_os = "linux")]
        platform_specific: iced::window::settings::PlatformSpecific {
            application_id: "strahlender".into(),
            ..Default::default()
        },
        // macOS uses the app bundle's native icon, including Liquid Glass.
        icon: if cfg!(target_os = "macos") {
            None
        } else {
            Some(
                iced::window::icon::from_rgba(
                    include_bytes!(concat!(env!("OUT_DIR"), "/brand/64.rgba")).to_vec(),
                    64,
                    64,
                )
                .expect("Build-time installer icon has valid dimensions"),
            )
        },
        ..Default::default()
    })
    .default_font(iced::Font::with_name("Fira Sans"))
    .run()
}
