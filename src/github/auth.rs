//! GitHub authentication detection.
//!
//! Auth order:
//! 1. gh CLI auth (verified via `gh auth status`, token retrieved via `gh auth token`)
//! 2. GITHUB_TOKEN environment variable
//! 3. GH_TOKEN environment variable

use std::env;

use tokio::process::Command;

use crate::error::GitHubError;

/// Get a GitHub token using the configured auth strategy.
///
/// Checks in order:
/// 1. gh CLI auth (verified via `gh auth status`, token retrieved via `gh auth token`)
/// 2. GITHUB_TOKEN environment variable
/// 3. GH_TOKEN environment variable
pub async fn get_github_token() -> Result<String, GitHubError> {
    // Try gh CLI first
    if let Some(token) = get_token_from_gh_cli().await {
        return Ok(token);
    }

    // Fall back to environment variables
    get_token_from_env()
}

/// Try to get a token from environment variables only.
///
/// Checks in order:
/// 1. GITHUB_TOKEN environment variable
/// 2. GH_TOKEN environment variable
pub fn get_token_from_env() -> Result<String, GitHubError> {
    // Try GITHUB_TOKEN first
    if let Ok(token) = env::var("GITHUB_TOKEN")
        && !token.is_empty()
    {
        return Ok(token);
    }

    // Fall back to GH_TOKEN
    if let Ok(token) = env::var("GH_TOKEN")
        && !token.is_empty()
    {
        return Ok(token);
    }

    Err(GitHubError::AuthenticationFailed)
}

/// Try to get a token from the gh CLI.
async fn get_token_from_gh_cli() -> Option<String> {
    // First check if gh is authenticated
    let status = match Command::new("gh").args(["auth", "status"]).output().await {
        Ok(s) => s,
        Err(e) => {
            tracing::debug!("gh CLI not available or failed to execute: {}", e);
            return None;
        }
    };

    if !status.status.success() {
        tracing::debug!(
            "gh auth status failed: {}",
            String::from_utf8_lossy(&status.stderr).trim()
        );
        return None;
    }

    // Get the actual token
    let output = match Command::new("gh").args(["auth", "token"]).output().await {
        Ok(o) => o,
        Err(e) => {
            tracing::debug!("gh auth token command failed to execute: {}", e);
            return None;
        }
    };

    if output.status.success() {
        let token = String::from_utf8_lossy(&output.stdout).trim().to_string();
        if !token.is_empty() {
            return Some(token);
        }
        tracing::debug!("gh auth token returned empty output");
    } else {
        tracing::debug!(
            "gh auth token failed: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        );
    }

    None
}

/// Parse the output of `gh auth token` command.
///
/// Returns the token if the output is valid, None otherwise.
pub fn parse_gh_auth_token_output(output: &str) -> Option<String> {
    let token = output.trim().to_string();
    if token.is_empty() {
        None
    } else {
        Some(token)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_github_token_takes_precedence_over_gh_token() {
        temp_env::with_vars(
            [
                ("GITHUB_TOKEN", Some("github_token_value")),
                ("GH_TOKEN", Some("gh_token_value")),
            ],
            || {
                let result = get_token_from_env();
                assert!(result.is_ok());
                assert_eq!(result.unwrap(), "github_token_value");
            },
        );
    }

    #[test]
    fn test_fallback_to_gh_token_when_github_token_empty() {
        temp_env::with_vars(
            [
                ("GITHUB_TOKEN", Some("")),
                ("GH_TOKEN", Some("gh_token_value")),
            ],
            || {
                let result = get_token_from_env();
                assert!(result.is_ok());
                assert_eq!(result.unwrap(), "gh_token_value");
            },
        );
    }

    #[test]
    fn test_fallback_to_gh_token_when_github_token_unset() {
        temp_env::with_vars(
            [
                ("GITHUB_TOKEN", None),
                ("GH_TOKEN", Some("gh_token_value")),
            ],
            || {
                let result = get_token_from_env();
                assert!(result.is_ok());
                assert_eq!(result.unwrap(), "gh_token_value");
            },
        );
    }

    #[test]
    fn test_empty_string_tokens_are_rejected() {
        temp_env::with_vars(
            [("GITHUB_TOKEN", Some("")), ("GH_TOKEN", Some(""))],
            || {
                let result = get_token_from_env();
                assert!(result.is_err());
            },
        );
    }

    #[test]
    fn test_error_when_no_tokens_available() {
        temp_env::with_vars(
            [
                ("GITHUB_TOKEN", None::<&str>),
                ("GH_TOKEN", None::<&str>),
            ],
            || {
                let result = get_token_from_env();
                assert!(result.is_err());
            },
        );
    }

    #[test]
    fn test_parse_gh_auth_token_output_valid() {
        let output = "gho_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n";
        let result = parse_gh_auth_token_output(output);
        assert_eq!(
            result,
            Some("gho_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx".to_string())
        );
    }

    #[test]
    fn test_parse_gh_auth_token_output_empty() {
        let result = parse_gh_auth_token_output("");
        assert!(result.is_none());
    }

    #[test]
    fn test_parse_gh_auth_token_output_whitespace_only() {
        let result = parse_gh_auth_token_output("   \n\t  ");
        assert!(result.is_none());
    }

    #[test]
    fn test_parse_gh_auth_token_output_trims_whitespace() {
        let output = "  gho_token_with_spaces  \n";
        let result = parse_gh_auth_token_output(output);
        assert_eq!(result, Some("gho_token_with_spaces".to_string()));
    }
}
