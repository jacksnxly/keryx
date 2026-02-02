//! LLM-based version bump determination.
//!
//! Semantically analyzes commits and PRs to determine the correct semver bump.
//! Falls back to the algorithmic approach on any failure.

use semver::Version;
use serde::Deserialize;
use tracing::{debug, warn};

use crate::git::ParsedCommit;
use crate::github::PullRequest;
use crate::llm::prompt::sanitize_for_prompt;
use crate::llm::LlmRouter;
use crate::version::bump::{apply_bump_to_version, determine_bump_type, BumpType};

/// Input for LLM-based version bump determination.
pub struct VersionBumpInput<'a> {
    pub commits: &'a [ParsedCommit],
    pub pull_requests: &'a [PullRequest],
    pub previous_version: Option<&'a Version>,
    pub repository_name: &'a str,
}

/// Response from the LLM for version bump.
#[derive(Deserialize)]
struct VersionBumpResponse {
    bump_type: String,
    reasoning: String,
}

/// Build the prompt for LLM-based version bump determination.
fn build_version_bump_prompt(input: &VersionBumpInput) -> Result<String, crate::llm::prompt::PromptError> {
    let sanitized_commits: Vec<String> = input
        .commits
        .iter()
        .map(|c| {
            let breaking = if c.breaking { " [BREAKING]" } else { "" };
            let ctype = c
                .commit_type
                .as_ref()
                .map(|t| format!("{:?}: ", t))
                .unwrap_or_default();
            sanitize_for_prompt(&format!("{}{}{}", ctype, c.message, breaking))
        })
        .collect();

    let sanitized_prs: Vec<String> = input
        .pull_requests
        .iter()
        .map(|pr| {
            let body_snippet = pr
                .body
                .as_deref()
                .map(|b| {
                    let truncated = if b.len() > 500 { &b[..500] } else { b };
                    sanitize_for_prompt(truncated)
                })
                .unwrap_or_default();
            sanitize_for_prompt(&format!("PR #{}: {} - {}", pr.number, pr.title, body_snippet))
        })
        .collect();

    let version_context = match input.previous_version {
        Some(v) => format!("The previous version is {}.", v),
        None => "There is no previous version (initial release).".to_string(),
    };

    Ok(format!(
        r#"You are determining the next semantic version bump for the project "{repo}".

## Semantic Versioning Rules
- **major**: Breaking changes that are incompatible with the previous API/behavior
- **minor**: New features or functionality added in a backwards-compatible manner
- **patch**: Backwards-compatible bug fixes, performance improvements, or internal changes

{version_context}

## Commits
{commits}

## Pull Requests
{prs}

## Instructions
Analyze the commits and PRs above. Determine whether this release warrants a **major**, **minor**, or **patch** bump.

Respond with JSON only (no markdown wrapping):
{{"bump_type": "major|minor|patch", "reasoning": "brief explanation"}}"#,
        repo = input.repository_name,
        version_context = version_context,
        commits = sanitized_commits.join("\n"),
        prs = if sanitized_prs.is_empty() {
            "(none)".to_string()
        } else {
            sanitized_prs.join("\n")
        },
    ))
}

/// Parse the LLM response into a BumpType.
///
/// Handles JSON that may be wrapped in markdown code blocks.
fn parse_version_bump_response(response: &str) -> Option<(BumpType, String)> {
    // Try to extract JSON from markdown wrapping
    let json_str = extract_json_from_response(response);

    let parsed: VersionBumpResponse = serde_json::from_str(&json_str).ok()?;

    let bump = match parsed.bump_type.to_lowercase().as_str() {
        "major" => BumpType::Major,
        "minor" => BumpType::Minor,
        "patch" => BumpType::Patch,
        _ => return None,
    };

    Some((bump, parsed.reasoning))
}

/// Extract JSON from a response that may be wrapped in markdown code blocks.
fn extract_json_from_response(response: &str) -> String {
    let trimmed = response.trim();

    // Try markdown code block
    if let Some(start) = trimmed.find("```json") {
        if let Some(end) = trimmed[start + 7..].find("```") {
            return trimmed[start + 7..start + 7 + end].trim().to_string();
        }
    }

    // Try bare code block
    if let Some(start) = trimmed.find("```") {
        if let Some(end) = trimmed[start + 3..].find("```") {
            let inner = trimmed[start + 3..start + 3 + end].trim();
            if inner.starts_with('{') {
                return inner.to_string();
            }
        }
    }

    // Try finding a JSON object directly
    if let Some(start) = trimmed.find('{') {
        if let Some(end) = trimmed.rfind('}') {
            return trimmed[start..=end].to_string();
        }
    }

    trimmed.to_string()
}

/// Determine the version bump using an LLM, with algorithmic fallback.
///
/// This function **never fails**. On any error (prompt build, LLM call, parse),
/// it prints a warning and returns the algorithmic result.
pub async fn determine_version_with_llm(
    input: &VersionBumpInput<'_>,
    llm: &mut LlmRouter,
    verbose: bool,
) -> (BumpType, Option<String>) {
    let algorithmic_bump = determine_bump_type(input.commits);

    let prompt = match build_version_bump_prompt(input) {
        Ok(p) => p,
        Err(e) => {
            warn!("Failed to build version bump prompt: {}. Using algorithmic bump.", e);
            return (algorithmic_bump, None);
        }
    };

    let response = match llm.generate_raw(&prompt).await {
        Ok(completion) => {
            if verbose {
                if let Some(ref primary_err) = completion.primary_error {
                    debug!(
                        "Version bump: primary provider ({}) failed: {}. Used {}.",
                        primary_err.provider(),
                        primary_err.summary(),
                        completion.provider
                    );
                }
            }
            completion.output
        }
        Err(e) => {
            warn!("LLM version bump failed: {}. Using algorithmic bump.", e.summary());
            return (algorithmic_bump, None);
        }
    };

    match parse_version_bump_response(&response) {
        Some((bump, reasoning)) => {
            debug!("LLM version bump: {:?} — {}", bump, reasoning);
            (bump, Some(reasoning))
        }
        None => {
            warn!(
                "Could not parse LLM version bump response. Using algorithmic bump. Response: {}",
                response.chars().take(200).collect::<String>()
            );
            (algorithmic_bump, None)
        }
    }
}

/// Convenience: determine next version using LLM with full fallback.
pub async fn calculate_next_version_with_llm(
    input: &VersionBumpInput<'_>,
    llm: &mut LlmRouter,
    verbose: bool,
) -> (Version, Option<String>) {
    let (bump, reasoning) = determine_version_with_llm(input, llm, verbose).await;
    let version = apply_bump_to_version(input.previous_version, bump);
    (version, reasoning)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_valid_minor_response() {
        let response = r#"{"bump_type": "minor", "reasoning": "New feature added"}"#;
        let (bump, reasoning) = parse_version_bump_response(response).unwrap();
        assert_eq!(bump, BumpType::Minor);
        assert_eq!(reasoning, "New feature added");
    }

    #[test]
    fn test_parse_valid_major_response() {
        let response = r#"{"bump_type": "major", "reasoning": "Breaking API change"}"#;
        let (bump, reasoning) = parse_version_bump_response(response).unwrap();
        assert_eq!(bump, BumpType::Major);
        assert_eq!(reasoning, "Breaking API change");
    }

    #[test]
    fn test_parse_valid_patch_response() {
        let response = r#"{"bump_type": "patch", "reasoning": "Bug fix"}"#;
        let (bump, _) = parse_version_bump_response(response).unwrap();
        assert_eq!(bump, BumpType::Patch);
    }

    #[test]
    fn test_parse_markdown_wrapped_response() {
        let response = "Here's the analysis:\n```json\n{\"bump_type\": \"minor\", \"reasoning\": \"Added new endpoint\"}\n```\n";
        let (bump, _) = parse_version_bump_response(response).unwrap();
        assert_eq!(bump, BumpType::Minor);
    }

    #[test]
    fn test_parse_bare_code_block() {
        let response = "```\n{\"bump_type\": \"patch\", \"reasoning\": \"Fix\"}\n```";
        let (bump, _) = parse_version_bump_response(response).unwrap();
        assert_eq!(bump, BumpType::Patch);
    }

    #[test]
    fn test_parse_with_surrounding_text() {
        let response = "Based on my analysis: {\"bump_type\": \"major\", \"reasoning\": \"Breaking change\"} Hope this helps!";
        let (bump, _) = parse_version_bump_response(response).unwrap();
        assert_eq!(bump, BumpType::Major);
    }

    #[test]
    fn test_parse_invalid_bump_type() {
        let response = r#"{"bump_type": "huge", "reasoning": "Big change"}"#;
        assert!(parse_version_bump_response(response).is_none());
    }

    #[test]
    fn test_parse_invalid_json() {
        let response = "not json at all";
        assert!(parse_version_bump_response(response).is_none());
    }

    #[test]
    fn test_parse_missing_fields() {
        let response = r#"{"bump_type": "minor"}"#;
        assert!(parse_version_bump_response(response).is_none());
    }

    #[test]
    fn test_parse_case_insensitive_bump_type() {
        let response = r#"{"bump_type": "MINOR", "reasoning": "test"}"#;
        let (bump, _) = parse_version_bump_response(response).unwrap();
        assert_eq!(bump, BumpType::Minor);
    }

    #[test]
    fn test_build_prompt_with_previous_version() {
        use chrono::Utc;
        use crate::git::CommitType;

        let commits = vec![ParsedCommit {
            hash: "abc123".to_string(),
            message: "feat: add auth".to_string(),
            commit_type: Some(CommitType::Feat),
            scope: None,
            breaking: false,
            timestamp: Utc::now(),
        }];

        let input = VersionBumpInput {
            commits: &commits,
            pull_requests: &[],
            previous_version: Some(&Version::new(1, 2, 3)),
            repository_name: "test-repo",
        };

        let prompt = build_version_bump_prompt(&input).unwrap();
        assert!(prompt.contains("test-repo"));
        assert!(prompt.contains("1.2.3"));
        assert!(prompt.contains("add auth"));
        assert!(prompt.contains("major|minor|patch"));
    }

    #[test]
    fn test_build_prompt_initial_release() {
        let input = VersionBumpInput {
            commits: &[],
            pull_requests: &[],
            previous_version: None,
            repository_name: "new-project",
        };

        let prompt = build_version_bump_prompt(&input).unwrap();
        assert!(prompt.contains("no previous version"));
        assert!(prompt.contains("new-project"));
    }
}
