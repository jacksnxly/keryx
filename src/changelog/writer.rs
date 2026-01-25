//! Write new changelog sections.

use std::path::Path;

use chrono::Utc;
use semver::Version;

use crate::error::ChangelogError;

use super::format::{ChangelogOutput, CHANGELOG_HEADER};
use super::parser::{find_insertion_point, read_changelog};

/// Write changelog entries to a file.
///
/// - Creates the file with header if it doesn't exist
/// - Backs up existing file to `<filename>.md.bak` (e.g., `CHANGELOG.md.bak`)
/// - Handles [Unreleased] section conversion per spec
pub fn write_changelog(
    path: &Path,
    output: &ChangelogOutput,
    version: &Version,
) -> Result<(), ChangelogError> {
    let today = Utc::now().format("%Y-%m-%d").to_string();

    // Read existing changelog or create new
    let existing = read_changelog(path)?;

    let new_content = if let Some(existing) = existing {
        // Backup existing file
        let backup_path = path.with_extension("md.bak");
        std::fs::copy(path, &backup_path).map_err(ChangelogError::BackupFailed)?;

        // Generate new version section
        let new_section = format_version_section(version, &today, output);

        // Insert new section
        let insertion_point = find_insertion_point(&existing.raw_content);

        let mut new_content = String::new();
        new_content.push_str(&existing.raw_content[..insertion_point]);
        new_content.push_str(&new_section);
        new_content.push('\n');
        new_content.push_str(&existing.raw_content[insertion_point..]);

        new_content
    } else {
        // Create new changelog
        let mut content = CHANGELOG_HEADER.to_string();
        content.push_str(&format_version_section(version, &today, output));
        content
    };

    std::fs::write(path, new_content).map_err(ChangelogError::WriteFailed)?;

    Ok(())
}

/// Format a version section in Keep a Changelog format.
fn format_version_section(version: &Version, date: &str, output: &ChangelogOutput) -> String {
    let mut section = format!("## [{}] - {}\n\n", version, date);

    for (category, entries) in output.entries_by_category() {
        section.push_str(&format!("### {}\n\n", category.as_str()));

        for entry in entries {
            section.push_str(&format!("- {}\n", entry.description));
        }

        section.push('\n');
    }

    section
}

/// Generate a summary message for the user.
pub fn generate_summary(output: &ChangelogOutput) -> String {
    let total = output.entries.len();
    let counts = output.count_by_type();

    if counts.is_empty() {
        return "No changelog entries generated.".to_string();
    }

    let details: Vec<String> = counts
        .iter()
        .map(|(cat, count)| {
            // Capitalize first letter
            let capitalized = cat
                .chars()
                .next()
                .map(|c| c.to_uppercase().to_string())
                .unwrap_or_default()
                + &cat[1..];
            format!("{}: {}", capitalized, count)
        })
        .collect();

    let entry_word = if total == 1 { "entry" } else { "entries" };

    format!(
        "Added {} {} ({}) to CHANGELOG.md",
        total,
        entry_word,
        details.join(", ")
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::changelog::format::{ChangelogCategory, ChangelogEntry};

    #[test]
    fn test_format_version_section() {
        let output = ChangelogOutput {
            entries: vec![
                ChangelogEntry {
                    category: ChangelogCategory::Added,
                    description: "New feature".to_string(),
                },
                ChangelogEntry {
                    category: ChangelogCategory::Fixed,
                    description: "Bug fix".to_string(),
                },
            ],
        };

        let section = format_version_section(&Version::new(1, 2, 0), "2024-01-01", &output);

        assert!(section.contains("## [1.2.0] - 2024-01-01"));
        assert!(section.contains("### Added"));
        assert!(section.contains("- New feature"));
        assert!(section.contains("### Fixed"));
        assert!(section.contains("- Bug fix"));
    }

    #[test]
    fn test_generate_summary() {
        let output = ChangelogOutput {
            entries: vec![
                ChangelogEntry {
                    category: ChangelogCategory::Added,
                    description: "Feature 1".to_string(),
                },
                ChangelogEntry {
                    category: ChangelogCategory::Added,
                    description: "Feature 2".to_string(),
                },
                ChangelogEntry {
                    category: ChangelogCategory::Fixed,
                    description: "Bug fix".to_string(),
                },
            ],
        };

        let summary = generate_summary(&output);
        assert!(summary.contains("3 entries"));
        assert!(summary.contains("Added: 2"));
        assert!(summary.contains("Fixed: 1"));
    }
}
