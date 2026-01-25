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
    /// Project description (from Cargo.toml or package.json)
    pub project_description: Option<String>,
    /// CLI features/flags available
    pub cli_features: Option<Vec<String>>,
}

/// Build the prompt for Claude to generate changelog entries.
///
/// Follows the spec's prompt structure exactly.
/// Sanitizes commit messages and PR bodies to prevent prompt injection.
pub fn build_prompt(input: &ChangelogInput) -> String {
    // Sanitize commits before serializing
    let sanitized_commits: Vec<_> = input.commits.iter().map(|c| {
        let mut commit = c.clone();
        commit.message = sanitize_for_prompt(&commit.message);
        commit
    }).collect();

    // Sanitize PRs before serializing
    let sanitized_prs: Vec<_> = input.pull_requests.iter().map(|pr| {
        let mut pr = pr.clone();
        pr.title = sanitize_for_prompt(&pr.title);
        pr.body = pr.body.as_ref().map(|b| sanitize_for_prompt(b));
        pr
    }).collect();

    let commits_json = serde_json::to_string_pretty(&sanitized_commits).unwrap_or_default();
    let prs_json = serde_json::to_string_pretty(&sanitized_prs).unwrap_or_default();

    let is_initial_release = input.previous_version.is_none();
    let repo_name = &input.repository_name;

    let context = if is_initial_release {
        let mut ctx = format!(
            r#"This is the INITIAL RELEASE of "{repo_name}".
For initial releases, describe the core features and capabilities that the project provides.
Do NOT skip entries just because commits look like "chore" or "initial commit" - this is the first release and users need to know what the project offers."#
        );

        // Add project description if available
        if let Some(desc) = &input.project_description {
            ctx.push_str(&format!("\n\nProject description: {}", desc));
        }

        // Add CLI features if available
        if let Some(features) = &input.cli_features {
            ctx.push_str("\n\nCLI features/flags available:");
            for feature in features {
                ctx.push_str(&format!("\n- {}", feature));
            }
        }

        ctx
    } else {
        format!(
            r#"This is an incremental release for "{repo_name}" (previous version: {}).
Focus only on changes since the last release.
Ignore docs-only, test-only, and chore commits unless they affect users."#,
            input.previous_version.as_ref().unwrap()
        )
    };

    format!(
        r#"You are generating release notes for a software project.

{context}

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
            project_description: None,
            cli_features: None,
        };

        let prompt = build_prompt(&input);

        assert!(prompt.contains("You are generating release notes"));
        assert!(prompt.contains("## Commits"));
        assert!(prompt.contains("## Pull Requests"));
        assert!(prompt.contains("## Instructions"));
        assert!(prompt.contains("Respond with JSON"));
    }

    #[test]
    fn test_initial_release_includes_context() {
        let input = ChangelogInput {
            commits: vec![],
            pull_requests: vec![],
            previous_version: None, // Initial release
            repository_name: "my-tool".to_string(),
            project_description: Some("A CLI tool for testing".to_string()),
            cli_features: Some(vec!["--verbose: Enable verbose output".to_string()]),
        };

        let prompt = build_prompt(&input);

        assert!(prompt.contains("INITIAL RELEASE"));
        assert!(prompt.contains("A CLI tool for testing"));
        assert!(prompt.contains("--verbose: Enable verbose output"));
    }

    #[test]
    fn test_sanitize_removes_backticks() {
        let text = "```rust\ncode\n```";
        let sanitized = sanitize_for_prompt(text);
        assert!(!sanitized.contains("```"));
    }
}
