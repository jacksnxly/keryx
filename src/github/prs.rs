//! PR fetching via octocrab.

use chrono::{DateTime, Utc};
use octocrab::Octocrab;
use serde::{Deserialize, Serialize};

use crate::error::GitHubError;

/// Represents a GitHub PR.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PullRequest {
    pub number: u64,
    pub title: String,
    pub body: Option<String>,
    pub merged_at: Option<DateTime<Utc>>,
    pub labels: Vec<String>,
}

/// Maximum PR body length to prevent token exhaustion (per spec: 10KB).
const MAX_BODY_LENGTH: usize = 10 * 1024;

/// Fetch merged PRs from a GitHub repository.
///
/// Fetches PRs merged between the given dates.
pub async fn fetch_merged_prs(
    token: &str,
    owner: &str,
    repo: &str,
    since: Option<DateTime<Utc>>,
    until: Option<DateTime<Utc>>,
) -> Result<Vec<PullRequest>, GitHubError> {
    let octocrab = Octocrab::builder()
        .personal_token(token.to_string())
        .build()
        .map_err(GitHubError::FetchPRs)?;

    let mut all_prs = Vec::new();
    let mut page = 1u32;

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
                let err_str = e.to_string();
                // Check for rate limiting
                if err_str.contains("rate limit") {
                    return Err(GitHubError::RateLimited {
                        reset_time: "unknown".to_string(),
                    });
                }
                // Check for not found
                if err_str.contains("Not Found") {
                    return Err(GitHubError::RepositoryNotFound {
                        owner: owner.to_string(),
                        repo: repo.to_string(),
                    });
                }
                return Err(GitHubError::FetchPRs(e));
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
            if let Some(since_date) = since {
                if merged_at < since_date {
                    continue;
                }
            }

            if let Some(until_date) = until {
                if merged_at > until_date {
                    continue;
                }
            }

            // Truncate body per spec (10KB max)
            let body = pr.body.map(|b| {
                if b.len() > MAX_BODY_LENGTH {
                    format!("{}... [truncated]", &b[..MAX_BODY_LENGTH])
                } else {
                    b
                }
            });

            let labels = pr
                .labels
                .unwrap_or_default()
                .into_iter()
                .map(|l| l.name)
                .collect();

            all_prs.push(PullRequest {
                number: pr.number,
                title: pr.title.unwrap_or_default(),
                body,
                merged_at: Some(merged_at),
                labels,
            });
        }

        // Check if there are more pages
        if prs_page.next.is_none() {
            break;
        }

        page += 1;

        // Safety limit to prevent infinite loops
        if page > 50 {
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
}
