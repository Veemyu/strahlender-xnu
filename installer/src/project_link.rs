//! The destination is fixed, independent of game metadata and user input.
pub const REPOSITORY: &str = "https://github.com/Veemyu/strahlender-xnu";

pub fn open() -> Result<(), ()> {
    crate::open::url(REPOSITORY).map_err(|_| ())
}
