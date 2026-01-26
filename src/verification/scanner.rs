//! Codebase scanner for gathering verification evidence.

use std::collections::HashSet;
use std::path::Path;
use std::process::Command;

use regex::Regex;
use tracing::debug;

use crate::changelog::ChangelogEntry;
use super::evidence::{
    Confidence, CountCheck, EntryEvidence, KeyFileContent, KeywordMatch,
    StubIndicator, VerificationEvidence,
};

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
    evidence.project_structure = get_project_structure(repo_path);

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
    let category = entry.category.as_str().to_string();

    // Extract keywords from the description
    let keywords = extract_keywords(description);
    debug!("Extracted keywords from '{}': {:?}", description, keywords);

    // Search for each keyword in the codebase
    let mut keyword_matches = Vec::new();
    let mut all_stub_indicators = Vec::new();

    for keyword in &keywords {
        if let Some(match_result) = search_keyword(keyword, repo_path) {
            // Check for stub indicators near the matches
            let stubs = find_stub_indicators_near_keyword(keyword, repo_path);
            let appears_complete = stubs.is_empty();

            all_stub_indicators.extend(stubs);
            keyword_matches.push(KeywordMatch {
                keyword: keyword.clone(),
                files_found: match_result.files,
                occurrence_count: match_result.count,
                sample_lines: match_result.samples,
                appears_complete,
            });
        }
    }

    // Check for numeric claims
    let count_checks = verify_numeric_claims(description, repo_path);

    // Calculate confidence
    let confidence = calculate_confidence(&keyword_matches, &all_stub_indicators, &count_checks);

    EntryEvidence {
        original_description: description.clone(),
        category,
        keyword_matches,
        count_checks,
        stub_indicators: all_stub_indicators,
        confidence,
    }
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

    // Also extract quoted terms
    let quote_re = Regex::new(r#"["'`]([^"'`]+)["'`]"#).expect("Invalid regex");
    for cap in quote_re.captures_iter(description) {
        if let Some(quoted) = cap.get(1) {
            let term = quoted.as_str().to_lowercase();
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
    count: usize,
    samples: Vec<String>,
}

/// Search for a keyword in the codebase using ripgrep.
fn search_keyword(keyword: &str, repo_path: &Path) -> Option<SearchResult> {
    // Use ripgrep for fast searching
    let output = Command::new("rg")
        .args([
            "--ignore-case",
            "--files-with-matches",
            "--type-add", "code:*.{rs,ts,tsx,js,jsx,py,go,java,c,cpp,h,hpp}",
            "--type", "code",
            "-g", "!target",
            "-g", "!node_modules",
            "-g", "!dist",
            "-g", "!build",
            "-g", "!.git",
            keyword,
        ])
        .current_dir(repo_path)
        .output();

    let files: Vec<String> = match output {
        Ok(out) if out.status.success() => {
            String::from_utf8_lossy(&out.stdout)
                .lines()
                .take(10) // Limit to 10 files
                .map(String::from)
                .collect()
        }
        _ => return None,
    };

    if files.is_empty() {
        return None;
    }

    // Get sample lines with context
    let samples_output = Command::new("rg")
        .args([
            "--ignore-case",
            "--max-count", "3",
            "-C", "1",
            "--type-add", "code:*.{rs,ts,tsx,js,jsx,py,go,java,c,cpp,h,hpp}",
            "--type", "code",
            "-g", "!target",
            "-g", "!node_modules",
            "-g", "!dist",
            "-g", "!build",
            "-g", "!.git",
            keyword,
        ])
        .current_dir(repo_path)
        .output();

    let samples: Vec<String> = match samples_output {
        Ok(out) if out.status.success() => {
            String::from_utf8_lossy(&out.stdout)
                .lines()
                .take(15) // Limit sample lines
                .map(String::from)
                .collect()
        }
        _ => Vec::new(),
    };

    // Count total occurrences
    let count_output = Command::new("rg")
        .args([
            "--ignore-case",
            "--count-matches",
            "--type-add", "code:*.{rs,ts,tsx,js,jsx,py,go,java,c,cpp,h,hpp}",
            "--type", "code",
            "-g", "!target",
            "-g", "!node_modules",
            "-g", "!dist",
            "-g", "!build",
            "-g", "!.git",
            keyword,
        ])
        .current_dir(repo_path)
        .output();

    let count: usize = match count_output {
        Ok(out) if out.status.success() => {
            String::from_utf8_lossy(&out.stdout)
                .lines()
                .filter_map(|line| {
                    line.rsplit(':').next()?.parse::<usize>().ok()
                })
                .sum()
        }
        _ => files.len(),
    };

    Some(SearchResult {
        files,
        count,
        samples,
    })
}

/// Find stub indicators near a keyword in the codebase.
fn find_stub_indicators_near_keyword(keyword: &str, repo_path: &Path) -> Vec<StubIndicator> {
    let mut indicators = Vec::new();

    // First, find files containing the keyword
    let files_output = Command::new("rg")
        .args([
            "--ignore-case",
            "--files-with-matches",
            "-g", "!target",
            "-g", "!node_modules",
            "-g", "!dist",
            "-g", "!build",
            "-g", "!.git",
            keyword,
        ])
        .current_dir(repo_path)
        .output();

    let files: Vec<String> = match files_output {
        Ok(out) if out.status.success() => {
            String::from_utf8_lossy(&out.stdout)
                .lines()
                .take(5) // Only check first 5 files
                .map(String::from)
                .collect()
        }
        _ => return indicators,
    };

    // Check each file for stub patterns
    for file in files {
        for pattern in STUB_PATTERNS {
            let output = Command::new("rg")
                .args([
                    "--line-number",
                    "--max-count", "3",
                    "-C", "1",
                    pattern,
                    &file,
                ])
                .current_dir(repo_path)
                .output();

            if let Ok(out) = output {
                if out.status.success() {
                    let content = String::from_utf8_lossy(&out.stdout);
                    for line in content.lines() {
                        if let Some((line_num, context)) = parse_rg_line(line) {
                            indicators.push(StubIndicator {
                                file: file.clone(),
                                line: line_num,
                                indicator: pattern.to_string(),
                                context,
                            });
                        }
                    }
                }
            }
        }
    }

    indicators
}

/// Parse a ripgrep output line into line number and content.
fn parse_rg_line(line: &str) -> Option<(usize, String)> {
    // Format: "123:content" or "123-context"
    let parts: Vec<&str> = line.splitn(2, |c| c == ':' || c == '-').collect();
    if parts.len() == 2 {
        if let Ok(num) = parts[0].parse::<usize>() {
            return Some((num, parts[1].to_string()));
        }
    }
    None
}

/// Verify numeric claims in a description.
fn verify_numeric_claims(description: &str, repo_path: &Path) -> Vec<CountCheck> {
    let mut checks = Vec::new();

    // Regex to find numeric claims like "8 templates", "6 languages", etc.
    let num_re = Regex::new(r"(\d+)\s+([a-zA-Z]+(?:\s+[a-zA-Z]+)?)")
        .expect("Invalid regex");

    for cap in num_re.captures_iter(description) {
        let count_str = cap.get(1).map(|m| m.as_str()).unwrap_or("0");
        let subject = cap.get(2).map(|m| m.as_str()).unwrap_or("");

        let claimed_count: usize = count_str.parse().unwrap_or(0);
        if claimed_count == 0 || claimed_count > 1000 {
            continue; // Skip unreasonable counts
        }

        // Try to verify this count
        let (actual_count, source) = try_verify_count(subject, repo_path);

        let matches = actual_count.map(|a| a == claimed_count).unwrap_or(true);

        checks.push(CountCheck {
            claimed_text: format!("{} {}", count_str, subject),
            claimed_count: Some(claimed_count),
            actual_count,
            source_location: source,
            matches,
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
        _ => None,
    }
}

/// Search for an array definition and count its elements.
fn search_and_count_array(
    repo_path: &Path,
    file_glob: &str,
    pattern: &str,
) -> Option<(usize, String)> {
    // Find files with the pattern
    let output = Command::new("rg")
        .args([
            "--files-with-matches",
            "-g", file_glob,
            "-g", "!target",
            "-g", "!node_modules",
            "-g", "!dist",
            pattern,
        ])
        .current_dir(repo_path)
        .output();

    let files: Vec<String> = match output {
        Ok(out) if out.status.success() => {
            String::from_utf8_lossy(&out.stdout)
                .lines()
                .map(String::from)
                .collect()
        }
        _ => return None,
    };

    for file in files {
        // Read the file and try to count array elements
        let file_path = repo_path.join(&file);
        if let Ok(content) = std::fs::read_to_string(&file_path) {
            // Simple heuristic: count items between [ and ]
            if let Some(count) = count_array_elements(&content, pattern) {
                return Some((count, file));
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
    for (i, c) in content[start..].chars().enumerate() {
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

/// Calculate confidence based on evidence.
fn calculate_confidence(
    keyword_matches: &[KeywordMatch],
    stub_indicators: &[StubIndicator],
    count_checks: &[CountCheck],
) -> Confidence {
    // Start with medium confidence
    let mut score: i32 = 50;

    // Boost for keyword matches
    for km in keyword_matches {
        if km.occurrence_count > 0 {
            score += 10;
            if km.appears_complete {
                score += 10;
            }
        }
        if km.files_found.len() > 2 {
            score += 5;
        }
    }

    // Penalty for stub indicators
    score -= (stub_indicators.len() as i32) * 15;

    // Penalty for count mismatches
    for check in count_checks {
        if !check.matches {
            score -= 20;
        }
    }

    // No keyword matches at all is suspicious
    if keyword_matches.is_empty() {
        score -= 30;
    }

    if score >= 70 {
        Confidence::High
    } else if score >= 40 {
        Confidence::Medium
    } else {
        Confidence::Low
    }
}

/// Get project structure using tree command.
fn get_project_structure(repo_path: &Path) -> Option<String> {
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
            Some(truncated)
        }
        _ => {
            // Fallback to ls if tree not available
            let ls_output = Command::new("ls")
                .args(["-la"])
                .current_dir(repo_path)
                .output();

            match ls_output {
                Ok(out) if out.status.success() => {
                    Some(String::from_utf8_lossy(&out.stdout).to_string())
                }
                _ => None,
            }
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
            if let Ok(content) = std::fs::read_to_string(&path) {
                // Truncate large files
                let truncated = if content.len() > 5000 {
                    format!("{}...[truncated]", &content[..5000])
                } else {
                    content
                };

                contents.push(KeyFileContent {
                    path: file.to_string(),
                    content: truncated,
                });
            }
        }
    }

    contents
}

#[cfg(test)]
mod tests {
    use super::*;

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
    fn test_calculate_confidence_high() {
        let keyword_matches = vec![
            KeywordMatch {
                keyword: "test".to_string(),
                files_found: vec!["a.rs".to_string(), "b.rs".to_string(), "c.rs".to_string()],
                occurrence_count: 10,
                sample_lines: vec![],
                appears_complete: true,
            },
        ];

        let confidence = calculate_confidence(&keyword_matches, &[], &[]);
        assert_eq!(confidence, Confidence::High);
    }

    #[test]
    fn test_calculate_confidence_low_with_stubs() {
        let keyword_matches = vec![
            KeywordMatch {
                keyword: "test".to_string(),
                files_found: vec!["a.rs".to_string()],
                occurrence_count: 1,
                sample_lines: vec![],
                appears_complete: false,
            },
        ];

        let stub_indicators = vec![
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
        ];

        let confidence = calculate_confidence(&keyword_matches, &stub_indicators, &[]);
        assert_eq!(confidence, Confidence::Low);
    }
}
