//! GitHub API operations using octocrab.

pub mod auth;
pub mod prs;

pub use auth::get_github_token;
pub use prs::{PullRequest, fetch_merged_prs, fetch_merged_prs_with_client};
