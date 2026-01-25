//! Read existing changelog using parse-changelog.

use std::path::Path;

use semver::Version;

use crate::error::ChangelogError;

/// Parsed changelog information.
#[derive(Debug)]
pub struct ParsedChangelog {
    pub has_unreleased: bool,
    pub latest_version: Option<Version>,
    pub raw_content: String,
}

/// Read and parse an existing changelog file.
pub fn read_changelog(path: &Path) -> Result<Option<ParsedChangelog>, ChangelogError> {
    if !path.exists() {
        return Ok(None);
    }

    let content = std::fs::read_to_string(path).map_err(ChangelogError::ReadFailed)?;

    let changelog = parse_changelog::parse(&content)
        .map_err(|e| ChangelogError::ParseFailed(e.to_string()))?;

    let has_unreleased = changelog.get("Unreleased").is_some()
        || changelog.get("unreleased").is_some();

    // Find the latest versioned release
    let latest_version = changelog
        .iter()
        .find(|(title, _)| {
            let t = title.to_lowercase();
            t != "unreleased" && !t.is_empty()
        })
        .and_then(|(title, _)| extract_version_from_title(title));

    Ok(Some(ParsedChangelog {
        has_unreleased,
        latest_version,
        raw_content: content,
    }))
}

/// Extract version number from a changelog section title.
/// e.g., "[1.2.3] - 2024-01-01" -> Version { major: 1, minor: 2, patch: 3 }
///
/// Returns `None` if the version string cannot be parsed as a valid semver.
fn extract_version_from_title(title: &str) -> Option<Version> {
    // Remove brackets and date
    let title = title.trim();

    // Handle [version] format
    let version_str = if title.starts_with('[') {
        if let Some(end) = title.find(']') {
            &title[1..end]
        } else {
            title
        }
    } else if let Some(dash_pos) = title.find(" - ") {
        // Handle version - date format
        title[..dash_pos].trim()
    } else {
        title
    };

    Version::parse(version_str).ok()
}

/// Find the position to insert a new version section.
/// Returns the byte offset after the header and any [Unreleased] section.
pub fn find_insertion_point(content: &str) -> usize {
    let lines: Vec<&str> = content.lines().collect();

    for (i, line) in lines.iter().enumerate() {
        // Skip initial header (until first ## section)
        if line.starts_with("## ") {
            // If this is [Unreleased], skip past it
            if line.to_lowercase().contains("unreleased") {
                // Find the next ## section or end of file
                for (j, next_line) in lines[i + 1..].iter().enumerate() {
                    if next_line.starts_with("## ") {
                        // Calculate byte position using iterators
                        let byte_pos: usize =
                            lines.iter().take(i + j + 1).map(|l| l.len() + 1).sum();
                        return byte_pos;
                    }
                }
                // No more sections, insert at end
                return content.len();
            } else {
                // First section is not Unreleased, insert before it
                let byte_pos: usize = lines.iter().take(i).map(|l| l.len() + 1).sum();
                return byte_pos;
            }
        }
    }

    // No sections found, insert at end of content
    content.len()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_version_with_brackets() {
        assert_eq!(
            extract_version_from_title("[1.2.3] - 2024-01-01"),
            Some(Version::new(1, 2, 3))
        );
    }

    #[test]
    fn test_extract_version_without_brackets() {
        assert_eq!(
            extract_version_from_title("1.2.3 - 2024-01-01"),
            Some(Version::new(1, 2, 3))
        );
    }

    #[test]
    fn test_extract_version_invalid() {
        assert_eq!(extract_version_from_title("not-a-version"), None);
    }

    #[test]
    fn test_find_insertion_point_empty() {
        let content = "# Changelog\n\nSome header text.\n";
        let pos = find_insertion_point(content);
        assert_eq!(pos, content.len());
    }

    #[test]
    fn test_find_insertion_point_with_unreleased() {
        let content = "# Changelog\n\n## [Unreleased]\n\n- Some change\n\n## [1.0.0] - 2024-01-01\n";
        let pos = find_insertion_point(content);
        assert!(pos > 0);
        assert!(content[pos..].starts_with("## [1.0.0]"));
    }
}
