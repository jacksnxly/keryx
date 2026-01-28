//! Codebase scanner for gathering verification evidence.

use std::collections::HashSet;
use std::path::Path;
use std::process::Command;

use regex_lite::Regex;
use tracing::{debug, warn};

use crate::changelog::ChangelogEntry;
use crate::error::VerificationError;
use super::evidence::{
    CountCheck, EntryEvidence, KeyFileContent, KeywordMatch,
    StubIndicator, VerificationEvidence,
};

/// Outcome of a ripgrep command execution.
enum RgOutcome {
    /// Command succeeded with output.
    Success(String),
    /// No matches found (exit code 1) - this is normal, not an error.
    NoMatch,
}

/// Execute a ripgrep command and categorize the outcome.
///
/// Handles the common three-way result pattern:
/// - Success with output → `Ok(RgOutcome::Success(stdout))`
/// - Exit code 1 (no matches) → `Ok(RgOutcome::NoMatch)`
/// - Other exit codes or errors → `Err(VerificationError)`
fn run_rg(cmd: &mut Command) -> Result<RgOutcome, VerificationError> {
    match cmd.output() {
        Ok(out) if out.status.success() => {
            Ok(RgOutcome::Success(String::from_utf8_lossy(&out.stdout).to_string()))
        }
        Ok(out) if out.status.code() == Some(1) => {
            // Exit code 1 means no matches found - this is normal
            Ok(RgOutcome::NoMatch)
        }
        Ok(out) => {
            let stderr = String::from_utf8_lossy(&out.stderr).trim().to_string();
            Err(VerificationError::RipgrepFailed {
                exit_code: out.status.code(),
                stderr,
            })
        }
        Err(e) => {
            if e.kind() == std::io::ErrorKind::NotFound {
                Err(VerificationError::RipgrepNotInstalled)
            } else {
                Err(VerificationError::ScannerIoError(e))
            }
        }
    }
}

/// Execute a ripgrep command, logging warnings on failure and returning a default.
///
/// Use this for "best-effort" calls where failure shouldn't abort the operation.
/// Returns `Some(stdout)` on success, `None` on no-match or error (with warning logged).
fn run_rg_or_warn(cmd: &mut Command, context: &str) -> Option<String> {
    match run_rg(cmd) {
        Ok(RgOutcome::Success(stdout)) => Some(stdout),
        Ok(RgOutcome::NoMatch) => None,
        Err(e) => {
            warn!("rg failed for {}: {}", context, e);
            None
        }
    }
}

/// Common ripgrep arguments to exclude build/dependency directories.
const RG_EXCLUDE_PATTERNS: &[&str] = &[
    "-g", "!target",
    "-g", "!node_modules",
    "-g", "!dist",
    "-g", "!build",
    "-g", "!.git",
];

/// Ripgrep type definition for common source code files.
const RG_CODE_TYPE: &[&str] = &[
    "--type-add", "code:*.{rs,ts,tsx,js,jsx,py,go,java,c,cpp,h,hpp}",
    "--type", "code",
];

/// Patterns that indicate incomplete/stub code.
const STUB_PATTERNS: &[&str] = &[
    "TODO",
    "FIXME",
    "XXX",
    "HACK",
    "unimplemented!",
    "todo!",
    "panic!(\"not implemented",
    "panic!(\"unimplemented",
    "// stub",
    "// placeholder",
    "NotImplemented",
    "raise NotImplementedError",
];

/// Common words to exclude from keyword extraction.
const STOP_WORDS: &[&str] = &[
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "as", "is", "was", "are", "were", "been",
    "be", "have", "has", "had", "do", "does", "did", "will", "would",
    "could", "should", "may", "might", "must", "shall", "can", "need",
    "new", "add", "added", "change", "changed", "fix", "fixed", "update",
    "updated", "remove", "removed", "improve", "improved", "support",
    "supported", "feature", "features", "now", "using", "use", "based",
    "all", "any", "some", "more", "less", "better", "best", "first",
    "initial", "release", "version", "multiple", "various", "several",
];

/// Gather verification evidence for changelog entries.
///
/// This function scans the codebase to verify claims made in the changelog entries.
/// It extracts keywords, searches for them in the code, checks for stub indicators,
/// and verifies numeric claims.
pub fn gather_verification_evidence(
    entries: &[ChangelogEntry],
    repo_path: &Path,
) -> VerificationEvidence {
    let mut evidence = VerificationEvidence::empty();

    // Gather project structure
    let (structure, source) = get_project_structure(repo_path);
    evidence.project_structure = structure;
    evidence.project_structure_source = source;

    // Gather key files
    evidence.key_files = gather_key_files(repo_path);

    // Process each entry
    for entry in entries {
        let entry_evidence = analyze_entry(entry, repo_path);
        evidence.entries.push(entry_evidence);
    }

    evidence
}

/// Analyze a single changelog entry against the codebase.
fn analyze_entry(entry: &ChangelogEntry, repo_path: &Path) -> EntryEvidence {
    let description = &entry.description;
    let category = entry.category.clone();

    // Extract keywords from the description
    let keywords = extract_keywords(description);
    debug!("Extracted keywords from '{}': {:?}", description, keywords);

    // Search for each keyword in the codebase
    let mut keyword_matches = Vec::new();
    let mut all_stub_indicators = Vec::new();

    for keyword in &keywords {
        match search_keyword(keyword, repo_path) {
            Ok(Some(match_result)) => {
                // Check for stub indicators near the matches
                let (stubs, stub_detection_ok) = match find_stub_indicators_near_keyword(keyword, repo_path) {
                    Ok(s) => (s, true),
                    Err(e) => {
                        warn!(
                            "Stub detection failed for keyword '{}': {}. Conservatively marking as incomplete.",
                            keyword, e
                        );
                        (Vec::new(), false)
                    }
                };
                // Mark incomplete if stubs found, occurrence counting failed, OR stub detection failed
                let appears_complete = stub_detection_ok && stubs.is_empty() && match_result.count.is_some();

                all_stub_indicators.extend(stubs);
                keyword_matches.push(KeywordMatch {
                    keyword: keyword.clone(),
                    files_found: match_result.files,
                    occurrence_count: match_result.count,
                    sample_lines: match_result.samples,
                    appears_complete,
                });
            }
            Ok(None) => {
                // No matches found - this is normal, skip this keyword
            }
            Err(e) => {
                warn!("Error searching for keyword '{}': {}", keyword, e);
            }
        }
    }

    // Check for numeric claims
    let count_checks = verify_numeric_claims(description, repo_path);

    // Deduplicate stub indicators by (file, line) - same TODO shouldn't count multiple times
    // even if found via different keywords
    let mut seen_stubs = HashSet::new();
    let unique_stub_indicators: Vec<_> = all_stub_indicators
        .into_iter()
        .filter(|s| seen_stubs.insert((s.file.clone(), s.line)))
        .collect();

    // Confidence is computed automatically by EntryEvidence
    EntryEvidence::new(
        description.clone(),
        category,
        keyword_matches,
        count_checks,
        unique_stub_indicators,
    )
}

/// Extract meaningful keywords from a description.
fn extract_keywords(description: &str) -> Vec<String> {
    let mut keywords = HashSet::new();

    // Regex for potential keywords (CamelCase, snake_case, or significant words)
    let word_re = Regex::new(r"[A-Z][a-z]+(?:[A-Z][a-z]+)*|[a-z]+(?:_[a-z]+)+|[A-Za-z]{4,}")
        .expect("Invalid regex");

    for cap in word_re.find_iter(description) {
        let word = cap.as_str().to_lowercase();

        // Skip stop words
        if STOP_WORDS.contains(&word.as_str()) {
            continue;
        }

        // Skip very short or very long words
        if word.len() < 4 || word.len() > 30 {
            continue;
        }

        keywords.insert(word);
    }

    // Also extract quoted terms (but skip CLI flags like --no-verify)
    let quote_re = Regex::new(r#"["'`]([^"'`]+)["'`]"#).expect("Invalid regex");
    for cap in quote_re.captures_iter(description) {
        if let Some(quoted) = cap.get(1) {
            let term = quoted.as_str();
            // Skip CLI flags (start with - or --)
            if term.starts_with('-') {
                continue;
            }
            let term = term.to_lowercase();
            if term.len() >= 3 && term.len() <= 50 {
                keywords.insert(term);
            }
        }
    }

    // Extract technology/product names (capitalized words)
    let tech_re = Regex::new(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)?)\b")
        .expect("Invalid regex");
    for cap in tech_re.captures_iter(description) {
        if let Some(tech) = cap.get(1) {
            let term = tech.as_str();
            // Skip generic words
            if !["Added", "Changed", "Fixed", "Removed", "Security", "The", "This", "With"]
                .contains(&term)
            {
                keywords.insert(term.to_lowercase());
            }
        }
    }

    keywords.into_iter().collect()
}

/// Result of searching for a keyword.
struct SearchResult {
    files: Vec<String>,
    /// Total occurrence count, or `None` if counting failed.
    count: Option<usize>,
    /// Sample lines, or `None` if sampling failed.
    samples: Option<Vec<String>>,
}

/// Build a ripgrep command with standard arguments for keyword searching.
///
/// Sets up `--ignore-case --fixed-strings`, code file type filters, and
/// directory exclusion patterns. Callers can add additional arguments
/// before executing.
fn build_rg_keyword_command(keyword: &str, repo_path: &Path) -> Command {
    let mut cmd = Command::new("rg");
    cmd.args(["--ignore-case", "--fixed-strings"]);
    cmd.args(RG_CODE_TYPE);
    cmd.args(RG_EXCLUDE_PATTERNS);
    cmd.arg(keyword);
    cmd.current_dir(repo_path);
    cmd
}

/// Search for a keyword in the codebase using ripgrep.
///
/// Returns:
/// - `Ok(Some(result))` - Matches found
/// - `Ok(None)` - No matches found (normal, expected)
/// - `Err(error)` - Error occurred during search
fn search_keyword(keyword: &str, repo_path: &Path) -> Result<Option<SearchResult>, VerificationError> {
    // Use ripgrep for fast searching
    // Use --fixed-strings to treat keyword as literal text, not regex
    let files: Vec<String> = match run_rg(
        build_rg_keyword_command(keyword, repo_path).arg("--files-with-matches"),
    )? {
        RgOutcome::Success(stdout) => stdout.lines().take(10).map(String::from).collect(),
        RgOutcome::NoMatch => return Ok(None),
    };

    if files.is_empty() {
        return Ok(None);
    }

    // Get sample lines with context (best-effort)
    let samples: Option<Vec<String>> = run_rg_or_warn(
        build_rg_keyword_command(keyword, repo_path).args(["--max-count", "3", "-C", "1"]),
        &format!("samples for keyword '{}'", keyword),
    )
    .map(|stdout| stdout.lines().take(15).map(String::from).collect());

    // Count total occurrences (best-effort)
    let count: Option<usize> = run_rg_or_warn(
        build_rg_keyword_command(keyword, repo_path).arg("--count-matches"),
        &format!("count for keyword '{}'", keyword),
    )
    .map(|stdout| {
        stdout
            .lines()
            .filter_map(|line| line.rsplit(':').next()?.parse::<usize>().ok())
            .sum()
    });

    Ok(Some(SearchResult {
        files,
        count,
        samples,
    }))
}

/// Find stub indicators near a keyword in the codebase.
///
/// Returns `Err` if ripgrep fails or is not found, so the caller can
/// conservatively treat the feature as incomplete rather than silently
/// marking it complete.
fn find_stub_indicators_near_keyword(keyword: &str, repo_path: &Path) -> Result<Vec<StubIndicator>, VerificationError> {
    let mut indicators = Vec::new();

    // First, find files containing the keyword (only in source code files)
    let mut cmd = Command::new("rg");
    cmd.args(["--ignore-case", "--fixed-strings", "--files-with-matches"]);
    cmd.args(RG_CODE_TYPE);
    cmd.args(RG_EXCLUDE_PATTERNS);
    cmd.arg(keyword);
    cmd.current_dir(repo_path);

    let files: Vec<String> = match run_rg(&mut cmd)? {
        RgOutcome::Success(stdout) => stdout.lines().take(5).map(String::from).collect(),
        RgOutcome::NoMatch => return Ok(indicators),
    };

    // Check each file for all stub patterns in a single rg call
    // Using -e flag for multiple patterns reduces subprocess count by 12x
    for file in &files {
        let mut cmd = Command::new("rg");
        cmd.args(["--fixed-strings", "--line-number", "--max-count", "36", "--json", "-C", "1"]);

        // Add each pattern with -e flag
        for pattern in STUB_PATTERNS {
            cmd.args(["-e", pattern]);
        }

        cmd.arg(file);
        cmd.current_dir(repo_path);

        match run_rg(&mut cmd)? {
            RgOutcome::Success(stdout) => {
                for line in stdout.lines() {
                    if let Some((line_num, context)) = parse_rg_json_match(line) {
                        // Determine which pattern matched by checking the context
                        let indicator = STUB_PATTERNS
                            .iter()
                            .find(|p| context.contains(*p))
                            .map(|p| p.to_string())
                            .unwrap_or_else(|| "stub".to_string());

                        indicators.push(StubIndicator {
                            file: file.clone(),
                            line: line_num,
                            indicator,
                            context,
                        });
                    }
                }
            }
            RgOutcome::NoMatch => {}
        }
    }

    Ok(indicators)
}

/// Parse a ripgrep JSON output line into line number and content.
fn parse_rg_json_match(line: &str) -> Option<(usize, String)> {
    let value: serde_json::Value = serde_json::from_str(line).ok()?;
    let kind = value.get("type")?.as_str()?;
    if kind != "match" {
        return None;
    }

    let data = value.get("data")?;
    let line_num = data.get("line_number")?.as_u64()? as usize;
    let text = data.get("lines")?.get("text")?.as_str()?;
    let context = text.trim_end_matches(['\n', '\r']).to_string();

    Some((line_num, context))
}

/// Verify numeric claims in a description.
fn verify_numeric_claims(description: &str, repo_path: &Path) -> Vec<CountCheck> {
    let mut checks = Vec::new();

    // Regex to find numeric claims like "8 templates", "6 languages", etc.
    // Anchors on start/whitespace to avoid matching hyphenated tokens like "UTF-8 handling".
    let num_re = Regex::new(r"(?:^|\s)(\d+)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)")
        .expect("Invalid regex");

    // Subjects that are not countable things (false positives)
    let non_countable = [
        "handling", "panic", "error", "errors", "issue", "issues",
        "byte", "bytes", "bit", "bits", "character", "characters",
        "pass", "mode", "way", "ways", "time", "times",
    ];

    for cap in num_re.captures_iter(description) {
        let count_str = cap.get(1).map(|m| m.as_str()).unwrap_or("0");
        let subject = cap.get(2).map(|m| m.as_str()).unwrap_or("");

        // Skip non-countable subjects
        let subject_lower = subject.to_lowercase();
        if non_countable.iter().any(|nc| subject_lower.starts_with(nc)) {
            continue;
        }

        let claimed_count: usize = count_str.parse().unwrap_or(0);
        if claimed_count == 0 || claimed_count > 1000 {
            continue; // Skip unreasonable counts
        }

        // Try to verify this count
        let (actual_count, source) = try_verify_count(subject, repo_path);

        checks.push(CountCheck {
            claimed_text: format!("{} {}", count_str, subject),
            claimed_count: Some(claimed_count),
            actual_count,
            source_location: source,
        });
    }

    checks
}

/// Try to verify a count claim by searching the codebase.
fn try_verify_count(subject: &str, repo_path: &Path) -> (Option<usize>, Option<String>) {
    let subject_lower = subject.to_lowercase();

    // Common patterns to count
    let count_patterns: &[(&str, &str, &str)] = &[
        // (subject keyword, file pattern, count pattern)
        ("template", "*.rs", r"(TEMPLATES|templates)\s*[=:]\s*\["),
        ("template", "*.ts", r"(TEMPLATES|templates)\s*[=:]\s*\["),
        ("language", "messages", ""),  // Count directories/files
        ("exchange", "*.rs", r"enum.*Exchange|Exchange\s*\{"),
        ("preset", "*.ts", r"(PRESETS|presets)\s*[=:]\s*\["),
        ("widget", "*.tsx", r"Widget|widget"),
    ];

    for (keyword, file_glob, pattern) in count_patterns {
        if subject_lower.contains(keyword) {
            if pattern.is_empty() {
                // Count files/directories
                let count = count_files_matching(repo_path, file_glob, keyword);
                if let Some(c) = count {
                    return (Some(c), Some(format!("files matching {}", file_glob)));
                }
            } else {
                // Search for array and count elements
                let result = search_and_count_array(repo_path, file_glob, pattern);
                if let Some((count, location)) = result {
                    return (Some(count), Some(location));
                }
            }
        }
    }

    (None, None)
}

/// Count files matching a pattern.
fn count_files_matching(repo_path: &Path, glob: &str, keyword: &str) -> Option<usize> {
    let output = Command::new("find")
        .args([
            ".",
            "-type", "f",
            "-name", glob,
            "-path", &format!("*{}*", keyword),
        ])
        .current_dir(repo_path)
        .output();

    match output {
        Ok(out) if out.status.success() => {
            let count = String::from_utf8_lossy(&out.stdout)
                .lines()
                .filter(|l| !l.is_empty())
                .count();
            if count > 0 {
                Some(count)
            } else {
                None
            }
        }
        Ok(out) => {
            let stderr = String::from_utf8_lossy(&out.stderr);
            warn!(
                "find command failed for glob '{}', keyword '{}': exit code {:?}, stderr: {}",
                glob,
                keyword,
                out.status.code(),
                stderr.trim()
            );
            None
        }
        Err(e) => {
            if e.kind() == std::io::ErrorKind::NotFound {
                warn!("find command not found - this should be available on Unix systems");
            } else {
                warn!(
                    "Failed to execute find for glob '{}', keyword '{}': {}",
                    glob, keyword, e
                );
            }
            None
        }
    }
}

/// Search for an array definition and count its elements.
fn search_and_count_array(
    repo_path: &Path,
    file_glob: &str,
    pattern: &str,
) -> Option<(usize, String)> {
    // Find files with the pattern
    let mut cmd = Command::new("rg");
    cmd.args(["--files-with-matches", "-g", file_glob]);
    cmd.args(RG_EXCLUDE_PATTERNS);
    cmd.arg(pattern);
    cmd.current_dir(repo_path);

    let files: Vec<String> = run_rg_or_warn(
        &mut cmd,
        &format!("array pattern '{}' in '{}'", pattern, file_glob),
    )?
    .lines()
    .map(String::from)
    .collect();

    for file in files {
        // Read the file and try to count array elements
        let file_path = repo_path.join(&file);
        match std::fs::read_to_string(&file_path) {
            Ok(content) => {
                // Simple heuristic: count items between [ and ]
                if let Some(count) = count_array_elements(&content, pattern) {
                    return Some((count, file));
                }
            }
            Err(e) => {
                if e.kind() == std::io::ErrorKind::NotFound {
                    debug!("File '{}' no longer exists for array counting: {}", file, e);
                } else {
                    warn!("Cannot read file '{}' for array counting: {}", file, e);
                }
            }
        }
    }

    None
}

/// Count elements in an array definition.
fn count_array_elements(content: &str, pattern: &str) -> Option<usize> {
    let re = Regex::new(pattern).ok()?;

    // Find the pattern
    let match_pos = re.find(content)?;

    // The pattern might include '[' or we need to find it after
    // First check if pattern ends with '['
    let matched_text = match_pos.as_str();
    let start = if matched_text.ends_with('[') {
        // Pattern includes '[', start counting from here
        match_pos.end() - 1
    } else {
        // Find the opening bracket after the match
        let after_match = &content[match_pos.end()..];
        let bracket_pos = after_match.find('[')?;
        match_pos.end() + bracket_pos
    };

    // Find matching closing bracket
    let mut depth = 0;
    let mut end = start;
    for (i, c) in content[start..].char_indices() {
        match c {
            '[' | '{' => depth += 1,
            ']' | '}' => {
                depth -= 1;
                if depth == 0 {
                    end = start + i;
                    break;
                }
            }
            _ => {}
        }
    }

    if end <= start {
        return None;
    }

    // Count top-level elements (simplified: count commas at depth 1 + 1)
    let array_content = &content[start + 1..end];
    let mut count = 0;
    let mut depth = 0;
    let mut last_was_comma = false;

    for c in array_content.chars() {
        match c {
            '[' | '{' | '(' => {
                depth += 1;
                last_was_comma = false;
            }
            ']' | '}' | ')' => {
                depth -= 1;
                last_was_comma = false;
            }
            ',' if depth == 0 => {
                count += 1;
                last_was_comma = true;
            }
            c if !c.is_whitespace() => {
                last_was_comma = false;
            }
            _ => {}
        }
    }

    // If we found any content, there's at least one element
    // But don't add 1 if the last thing was a trailing comma
    if !array_content.trim().is_empty() && !last_was_comma {
        count += 1;
    }

    Some(count)
}

/// Get project structure using tree command, with ls fallback.
///
/// Returns `(content, source)` where source is `"tree"`, `"ls"`, or `None` if
/// both commands failed.
fn get_project_structure(repo_path: &Path) -> (Option<String>, Option<String>) {
    let output = Command::new("tree")
        .args([
            "-L", "3",
            "-I", "target|node_modules|dist|build|.git|__pycache__",
            "--dirsfirst",
        ])
        .current_dir(repo_path)
        .output();

    match output {
        Ok(out) if out.status.success() => {
            let tree = String::from_utf8_lossy(&out.stdout);
            // Truncate if too long
            let truncated: String = tree.lines().take(50).collect::<Vec<_>>().join("\n");
            return (Some(truncated), Some("tree".to_string()));
        }
        Ok(out) => {
            debug!(
                "tree command failed (exit code {:?}), falling back to ls",
                out.status.code()
            );
        }
        Err(e) => {
            if e.kind() == std::io::ErrorKind::NotFound {
                debug!("tree command not found, falling back to ls");
            } else {
                debug!("tree command error: {}, falling back to ls", e);
            }
        }
    }

    // Fallback to ls
    let ls_output = Command::new("ls")
        .args(["-la"])
        .current_dir(repo_path)
        .output();

    match ls_output {
        Ok(ls_out) if ls_out.status.success() => {
            (Some(String::from_utf8_lossy(&ls_out.stdout).to_string()), Some("ls".to_string()))
        }
        Ok(ls_out) => {
            debug!(
                "ls command also failed (exit code {:?}), cannot get project structure",
                ls_out.status.code()
            );
            (None, None)
        }
        Err(e) => {
            debug!("ls command error: {}, cannot get project structure", e);
            (None, None)
        }
    }
}

/// Gather content of key project files.
fn gather_key_files(repo_path: &Path) -> Vec<KeyFileContent> {
    let key_files = [
        "Cargo.toml",
        "package.json",
        "pyproject.toml",
        "go.mod",
        "README.md",
    ];

    let mut contents = Vec::new();

    for file in &key_files {
        let path = repo_path.join(file);
        if path.exists() {
            match std::fs::read_to_string(&path) {
                Ok(content) => {
                    // Truncate large files (respecting UTF-8 character boundaries)
                    let truncated = if content.len() > 5000 {
                        let mut end = 5000;
                        while end > 0 && !content.is_char_boundary(end) {
                            end -= 1;
                        }
                        format!("{}...[truncated]", &content[..end])
                    } else {
                        content
                    };

                    contents.push(KeyFileContent {
                        path: file.to_string(),
                        content: truncated,
                    });
                }
                Err(e) => {
                    warn!(
                        "Key file '{}' exists but cannot be read: {}",
                        file, e
                    );
                }
            }
        }
    }

    contents
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::changelog::ChangelogCategory;
    use super::super::evidence::Confidence;

    #[test]
    fn test_extract_keywords() {
        let description = "Added Bybit exchange support with WebSocket streaming";
        let keywords = extract_keywords(description);

        assert!(keywords.contains(&"bybit".to_string()));
        assert!(keywords.contains(&"websocket".to_string()));
        assert!(keywords.contains(&"exchange".to_string()));
    }

    #[test]
    fn test_extract_keywords_filters_stop_words() {
        let description = "Added new feature for the application";
        let keywords = extract_keywords(description);

        assert!(!keywords.contains(&"added".to_string()));
        assert!(!keywords.contains(&"new".to_string()));
        assert!(!keywords.contains(&"the".to_string()));
        assert!(keywords.contains(&"application".to_string()));
    }

    #[test]
    fn test_count_array_elements() {
        let content = r#"
        const TEMPLATES = [
            { name: "one" },
            { name: "two" },
            { name: "three" },
        ];
        "#;

        let count = count_array_elements(content, r"TEMPLATES\s*=\s*\[");
        assert_eq!(count, Some(3));
    }

    #[test]
    fn test_count_array_elements_empty_array() {
        let content = "const ITEMS = [];";
        let count = count_array_elements(content, r"ITEMS\s*=\s*\[");
        assert_eq!(count, Some(0));
    }

    #[test]
    fn test_count_array_elements_empty_array_with_whitespace() {
        let content = "const ITEMS = [   ];";
        let count = count_array_elements(content, r"ITEMS\s*=\s*\[");
        assert_eq!(count, Some(0));
    }

    #[test]
    fn test_count_array_elements_single_element_no_trailing_comma() {
        let content = r#"const ITEMS = ["only"];"#;
        let count = count_array_elements(content, r"ITEMS\s*=\s*\[");
        assert_eq!(count, Some(1));
    }

    #[test]
    fn test_count_array_elements_single_element_with_trailing_comma() {
        let content = r#"const ITEMS = ["only",];"#;
        let count = count_array_elements(content, r"ITEMS\s*=\s*\[");
        assert_eq!(count, Some(1));
    }

    #[test]
    fn test_count_array_elements_nested_brackets() {
        let content = r#"const DATA = [{ inner: [1,2,3] }, { inner: [4,5] }];"#;
        let count = count_array_elements(content, r"DATA\s*=\s*\[");
        assert_eq!(count, Some(2));
    }

    #[test]
    fn test_count_array_elements_nested_arrays() {
        let content = r#"const MATRIX = [[1, 2], [3, 4], [5, 6]];"#;
        let count = count_array_elements(content, r"MATRIX\s*=\s*\[");
        assert_eq!(count, Some(3));
    }

    #[test]
    fn test_count_array_elements_mixed_brackets() {
        let content = r#"const MIX = [{ a: (1 + 2) }, [3, 4], "five"];"#;
        let count = count_array_elements(content, r"MIX\s*=\s*\[");
        assert_eq!(count, Some(3));
    }

    #[test]
    fn test_count_array_elements_unbalanced_brackets() {
        let content = "const BROKEN = [{ unclosed: true";
        let count = count_array_elements(content, r"BROKEN\s*=\s*\[");
        assert!(count.is_none() || count == Some(0));
    }

    #[test]
    fn test_count_array_elements_strings_containing_brackets() {
        let content = r#"const ITEMS = ["has [brackets]", "has {braces}", "normal"];"#;
        // Note: the function uses a simple char-based approach, so brackets
        // inside strings will affect depth tracking. This test documents
        // the current behavior rather than an ideal one.
        let count = count_array_elements(content, r"ITEMS\s*=\s*\[");
        assert!(count.is_some());
    }

    #[test]
    fn test_count_array_elements_pattern_not_found() {
        let content = "const OTHER = [1, 2, 3];";
        let count = count_array_elements(content, r"MISSING\s*=\s*\[");
        assert_eq!(count, None);
    }

    #[test]
    fn test_count_array_elements_no_trailing_comma_multiline() {
        let content = r#"
        const LIST = [
            "alpha",
            "beta",
            "gamma"
        ];
        "#;
        let count = count_array_elements(content, r"LIST\s*=\s*\[");
        assert_eq!(count, Some(3));
    }

    #[test]
    fn test_count_array_elements_multibyte_utf8() {
        // Multi-byte UTF-8 characters (CJK) would cause a panic with
        // .chars().enumerate() because enumerate yields char indices,
        // not byte offsets. .char_indices() yields byte offsets correctly.
        let content = r#"const ITEMS = ["日本語", "中文", "한국어"];"#;
        let count = count_array_elements(content, r"ITEMS\s*=\s*\[");
        assert_eq!(count, Some(3));
    }

    #[test]
    fn test_count_array_elements_multibyte_utf8_multiline() {
        let content = r#"
        const TEMPLATES = [
            { name: "テンプレート" },
            { name: "шаблон" },
            { name: "plantilla" },
        ];
        "#;
        let count = count_array_elements(content, r"TEMPLATES\s*=\s*\[");
        assert_eq!(count, Some(3));
    }

    #[test]
    fn test_entry_confidence_high() {
        let entry = EntryEvidence::new(
            "Test entry".to_string(),
            ChangelogCategory::Added,
            vec![
                KeywordMatch {
                    keyword: "test".to_string(),
                    files_found: vec!["a.rs".to_string(), "b.rs".to_string(), "c.rs".to_string()],
                    occurrence_count: Some(10),
                    sample_lines: Some(vec![]),
                    appears_complete: true,
                },
            ],
            vec![],
            vec![],
        );

        assert_eq!(entry.confidence(), Confidence::High);
    }

    #[test]
    fn test_entry_confidence_low_with_stubs() {
        let entry = EntryEvidence::new(
            "Test entry".to_string(),
            ChangelogCategory::Added,
            vec![
                KeywordMatch {
                    keyword: "test".to_string(),
                    files_found: vec!["a.rs".to_string()],
                    occurrence_count: Some(1),
                    sample_lines: Some(vec![]),
                    appears_complete: false,
                },
            ],
            vec![],
            vec![
                StubIndicator {
                    file: "a.rs".to_string(),
                    line: 10,
                    indicator: "TODO".to_string(),
                    context: "// TODO: implement".to_string(),
                },
                StubIndicator {
                    file: "a.rs".to_string(),
                    line: 20,
                    indicator: "unimplemented!".to_string(),
                    context: "unimplemented!()".to_string(),
                },
            ],
        );

        assert_eq!(entry.confidence(), Confidence::Low);
    }

    // Tests for verify_numeric_claims (KRX-054)

    #[test]
    fn test_verify_numeric_claims_extracts_count() {
        let temp_dir = tempfile::tempdir().expect("Failed to create temp dir");
        let checks = verify_numeric_claims("Added 8 templates for reports", temp_dir.path());

        // Should find the "8 templates" claim
        assert!(!checks.is_empty(), "Should extract numeric claims");
        let claim = checks.iter().find(|c| c.claimed_text.contains("8"));
        assert!(claim.is_some(), "Should find '8 templates' claim");
        assert_eq!(claim.unwrap().claimed_count, Some(8));
    }

    #[test]
    fn test_verify_numeric_claims_skips_zero() {
        let temp_dir = tempfile::tempdir().expect("Failed to create temp dir");
        let checks = verify_numeric_claims("Added 0 bugs to the codebase", temp_dir.path());

        // Should skip zero counts as unreasonable
        let zero_claim = checks.iter().find(|c| c.claimed_count == Some(0));
        assert!(zero_claim.is_none(), "Should skip zero counts");
    }

    #[test]
    fn test_verify_numeric_claims_skips_large_numbers() {
        let temp_dir = tempfile::tempdir().expect("Failed to create temp dir");
        let checks = verify_numeric_claims("Added 9999 features", temp_dir.path());

        // Should skip unreasonably large counts (>1000)
        let large_claim = checks.iter().find(|c| c.claimed_count == Some(9999));
        assert!(large_claim.is_none(), "Should skip counts > 1000");
    }

    #[test]
    fn test_verify_numeric_claims_no_numbers() {
        let temp_dir = tempfile::tempdir().expect("Failed to create temp dir");
        let checks = verify_numeric_claims("Added WebSocket support", temp_dir.path());

        // No numeric claims, should return empty
        assert!(checks.is_empty(), "Should return empty for no numeric claims");
    }

    #[test]
    fn test_verify_numeric_claims_skips_hyphenated_tokens() {
        let temp_dir = tempfile::tempdir().expect("Failed to create temp dir");
        let checks = verify_numeric_claims("Improved UTF-8 handling", temp_dir.path());

        assert!(checks.is_empty(), "Should skip hyphenated tokens like UTF-8");
    }

    #[test]
    fn test_verify_numeric_claims_multiple_claims() {
        let temp_dir = tempfile::tempdir().expect("Failed to create temp dir");
        let checks = verify_numeric_claims("Added 5 templates and 3 presets", temp_dir.path());

        // Should find both claims
        assert!(checks.len() >= 2, "Should find multiple numeric claims");

        let five_claim = checks.iter().find(|c| c.claimed_count == Some(5));
        assert!(five_claim.is_some(), "Should find '5 templates' claim");

        let three_claim = checks.iter().find(|c| c.claimed_count == Some(3));
        assert!(three_claim.is_some(), "Should find '3 presets' claim");
    }

    #[test]
    fn test_verify_numeric_claims_formats_claimed_text() {
        let temp_dir = tempfile::tempdir().expect("Failed to create temp dir");
        let checks = verify_numeric_claims("Added 10 new widgets", temp_dir.path());

        assert!(!checks.is_empty());
        let claim = &checks[0];
        // claimed_text should include both the number and subject
        assert!(claim.claimed_text.contains("10"), "claimed_text should contain the number");
    }

    #[test]
    fn test_verify_numeric_claims_boundary_1000() {
        let temp_dir = tempfile::tempdir().expect("Failed to create temp dir");

        // 1000 should be accepted (boundary)
        let checks_1000 = verify_numeric_claims("Added 1000 items", temp_dir.path());
        let claim_1000 = checks_1000.iter().find(|c| c.claimed_count == Some(1000));
        assert!(claim_1000.is_some(), "1000 should be accepted");

        // 1001 should be rejected
        let checks_1001 = verify_numeric_claims("Added 1001 items", temp_dir.path());
        let claim_1001 = checks_1001.iter().find(|c| c.claimed_count == Some(1001));
        assert!(claim_1001.is_none(), "1001 should be rejected");
    }

    // Tests for parse_rg_json_match (KRX-054)

    #[test]
    fn test_parse_rg_json_match_basic() {
        let line = r#"{"type":"match","data":{"line_number":123,"lines":{"text":"fn main() {\n"}}}"#;
        let result = parse_rg_json_match(line);
        assert!(result.is_some());
        let (line_num, content) = result.unwrap();
        assert_eq!(line_num, 123);
        assert_eq!(content, "fn main() {");
    }

    #[test]
    fn test_parse_rg_json_match_skips_context() {
        let line = r#"{"type":"context","data":{"line_number":45,"lines":{"text":"    let x = 1;\n"}}}"#;
        let result = parse_rg_json_match(line);
        assert!(result.is_none(), "Should skip context lines");
    }

    #[test]
    fn test_parse_rg_json_match_invalid_json() {
        let result = parse_rg_json_match("not json");
        assert!(result.is_none(), "Should return None for invalid JSON");
    }

    #[test]
    fn test_parse_rg_json_match_missing_fields() {
        let line = r#"{"type":"match","data":{"lines":{"text":"hello\n"}}}"#;
        let result = parse_rg_json_match(line);
        assert!(result.is_none(), "Should return None when line_number is missing");
    }

    #[test]
    fn test_parse_rg_json_match_empty_content() {
        let line = r#"{"type":"match","data":{"line_number":1,"lines":{"text":"\n"}}}"#;
        let result = parse_rg_json_match(line);
        assert!(result.is_some());
        let (line_num, content) = result.unwrap();
        assert_eq!(line_num, 1);
        assert_eq!(content, "");
    }

    #[test]
    fn test_parse_rg_json_match_content_with_colon() {
        // Content itself may contain colons
        let line = r#"{"type":"match","data":{"line_number":10,"lines":{"text":"let url = \"http://example.com\";\n"}}}"#;
        let result = parse_rg_json_match(line);
        assert!(result.is_some());
        let (line_num, content) = result.unwrap();
        assert_eq!(line_num, 10);
        assert_eq!(content, "let url = \"http://example.com\";");
    }

    // Tests for gather_key_files UTF-8 truncation (KRX-057)

    #[test]
    fn test_gather_key_files_truncates_large_files_with_utf8() {
        use std::fs;

        let temp_dir = tempfile::tempdir().expect("Failed to create temp dir");

        // Create a README.md with multi-byte UTF-8 characters
        // We need content > 5000 bytes where a multi-byte char would be at boundary
        let mut content = String::new();
        // Fill with CJK characters (3 bytes each) to ensure multi-byte chars
        // are near the 5000 byte boundary
        for _ in 0..2000 {
            content.push('日'); // 3 bytes each = 6000 bytes total
        }

        let readme_path = temp_dir.path().join("README.md");
        fs::write(&readme_path, &content).expect("Failed to write test file");

        // This should not panic - it previously would if truncation hit mid-character
        let result = gather_key_files(temp_dir.path());

        // Verify we got the file
        assert!(!result.is_empty(), "Should find README.md");

        // Find the README entry
        let readme_entry = result.iter().find(|k| k.path == "README.md");
        assert!(readme_entry.is_some(), "Should have README.md entry");

        let truncated = &readme_entry.unwrap().content;
        // Should be truncated (indicated by the suffix)
        assert!(
            truncated.ends_with("...[truncated]"),
            "Large file should be truncated"
        );
        // Should be valid UTF-8 (this would have panicked before the fix)
        assert!(truncated.is_ascii() || truncated.chars().count() > 0);
    }

    #[test]
    fn test_gather_key_files_does_not_truncate_small_files() {
        use std::fs;

        let temp_dir = tempfile::tempdir().expect("Failed to create temp dir");

        // Create a small README.md (under 5000 bytes)
        let content = "# My Project\n\nThis is a small readme with emojis 🚀✨\n";
        let readme_path = temp_dir.path().join("README.md");
        fs::write(&readme_path, content).expect("Failed to write test file");

        let result = gather_key_files(temp_dir.path());

        assert!(!result.is_empty(), "Should find README.md");

        let readme_entry = result.iter().find(|k| k.path == "README.md");
        assert!(readme_entry.is_some());

        let file_content = &readme_entry.unwrap().content;
        // Should NOT be truncated
        assert!(
            !file_content.ends_with("...[truncated]"),
            "Small file should not be truncated"
        );
        assert_eq!(file_content, content);
    }
}
