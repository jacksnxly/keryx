//! Split analysis for automatic commit splitting.
//!
//! Detects when changes span multiple logical concerns and groups files
//! into separate atomic commits.

use std::collections::HashSet;

use serde::Deserialize;
use tracing::{debug, warn};

use crate::commit::diff::DiffSummary;
use crate::llm::extract_json;
use crate::llm::router::{LlmError, LlmRouter};

/// Minimum number of changed files before split analysis is attempted.
pub const SPLIT_ANALYSIS_THRESHOLD: usize = 4;

/// A group of files that belong to a single logical commit.
#[derive(Debug, Clone, Deserialize)]
pub struct CommitGroup {
    /// Short description for display (NOT the commit message).
    pub label: String,
    /// File paths belonging to this group.
    pub files: Vec<String>,
}

/// Result of split analysis: an ordered list of commit groups.
#[derive(Debug, Clone, Deserialize)]
pub struct SplitAnalysis {
    /// Ordered groups: foundational changes first.
    pub groups: Vec<CommitGroup>,
}

/// Build the prompt for split analysis.
///
/// Uses ONLY file paths and status (no full diff) to keep the analysis
/// lightweight — typically under 2K tokens even for 50+ files.
pub fn build_split_analysis_prompt(diff: &DiffSummary, branch_name: &str) -> String {
    let file_count = diff.changed_files.len();

    let files_section: String = diff
        .changed_files
        .iter()
        .map(|f| format!("- {} ({})", f.path, f.status))
        .collect::<Vec<_>>()
        .join("\n");

    format!(
        r#"You are analyzing a set of file changes to determine if they should be split into multiple atomic commits.

## Changed Files ({file_count} files, {additions} additions, {deletions} deletions)
{files_section}

## Branch Context
Branch: {branch_name}

## Rules
1. Files that are part of the same feature/fix/refactor → same group
2. Test files go with the code they test
3. Unrelated changes should be separate groups
4. Order groups by dependency: foundational changes first
5. Every file must appear in exactly one group
6. If unsure whether to split, prefer fewer groups
7. Each group label should be a short description (3-8 words), NOT a commit message

Respond with ONLY a JSON object (no markdown, no explanation):
{{"groups": [{{"label": "short description", "files": ["path/to/file.rs"]}}]}}"#,
        additions = diff.additions,
        deletions = diff.deletions,
    )
}

/// Analyze whether the diff should be split into multiple commits.
///
/// Calls the LLM with a lightweight prompt (file paths only, no diff content).
/// Returns `Ok(Some(analysis))` if splitting is recommended (2+ groups),
/// `Ok(None)` if a single commit is sufficient, or propagates LLM errors.
///
/// Parse/validation failures return `Ok(None)` — the caller falls back to
/// a single commit.
pub async fn analyze_split(
    diff: &DiffSummary,
    branch_name: &str,
    llm: &mut LlmRouter,
    verbose: bool,
) -> Result<Option<SplitAnalysis>, LlmError> {
    let prompt = build_split_analysis_prompt(diff, branch_name);

    if verbose {
        debug!("Split analysis prompt length: {} chars", prompt.len());
    }

    let completion = llm.generate_raw(&prompt).await?;

    let json_str = extract_json(&completion.output);
    let analysis: SplitAnalysis = match serde_json::from_str(&json_str) {
        Ok(a) => a,
        Err(e) => {
            warn!("Failed to parse split analysis JSON: {}", e);
            eprintln!(
                "\x1b[33m⚠ Split analysis response could not be parsed, falling back to single commit\x1b[0m"
            );
            if verbose {
                debug!("Raw response: {}", &completion.output);
            }
            return Ok(None);
        }
    };

    // Single group means no split needed
    if analysis.groups.len() <= 1 {
        return Ok(None);
    }

    // Validate the analysis
    let changed_files: Vec<&str> = diff
        .changed_files
        .iter()
        .map(|f| f.path.as_str())
        .collect();

    if let Some(error) = validate_split(&analysis, &changed_files) {
        warn!("Split analysis validation failed: {}", error);
        eprintln!(
            "\x1b[33m⚠ Split analysis failed validation, falling back to single commit\x1b[0m"
        );
        if verbose {
            eprintln!("  Details: {}", error);
        }
        return Ok(None);
    }

    Ok(Some(analysis))
}

/// Validate that a split analysis is consistent with the actual changed files.
///
/// Checks:
/// - No orphaned files (files in the diff but not in any group)
/// - No duplicate files (files appearing in multiple groups)
/// - No unknown files (files in groups but not in the diff)
///
/// Returns an error message if validation fails, or `None` if valid.
pub fn validate_split(analysis: &SplitAnalysis, changed_files: &[&str]) -> Option<String> {
    let mut seen: HashSet<&str> = HashSet::new();

    for group in &analysis.groups {
        for file in &group.files {
            // Check for unknown files
            if !changed_files.contains(&file.as_str()) {
                return Some(format!("Unknown file in group '{}': {}", group.label, file));
            }

            // Check for duplicates
            if !seen.insert(file.as_str()) {
                return Some(format!("Duplicate file across groups: {}", file));
            }
        }
    }

    // Check for orphaned files
    for file in changed_files {
        if !seen.contains(file) {
            return Some(format!("File not assigned to any group: {}", file));
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::commit::diff::{ChangedFile, DiffSummary, FileStatus};

    fn make_diff(files: &[(&str, FileStatus)]) -> DiffSummary {
        DiffSummary {
            diff_text: String::new(),
            changed_files: files
                .iter()
                .map(|(path, status)| ChangedFile {
                    path: path.to_string(),
                    status: status.clone(),
                })
                .collect(),
            truncated: false,
            additions: 50,
            deletions: 10,
        }
    }

    fn make_analysis(groups: Vec<(&str, Vec<&str>)>) -> SplitAnalysis {
        SplitAnalysis {
            groups: groups
                .into_iter()
                .map(|(label, files)| CommitGroup {
                    label: label.to_string(),
                    files: files.into_iter().map(String::from).collect(),
                })
                .collect(),
        }
    }

    // --- validate_split tests ---

    #[test]
    fn test_validate_split_valid() {
        let analysis = make_analysis(vec![
            ("Group A", vec!["src/a.rs", "src/b.rs"]),
            ("Group B", vec!["src/c.rs"]),
        ]);
        let changed = vec!["src/a.rs", "src/b.rs", "src/c.rs"];
        assert_eq!(validate_split(&analysis, &changed), None);
    }

    #[test]
    fn test_validate_split_orphaned_file() {
        let analysis = make_analysis(vec![
            ("Group A", vec!["src/a.rs"]),
        ]);
        let changed = vec!["src/a.rs", "src/b.rs"];
        let err = validate_split(&analysis, &changed).unwrap();
        assert!(err.contains("src/b.rs"));
        assert!(err.contains("not assigned"));
    }

    #[test]
    fn test_validate_split_duplicate_file() {
        let analysis = make_analysis(vec![
            ("Group A", vec!["src/a.rs"]),
            ("Group B", vec!["src/a.rs", "src/b.rs"]),
        ]);
        let changed = vec!["src/a.rs", "src/b.rs"];
        let err = validate_split(&analysis, &changed).unwrap();
        assert!(err.contains("Duplicate"));
        assert!(err.contains("src/a.rs"));
    }

    #[test]
    fn test_validate_split_unknown_file() {
        let analysis = make_analysis(vec![
            ("Group A", vec!["src/a.rs", "src/unknown.rs"]),
        ]);
        let changed = vec!["src/a.rs"];
        let err = validate_split(&analysis, &changed).unwrap();
        assert!(err.contains("Unknown"));
        assert!(err.contains("src/unknown.rs"));
    }

    // --- prompt tests ---

    #[test]
    fn test_prompt_contains_all_file_paths() {
        let diff = make_diff(&[
            ("src/commit/analysis.rs", FileStatus::Added),
            ("src/commit/diff.rs", FileStatus::Modified),
            ("src/main.rs", FileStatus::Modified),
            ("tests/analysis_test.rs", FileStatus::Added),
        ]);
        let prompt = build_split_analysis_prompt(&diff, "feat/commit-splitting");

        assert!(prompt.contains("src/commit/analysis.rs"));
        assert!(prompt.contains("src/commit/diff.rs"));
        assert!(prompt.contains("src/main.rs"));
        assert!(prompt.contains("tests/analysis_test.rs"));
        assert!(prompt.contains("feat/commit-splitting"));
        assert!(prompt.contains("4 files"));
    }

    #[test]
    fn test_prompt_contains_file_statuses() {
        let diff = make_diff(&[
            ("src/new.rs", FileStatus::Added),
            ("src/old.rs", FileStatus::Deleted),
            ("src/changed.rs", FileStatus::Modified),
            ("src/moved.rs", FileStatus::Renamed),
        ]);
        let prompt = build_split_analysis_prompt(&diff, "main");

        assert!(prompt.contains("Added"));
        assert!(prompt.contains("Deleted"));
        assert!(prompt.contains("Modified"));
        assert!(prompt.contains("Renamed"));
    }

    #[test]
    fn test_prompt_contains_addition_deletion_counts() {
        let diff = make_diff(&[
            ("src/a.rs", FileStatus::Modified),
            ("src/b.rs", FileStatus::Modified),
            ("src/c.rs", FileStatus::Modified),
            ("src/d.rs", FileStatus::Modified),
        ]);
        let prompt = build_split_analysis_prompt(&diff, "main");

        assert!(prompt.contains("50 additions"));
        assert!(prompt.contains("10 deletions"));
    }

    // --- JSON round-trip test ---

    #[test]
    fn test_split_analysis_json_roundtrip() {
        let json = r#"{"groups": [{"label": "Add analysis module", "files": ["src/commit/analysis.rs", "tests/analysis_test.rs"]}, {"label": "Update CLI", "files": ["src/main.rs"]}]}"#;
        let analysis: SplitAnalysis = serde_json::from_str(json).unwrap();
        assert_eq!(analysis.groups.len(), 2);
        assert_eq!(analysis.groups[0].label, "Add analysis module");
        assert_eq!(analysis.groups[0].files, vec!["src/commit/analysis.rs", "tests/analysis_test.rs"]);
        assert_eq!(analysis.groups[1].label, "Update CLI");
        assert_eq!(analysis.groups[1].files, vec!["src/main.rs"]);
    }

    #[test]
    fn test_split_analysis_single_group_json() {
        let json = r#"{"groups": [{"label": "All changes", "files": ["src/a.rs", "src/b.rs"]}]}"#;
        let analysis: SplitAnalysis = serde_json::from_str(json).unwrap();
        assert_eq!(analysis.groups.len(), 1);
    }
}
