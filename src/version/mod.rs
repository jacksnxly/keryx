//! Version management and semver bumping.

pub mod bump;
pub mod llm_bump;

pub use bump::{BumpType, apply_bump_to_version, calculate_next_version, determine_bump_type};
pub use llm_bump::{VersionBumpInput, calculate_next_version_with_llm};
