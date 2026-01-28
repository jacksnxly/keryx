//! PR fetching via octocrab.

use std::env;
use std::num::NonZeroU64;

use chrono::{DateTime, Utc};
use octocrab::Octocrab;
use serde::{Deserialize, Serialize};
use tracing::warn;

use crate::error::GitHubError;

/// Default maximum number of PRs to fetch.
const DEFAULT_PR_LIMIT: usize = 100;

/// Environment variable to override the default PR limit.
const PR_LIMIT_ENV_VAR: &str = "KERYX_PR_LIMIT";

/// Get the configured PR limit.
///
/// Reads from KERYX_PR_LIMIT environment variable if set,
/// otherwise uses the default of 100 PRs.
///
/// Logs a warning if the environment variable is set but contains
/// an invalid value (non-numeric, empty, or zero).
fn get_pr_limit() -> usize {
    match env::var(PR_LIMIT_ENV_VAR) {
        Ok(v) if !v.is_empty() => match v.parse::<usize>() {
            Ok(0) => {
                warn!(
                    "Invalid {} value '0' (must be > 0), using default {}",
                    PR_LIMIT_ENV_VAR, DEFAULT_PR_LIMIT
                );
                DEFAULT_PR_LIMIT
            }
            Ok(limit) => limit,
            Err(_) => {
                warn!(
                    "Invalid {} value '{}', using default {}",
                    PR_LIMIT_ENV_VAR, v, DEFAULT_PR_LIMIT
                );
                DEFAULT_PR_LIMIT
            }
        },
        _ => DEFAULT_PR_LIMIT,
    }
}

/// Represents a GitHub PR.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PullRequest {
    pub number: NonZeroU64,
    pub title: String,
    pub body: Option<String>,
    pub merged_at: Option<DateTime<Utc>>,
    pub labels: Vec<String>,
}

/// Maximum PR body length to prevent token exhaustion (per spec: 10KB).
const MAX_BODY_LENGTH: usize = 10 * 1024;

/// Truncate a string to max_len characters, ensuring valid UTF-8 at the boundary.
///
/// Unlike byte slicing, this is safe for multi-byte characters (e.g., Japanese, emoji).
fn truncate_body(body: &str, max_len: usize) -> String {
    if body.len() <= max_len {
        return body.to_string();
    }

    // Find a valid character boundary at or before max_len
    let mut end = max_len;
    while end > 0 && !body.is_char_boundary(end) {
        end -= 1;
    }

    format!("{}... [truncated]", &body[..end])
}

/// Fetch merged PRs from a GitHub repository using a token.
///
/// This is the main entry point that constructs the octocrab client.
/// Fetches PRs merged between the given dates.
///
/// # Arguments
/// * `limit` - Maximum number of PRs to fetch. If None, uses KERYX_PR_LIMIT env var or default (100).
pub async fn fetch_merged_prs(
    token: &str,
    owner: &str,
    repo: &str,
    since: Option<DateTime<Utc>>,
    until: Option<DateTime<Utc>>,
    limit: Option<usize>,
) -> Result<Vec<PullRequest>, GitHubError> {
    let octocrab = Octocrab::builder()
        .personal_token(token.to_string())
        .build()
        .map_err(|e| GitHubError::FetchPRs(Box::new(e)))?;

    fetch_merged_prs_with_client(&octocrab, owner, repo, since, until, limit).await
}

/// Fetch merged PRs using a pre-configured octocrab client.
///
/// This allows dependency injection for testing with mock servers.
///
/// # Arguments
/// * `limit` - Maximum number of PRs to fetch. If None, uses KERYX_PR_LIMIT env var or default (100).
pub async fn fetch_merged_prs_with_client(
    octocrab: &Octocrab,
    owner: &str,
    repo: &str,
    since: Option<DateTime<Utc>>,
    until: Option<DateTime<Utc>>,
    limit: Option<usize>,
) -> Result<Vec<PullRequest>, GitHubError> {
    let effective_limit = limit.unwrap_or_else(get_pr_limit);
    let mut all_prs = Vec::new();
    let mut page = 1u32;
    let mut hit_limit = false;

    loop {
        let result = octocrab
            .pulls(owner, repo)
            .list()
            .state(octocrab::params::State::Closed)
            .sort(octocrab::params::pulls::Sort::Updated)
            .direction(octocrab::params::Direction::Descending)
            .per_page(100)
            .page(page)
            .send()
            .await;

        let prs_page = match result {
            Ok(page) => page,
            Err(e) => {
                // Check error content using both Display and Debug output
                // to handle different octocrab error formats
                let err_display = e.to_string();
                let err_debug = format!("{:?}", e);
                let err_lower = err_display.to_lowercase();
                let debug_lower = err_debug.to_lowercase();

                // Check for rate limiting (GitHub returns 403 with rate limit message)
                if err_lower.contains("rate limit") || debug_lower.contains("rate limit") {
                    return Err(GitHubError::RateLimited {
                        reset_time: "unknown".to_string(),
                    });
                }
                // Check for not found (GitHub returns 404)
                if err_display.contains("Not Found") || err_debug.contains("Not Found") {
                    return Err(GitHubError::RepositoryNotFound {
                        owner: owner.to_string(),
                        repo: repo.to_string(),
                    });
                }
                return Err(GitHubError::FetchPRs(Box::new(e)));
            }
        };

        let items = prs_page.items;
        if items.is_empty() {
            break;
        }

        for pr in items {
            // Only include merged PRs
            let merged_at = match pr.merged_at {
                Some(merged) => merged,
                None => continue,
            };

            // Filter by date range if specified
            if let Some(since_date) = since
                && merged_at < since_date
            {
                continue;
            }

            if let Some(until_date) = until
                && merged_at > until_date
            {
                continue;
            }

            // Validate PR number (0 is invalid, should never happen from GitHub API)
            let number = match NonZeroU64::new(pr.number) {
                Some(n) => n,
                None => {
                    warn!(
                        "Skipping PR with invalid number 0 (title: {:?})",
                        pr.title.as_deref().unwrap_or("<no title>")
                    );
                    continue;
                }
            };

            // Truncate body per spec (10KB max)
            let body = pr.body.map(|b| truncate_body(&b, MAX_BODY_LENGTH));

            let labels = pr
                .labels
                .unwrap_or_default()
                .into_iter()
                .map(|l| l.name)
                .collect();

            all_prs.push(PullRequest {
                number,
                title: pr.title.unwrap_or_default(),
                body,
                merged_at: Some(merged_at),
                labels,
            });

            // Check PR limit
            if all_prs.len() >= effective_limit {
                hit_limit = true;
                break;
            }
        }

        // Exit outer loop if we hit the PR limit
        if hit_limit {
            warn!(
                "Reached PR limit ({}) while fetching PRs for {}/{}. \
                Use KERYX_PR_LIMIT env var or --pr-limit to increase.",
                effective_limit, owner, repo
            );
            break;
        }

        // Check if there are more pages
        if prs_page.next.is_none() {
            break;
        }

        page += 1;

        // Safety limit to prevent infinite loops
        if page > 50 {
            warn!(
                "Reached 50-page safety limit while fetching PRs for {}/{}. \
                {} PRs collected. Consider using date filters to narrow the range.",
                owner, repo, all_prs.len()
            );
            break;
        }
    }

    Ok(all_prs)
}

/// Extract owner and repo from a git remote URL.
pub fn parse_github_remote(url: &str) -> Result<(String, String), GitHubError> {
    // Handle SSH format: git@github.com:owner/repo.git
    if url.starts_with("git@github.com:") {
        let path = url
            .strip_prefix("git@github.com:")
            .ok_or(GitHubError::InvalidRepositoryUrl)?;
        return parse_owner_repo_path(path);
    }

    // Handle HTTPS format: https://github.com/owner/repo.git
    if url.contains("github.com/") {
        let path = url
            .split("github.com/")
            .nth(1)
            .ok_or(GitHubError::InvalidRepositoryUrl)?;
        return parse_owner_repo_path(path);
    }

    Err(GitHubError::InvalidRepositoryUrl)
}

fn parse_owner_repo_path(path: &str) -> Result<(String, String), GitHubError> {
    let path = path.strip_suffix(".git").unwrap_or(path);
    let parts: Vec<&str> = path.split('/').collect();

    if parts.len() >= 2 {
        Ok((parts[0].to_string(), parts[1].to_string()))
    } else {
        Err(GitHubError::InvalidRepositoryUrl)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_ssh_url() {
        let (owner, repo) = parse_github_remote("git@github.com:owner/repo.git").unwrap();
        assert_eq!(owner, "owner");
        assert_eq!(repo, "repo");
    }

    #[test]
    fn test_parse_https_url() {
        let (owner, repo) = parse_github_remote("https://github.com/owner/repo.git").unwrap();
        assert_eq!(owner, "owner");
        assert_eq!(repo, "repo");
    }

    #[test]
    fn test_parse_https_url_no_git_suffix() {
        let (owner, repo) = parse_github_remote("https://github.com/owner/repo").unwrap();
        assert_eq!(owner, "owner");
        assert_eq!(repo, "repo");
    }

    #[test]
    fn test_parse_invalid_url() {
        let result = parse_github_remote("https://gitlab.com/owner/repo");
        assert!(result.is_err());
    }

    #[test]
    fn test_truncate_body_short_string() {
        let body = "Hello, world!";
        let result = truncate_body(body, 100);
        assert_eq!(result, "Hello, world!");
    }

    #[test]
    fn test_truncate_body_exact_length() {
        let body = "Hello";
        let result = truncate_body(body, 5);
        assert_eq!(result, "Hello");
    }

    #[test]
    fn test_truncate_body_ascii_overflow() {
        let body = "Hello, world!";
        let result = truncate_body(body, 5);
        assert_eq!(result, "Hello... [truncated]");
    }

    #[test]
    fn test_truncate_body_multibyte_japanese() {
        // Each Japanese character is 3 bytes
        // "あいう" = 9 bytes total
        let body = "あいう";
        // Truncate at 5 bytes - should back up to byte 3 (end of first char)
        let result = truncate_body(body, 5);
        assert_eq!(result, "あ... [truncated]");
        // Verify result is valid UTF-8
        assert!(result.is_ascii() || std::str::from_utf8(result.as_bytes()).is_ok());
    }

    #[test]
    fn test_truncate_body_multibyte_emoji() {
        // Emoji can be 4 bytes
        // "😀😁😂" = 12 bytes total
        let body = "😀😁😂";
        // Truncate at 6 bytes - should back up to byte 4 (end of first emoji)
        let result = truncate_body(body, 6);
        assert_eq!(result, "😀... [truncated]");
    }

    #[test]
    fn test_truncate_body_mixed_content() {
        // Mix of ASCII and multi-byte
        let body = "Hello あいう World";
        // "Hello " = 6 bytes, "あ" = 3 bytes = 9 bytes at "Hello あ"
        let result = truncate_body(body, 10);
        // Should truncate after "Hello あ" (9 bytes), not mid-character
        assert_eq!(result, "Hello あ... [truncated]");
    }

    #[test]
    fn test_truncate_body_large_multibyte() {
        // Test with many multi-byte characters exceeding MAX_BODY_LENGTH
        let body = "あ".repeat(5000); // 15000 bytes
        let result = truncate_body(&body, 10000);
        // Should not panic, should be valid UTF-8
        assert!(result.ends_with("... [truncated]"));
        // Verify it's valid UTF-8
        assert!(std::str::from_utf8(result.as_bytes()).is_ok());
        // Should have truncated to approximately 3333 characters (9999 bytes) or less
        let truncated_part = result.strip_suffix("... [truncated]").unwrap();
        assert!(truncated_part.len() <= 10000);
    }

    #[test]
    fn test_pullrequest_serialization_with_nonzero() {
        use std::num::NonZeroU64;

        let pr = PullRequest {
            number: NonZeroU64::new(42).unwrap(),
            title: "Test PR".to_string(),
            body: Some("Body".to_string()),
            merged_at: None,
            labels: vec!["bug".to_string()],
        };

        // Serialize
        let json = serde_json::to_string(&pr).expect("serialize");
        assert!(json.contains("\"number\":42"));

        // Deserialize
        let parsed: PullRequest = serde_json::from_str(&json).expect("deserialize");
        assert_eq!(parsed.number.get(), 42);
    }

    #[test]
    fn test_pullrequest_deserialize_rejects_zero() {
        let json = r#"{"number":0,"title":"Test","body":null,"merged_at":null,"labels":[]}"#;
        let result: Result<PullRequest, _> = serde_json::from_str(json);
        assert!(result.is_err(), "Should reject PR with number 0");
    }

    // =============================================================================
    // PR LIMIT CONFIGURATION TESTS
    // =============================================================================

    #[test]
    fn test_get_pr_limit_default() {
        temp_env::with_var_unset(PR_LIMIT_ENV_VAR, || {
            let limit = get_pr_limit();
            assert_eq!(limit, DEFAULT_PR_LIMIT);
        });
    }

    #[test]
    fn test_get_pr_limit_from_env() {
        temp_env::with_var(PR_LIMIT_ENV_VAR, Some("50"), || {
            let limit = get_pr_limit();
            assert_eq!(limit, 50);
        });
    }

    #[test]
    fn test_get_pr_limit_invalid_env_uses_default() {
        temp_env::with_var(PR_LIMIT_ENV_VAR, Some("not_a_number"), || {
            let limit = get_pr_limit();
            assert_eq!(limit, DEFAULT_PR_LIMIT);
        });
    }

    #[test]
    fn test_get_pr_limit_zero_uses_default() {
        temp_env::with_var(PR_LIMIT_ENV_VAR, Some("0"), || {
            let limit = get_pr_limit();
            assert_eq!(limit, DEFAULT_PR_LIMIT);
        });
    }

    #[test]
    fn test_get_pr_limit_empty_env_uses_default() {
        temp_env::with_var(PR_LIMIT_ENV_VAR, Some(""), || {
            let limit = get_pr_limit();
            assert_eq!(limit, DEFAULT_PR_LIMIT);
        });
    }
}
