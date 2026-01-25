//! GitHub authentication detection.
//!
//! Auth order per spec:
//! 1. Check `gh auth status` (gh CLI)
//! 2. Fall back to GITHUB_TOKEN env var
//! 3. Fall back to GH_TOKEN env var

use std::env;
use std::process::Command;

use crate::error::GitHubError;

/// Get a GitHub token using the configured auth strategy.
///
/// Checks in order:
/// 1. gh CLI auth (via `gh auth token`)
/// 2. GITHUB_TOKEN environment variable
/// 3. GH_TOKEN environment variable
pub fn get_github_token() -> Result<String, GitHubError> {
    // Try gh CLI first
    if let Some(token) = get_token_from_gh_cli() {
        return Ok(token);
    }

    // Fall back to GITHUB_TOKEN
    if let Ok(token) = env::var("GITHUB_TOKEN") {
        if !token.is_empty() {
            return Ok(token);
        }
    }

    // Fall back to GH_TOKEN
    if let Ok(token) = env::var("GH_TOKEN") {
        if !token.is_empty() {
            return Ok(token);
        }
    }

    Err(GitHubError::AuthenticationFailed)
}

/// Try to get a token from the gh CLI.
fn get_token_from_gh_cli() -> Option<String> {
    // First check if gh is authenticated
    let status = Command::new("gh")
        .args(["auth", "status"])
        .output()
        .ok()?;

    if !status.status.success() {
        return None;
    }

    // Get the actual token
    let output = Command::new("gh")
        .args(["auth", "token"])
        .output()
        .ok()?;

    if output.status.success() {
        let token = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if !token.is_empty() {
            return Some(token);
        }
    }

    None
}

/// Check if GitHub authentication is available (without retrieving the token).
pub fn is_github_auth_available() -> bool {
    get_github_token().is_ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_env_var_fallback() {
        // This test depends on environment, so it's more of a smoke test
        // Real tests would mock the environment
        let _ = get_github_token();
    }
}
