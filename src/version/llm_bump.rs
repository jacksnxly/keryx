//! LLM-based version bump determination.
//!
//! Semantically analyzes commits and PRs to determine the correct semver bump.
//! Falls back to the algorithmic approach on any failure.

use semver::Version;
use serde::de::{self, Deserializer};
use serde::Deserialize;
use tracing::{debug, warn};

use crate::git::ParsedCommit;
use crate::github::PullRequest;
use crate::llm::extract_json;
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

/// Typed bump type for LLM deserialization with case-insensitive support.
///
/// Kept private to this module to avoid coupling `BumpType` to serde.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RawBumpType {
    Major,
    Minor,
    Patch,
}

impl<'de> Deserialize<'de> for RawBumpType {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let s = String::deserialize(deserializer)?;
        match s.to_lowercase().as_str() {
            "major" => Ok(RawBumpType::Major),
            "minor" => Ok(RawBumpType::Minor),
            "patch" => Ok(RawBumpType::Patch),
            _ => Err(de::Error::unknown_variant(&s, &["major", "minor", "patch"])),
        }
    }
}

impl From<RawBumpType> for BumpType {
    fn from(raw: RawBumpType) -> Self {
        match raw {
            RawBumpType::Major => BumpType::Major,
            RawBumpType::Minor => BumpType::Minor,
            RawBumpType::Patch => BumpType::Patch,
        }
    }
}

/// Response from the LLM for version bump.
#[derive(Deserialize)]
struct VersionBumpResponse {
    bump_type: RawBumpType,
    reasoning: Option<String>,
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
                    let truncated = if b.len() > 500 {
                        let mut end = 500;
                        while end > 0 && !b.is_char_boundary(end) {
                            end -= 1;
                        }
                        &b[..end]
                    } else {
                        b
                    };
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

    let sanitized_repo = sanitize_for_prompt(input.repository_name);

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
        repo = sanitized_repo,
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
/// Invalid bump types are rejected at deserialization time.
fn parse_version_bump_response(response: &str) -> Option<(BumpType, String)> {
    // Try to extract JSON from markdown wrapping
    let json_str = extract_json(response);

    let parsed: VersionBumpResponse = match serde_json::from_str(&json_str) {
        Ok(v) => v,
        Err(e) => {
            debug!("Failed to parse version bump JSON: {}", e);
            return None;
        }
    };

    let bump: BumpType = parsed.bump_type.into();
    Some((bump, parsed.reasoning.unwrap_or_default()))
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
            eprintln!(
                "\x1b[33m⚠ LLM version bump failed (prompt error), using algorithmic bump\x1b[0m"
            );
            eprintln!("  Reason: {}", e);
            return (algorithmic_bump, None);
        }
    };

    let response = match llm.generate_raw(&prompt).await {
        Ok(completion) => {
            if let Some(ref primary_err) = completion.primary_error {
                warn!(
                    "Version bump: primary provider ({}) failed: {}. Used {}.",
                    primary_err.provider(),
                    primary_err.summary(),
                    completion.provider
                );
                eprintln!();
                eprintln!(
                    "\x1b[33m⚠ {} failed, using {} for version bump\x1b[0m",
                    primary_err.provider(),
                    completion.provider
                );
                if verbose {
                    eprintln!("  Details: {}", primary_err.detail());
                } else {
                    eprintln!("  Reason: {}", primary_err.summary());
                }
                eprintln!();
            }
            completion.output
        }
        Err(e) => {
            warn!("LLM version bump failed: {}. Using algorithmic bump.", e.summary());
            eprintln!();
            eprintln!(
                "\x1b[33m⚠ LLM version bump failed, using algorithmic bump\x1b[0m"
            );
            eprintln!("  Reason: {}", e.summary());
            eprintln!();
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
            eprintln!();
            eprintln!(
                "\x1b[33m⚠ Could not parse LLM version bump response, using algorithmic bump\x1b[0m"
            );
            eprintln!();
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
    fn test_parse_missing_reasoning_succeeds() {
        let response = r#"{"bump_type": "minor"}"#;
        let (bump, reasoning) = parse_version_bump_response(response).unwrap();
        assert_eq!(bump, BumpType::Minor);
        assert_eq!(reasoning, "");
    }

    #[test]
    fn test_parse_case_insensitive_uppercase() {
        let response = r#"{"bump_type": "MINOR", "reasoning": "test"}"#;
        let (bump, _) = parse_version_bump_response(response).unwrap();
        assert_eq!(bump, BumpType::Minor);
    }

    #[test]
    fn test_parse_case_insensitive_mixed_case() {
        let response = r#"{"bump_type": "Major", "reasoning": "test"}"#;
        let (bump, _) = parse_version_bump_response(response).unwrap();
        assert_eq!(bump, BumpType::Major);
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
    fn test_build_prompt_pr_body_multibyte_utf8_truncation() {
        // KRX-089: PR body truncation must respect UTF-8 character boundaries.
        // The emoji 🎉 is 4 bytes (0xF0 0x9F 0x8E 0x89).
        // Place it so byte 500 falls mid-character.
        let prefix = "a".repeat(498); // 498 ASCII bytes
        let body = format!("{}🎉🎉", prefix); // 498 + 4 + 4 = 506 bytes

        let pr = PullRequest {
            number: std::num::NonZeroU64::new(1).unwrap(),
            title: "Test PR".to_string(),
            body: Some(body),
            merged_at: None,
            labels: vec![],
        };

        let input = VersionBumpInput {
            commits: &[],
            pull_requests: &[pr],
            previous_version: None,
            repository_name: "test-repo",
        };

        // This should NOT panic - the old code panicked on multi-byte boundary
        let result = build_version_bump_prompt(&input);
        assert!(result.is_ok());

        let prompt = result.unwrap();
        // The prompt should be valid UTF-8 (guaranteed by String type) and contain PR info
        assert!(prompt.contains("Test PR"));

        // Verify the body snippet in the prompt is bounded to <= 500 bytes.
        // The prompt contains the sanitized PR line: "PR #1: Test PR - <body_snippet>"
        // Extract the body portion after "Test PR - "
        if let Some(pr_line_start) = prompt.find("PR #1: Test PR - ") {
            let body_start = pr_line_start + "PR #1: Test PR - ".len();
            // The body snippet goes to end of line
            let body_end = prompt[body_start..]
                .find('\n')
                .map(|i| body_start + i)
                .unwrap_or(prompt.len());
            let body_in_prompt = &prompt[body_start..body_end];
            assert!(
                body_in_prompt.len() <= 500,
                "Body snippet in prompt should be <= 500 bytes, was {}",
                body_in_prompt.len()
            );
        }
    }

    #[test]
    fn test_build_prompt_pr_body_cjk_truncation() {
        // CJK characters are 3 bytes each in UTF-8.
        // Fill so byte 500 falls mid-character.
        let prefix = "a".repeat(499); // 499 ASCII bytes
        // Next char '中' is 3 bytes: byte 499..502, so byte 500 is mid-char
        let body = format!("{}中文测试", prefix);

        let pr = PullRequest {
            number: std::num::NonZeroU64::new(2).unwrap(),
            title: "CJK test".to_string(),
            body: Some(body),
            merged_at: None,
            labels: vec![],
        };

        let input = VersionBumpInput {
            commits: &[],
            pull_requests: &[pr],
            previous_version: None,
            repository_name: "test-repo",
        };

        // Should not panic
        let result = build_version_bump_prompt(&input);
        assert!(result.is_ok());
    }

    #[test]
    fn test_build_prompt_with_populated_prs() {
        use chrono::Utc;
        use crate::git::CommitType;

        let commits = vec![ParsedCommit {
            hash: "abc123".to_string(),
            message: "feat: add dashboard".to_string(),
            commit_type: Some(CommitType::Feat),
            scope: None,
            breaking: false,
            timestamp: Utc::now(),
        }];

        let prs = vec![
            PullRequest {
                number: std::num::NonZeroU64::new(42).unwrap(),
                title: "Add user dashboard".to_string(),
                body: Some("Implements the new dashboard with charts and filters.".to_string()),
                merged_at: None,
                labels: vec![],
            },
            PullRequest {
                number: std::num::NonZeroU64::new(43).unwrap(),
                title: "Fix login regression".to_string(),
                body: None,
                merged_at: None,
                labels: vec![],
            },
        ];

        let input = VersionBumpInput {
            commits: &commits,
            pull_requests: &prs,
            previous_version: Some(&Version::new(2, 0, 0)),
            repository_name: "my-app",
        };

        let prompt = build_version_bump_prompt(&input).unwrap();
        assert!(prompt.contains("my-app"));
        assert!(prompt.contains("2.0.0"));
        assert!(prompt.contains("PR #42"));
        assert!(prompt.contains("Add user dashboard"));
        assert!(prompt.contains("charts and filters"));
        assert!(prompt.contains("PR #43"));
        assert!(prompt.contains("Fix login regression"));
        assert!(prompt.contains("add dashboard"));
        // Should not contain "(none)" since PRs are present
        assert!(!prompt.contains("(none)"));
    }

    #[test]
    fn test_build_prompt_long_body_truncated_to_500_bytes() {
        let long_body = "x".repeat(1000);

        let pr = PullRequest {
            number: std::num::NonZeroU64::new(10).unwrap(),
            title: "Big PR".to_string(),
            body: Some(long_body),
            merged_at: None,
            labels: vec![],
        };

        let input = VersionBumpInput {
            commits: &[],
            pull_requests: &[pr],
            previous_version: Some(&Version::new(1, 0, 0)),
            repository_name: "test",
        };

        let prompt = build_version_bump_prompt(&input).unwrap();
        assert!(prompt.contains("Big PR"));

        // The body_snippet passed to the prompt should be at most 500 chars of 'x'
        // Count consecutive 'x' chars in the prompt to verify truncation
        let max_x_run = prompt
            .split(|c: char| c != 'x')
            .map(|s| s.len())
            .max()
            .unwrap_or(0);
        assert!(
            max_x_run <= 500,
            "Body should be truncated to <= 500 bytes, longest x-run was {}",
            max_x_run
        );
    }

    // ============================================
    // extract_json edge cases
    // ============================================

    /// Empty code block should return empty string (no valid JSON).
    #[test]
    fn test_extract_json_empty_code_block() {
        let response = "```json\n```";
        let result = extract_json(response);
        // Empty string is returned from the code block extraction
        assert_eq!(result, "");
    }

    /// Multiple JSON objects - the shared extract_json uses proper JSON parsing
    /// and correctly extracts the first valid object.
    #[test]
    fn test_extract_json_multiple_objects() {
        let response = r#"{"bump_type": "minor", "reasoning": "feat"} {"bump_type": "patch", "reasoning": "fix"}"#;
        let result = extract_json(response);
        assert!(result.contains("bump_type"));
        // The improved extractor finds the first valid JSON object
        let (bump, _) = parse_version_bump_response(response).unwrap();
        assert_eq!(bump, BumpType::Minor);
    }

    /// Response with only closing braces - should fall through to returning trimmed input.
    #[test]
    fn test_extract_json_only_closing_braces() {
        let response = "}}";
        let result = extract_json(response);
        // No opening brace found first, so trimmed input is returned as-is
        assert_eq!(result, "}}");
    }

    /// Response with mismatched braces - should still extract something.
    #[test]
    fn test_extract_json_no_json_present() {
        let response = "This is just plain text with no JSON";
        let result = extract_json(response);
        assert_eq!(result, response);
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
