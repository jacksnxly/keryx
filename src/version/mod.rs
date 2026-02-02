//! Version management and semver bumping.

pub mod bump;
pub mod llm_bump;

pub use bump::{apply_bump_to_version, calculate_next_version, determine_bump_type, BumpType};
pub use llm_bump::{calculate_next_version_with_llm, VersionBumpInput};
