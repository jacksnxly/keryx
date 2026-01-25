//! Changelog parsing and writing.

pub mod format;
pub mod parser;
pub mod writer;

pub use format::{ChangelogCategory, ChangelogEntry, ChangelogOutput};
pub use parser::read_changelog;
pub use writer::write_changelog;
