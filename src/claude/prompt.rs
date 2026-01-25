//! Prompt construction for Claude.

use crate::git::ParsedCommit;
use crate::github::PullRequest;

/// Input to Claude for changelog generation.
#[derive(Debug, Clone, serde::Serialize)]
pub struct ChangelogInput {
    pub commits: Vec<ParsedCommit>,
    pub pull_requests: Vec<PullRequest>,
    pub previous_version: Option<String>,
    pub repository_name: String,
}

/// Build the prompt for Claude to generate changelog entries.
///
/// Follows the spec's prompt structure exactly.
pub fn build_prompt(input: &ChangelogInput) -> String {
    let commits_json = serde_json::to_string_pretty(&input.commits).unwrap_or_default();
    let prs_json = serde_json::to_string_pretty(&input.pull_requests).unwrap_or_default();

    format!(
        r#"You are generating release notes for a software project.

Given the following commits and pull requests, generate changelog entries
following the Keep a Changelog format.

## Commits
{commits_json}

## Pull Requests
{prs_json}

## Instructions
1. Group changes into categories: Added, Changed, Deprecated, Removed, Fixed, Security
2. Write user-facing descriptions (not technical commit messages)
3. Focus on benefits and impact
4. Combine related commits/PRs into single entries where appropriate
5. Ignore docs-only, test-only, and chore commits unless they affect users

Respond with JSON:
{{
  "entries": [
    {{"category": "Added", "description": "..."}},
    ...
  ]
}}"#
    )
}

/// Sanitize commit messages before passing to Claude to prevent prompt injection.
pub fn sanitize_for_prompt(text: &str) -> String {
    // Remove potential prompt injection patterns
    text.replace("```", "'''")
        .replace("##", "//")
        .lines()
        .take(50) // Limit lines
        .collect::<Vec<_>>()
        .join("\n")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_prompt_structure() {
        let input = ChangelogInput {
            commits: vec![],
            pull_requests: vec![],
            previous_version: Some("1.0.0".to_string()),
            repository_name: "test-repo".to_string(),
        };

        let prompt = build_prompt(&input);

        assert!(prompt.contains("You are generating release notes"));
        assert!(prompt.contains("## Commits"));
        assert!(prompt.contains("## Pull Requests"));
        assert!(prompt.contains("## Instructions"));
        assert!(prompt.contains("Respond with JSON"));
    }

    #[test]
    fn test_sanitize_removes_backticks() {
        let text = "```rust\ncode\n```";
        let sanitized = sanitize_for_prompt(text);
        assert!(!sanitized.contains("```"));
    }
}
