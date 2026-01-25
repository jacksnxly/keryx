//! Version management and semver bumping.

pub mod bump;

pub use bump::{calculate_next_version, BumpType};
