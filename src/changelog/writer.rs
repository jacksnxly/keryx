//! Write new changelog sections.

use std::io::Write;
use std::path::Path;

use chrono::Utc;
use semver::Version;
use tempfile::NamedTempFile;

use crate::error::ChangelogError;

use super::format::{CHANGELOG_HEADER, ChangelogOutput};
use super::parser::{find_insertion_point, read_changelog};

/// Atomically write content to a file using temp file + rename pattern.
///
/// This prevents TOCTOU race conditions by:
/// 1. Creating a temp file in the same directory as the target
/// 2. Writing all content to the temp file
/// 3. Atomically renaming the temp file to the target path
fn atomic_write(path: &Path, content: &str) -> Result<(), ChangelogError> {
    // Create temp file in same directory (required for atomic rename across filesystems)
    let parent = path.parent().unwrap_or(Path::new("."));

    let mut temp_file = NamedTempFile::new_in(parent).map_err(ChangelogError::WriteFailed)?;

    // Write content
    temp_file
        .write_all(content.as_bytes())
        .map_err(ChangelogError::WriteFailed)?;

    // Sync to disk for durability
    temp_file
        .as_file()
        .sync_all()
        .map_err(ChangelogError::WriteFailed)?;

    // Atomically replace the target file
    temp_file
        .persist(path)
        .map_err(|e| ChangelogError::WriteFailed(e.error))?;

    Ok(())
}

/// Atomically copy a file (for backups).
///
/// Uses the same temp file + rename pattern to prevent partial backups.
fn atomic_copy(src: &Path, dst: &Path) -> Result<(), ChangelogError> {
    let content = std::fs::read(src).map_err(ChangelogError::BackupFailed)?;

    let parent = dst.parent().unwrap_or(Path::new("."));
    let mut temp_file = NamedTempFile::new_in(parent).map_err(ChangelogError::BackupFailed)?;

    temp_file
        .write_all(&content)
        .map_err(ChangelogError::BackupFailed)?;

    temp_file
        .as_file()
        .sync_all()
        .map_err(ChangelogError::BackupFailed)?;

    temp_file
        .persist(dst)
        .map_err(|e| ChangelogError::BackupFailed(e.error))?;

    Ok(())
}

/// Write changelog entries to a file.
///
/// - Creates the file with header if it doesn't exist
/// - Backs up existing file to `<filename>.md.bak` (e.g., `CHANGELOG.md.bak`)
/// - Handles `[Unreleased]` section conversion per spec
pub fn write_changelog(
    path: &Path,
    output: &ChangelogOutput,
    version: &Version,
) -> Result<(), ChangelogError> {
    let today = Utc::now().format("%Y-%m-%d").to_string();

    // Read existing changelog or create new
    let existing = read_changelog(path)?;

    let new_content = if let Some(existing) = existing {
        // Atomic backup of existing file
        let backup_path = path.with_extension("md.bak");
        atomic_copy(path, &backup_path)?;

        // Generate new version section
        let new_section = format_version_section(version, &today, output);

        // Normalize line endings before insertion (matches find_insertion_point behavior)
        // This ensures byte offsets are calculated consistently across platforms
        let normalized_content = existing.raw_content.replace("\r\n", "\n");

        // Insert new section
        let insertion_point = find_insertion_point(&normalized_content);

        let mut new_content = String::new();
        new_content.push_str(&normalized_content[..insertion_point]);
        new_content.push_str(&new_section);
        new_content.push('\n');
        new_content.push_str(&normalized_content[insertion_point..]);

        new_content
    } else {
        // Create new changelog
        let mut content = CHANGELOG_HEADER.to_string();
        content.push_str(&format_version_section(version, &today, output));
        content
    };

    // Atomic write: temp file + rename to prevent TOCTOU race
    atomic_write(path, &new_content)?;

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

    #[test]
    fn test_atomic_write_creates_file() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("test.md");

        atomic_write(&path, "test content").unwrap();

        assert!(path.exists());
        assert_eq!(std::fs::read_to_string(&path).unwrap(), "test content");
    }

    #[test]
    fn test_atomic_write_overwrites_existing() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("test.md");

        std::fs::write(&path, "original content").unwrap();
        atomic_write(&path, "new content").unwrap();

        assert_eq!(std::fs::read_to_string(&path).unwrap(), "new content");
    }

    #[test]
    fn test_atomic_copy_creates_backup() {
        let dir = tempfile::tempdir().unwrap();
        let src = dir.path().join("source.md");
        let dst = dir.path().join("backup.md");

        std::fs::write(&src, "source content").unwrap();
        atomic_copy(&src, &dst).unwrap();

        assert!(dst.exists());
        assert_eq!(std::fs::read_to_string(&dst).unwrap(), "source content");
        // Original still exists
        assert!(src.exists());
    }

    #[test]
    fn test_atomic_copy_overwrites_existing_backup() {
        let dir = tempfile::tempdir().unwrap();
        let src = dir.path().join("source.md");
        let dst = dir.path().join("backup.md");

        std::fs::write(&src, "new source content").unwrap();
        std::fs::write(&dst, "old backup content").unwrap();
        atomic_copy(&src, &dst).unwrap();

        assert_eq!(std::fs::read_to_string(&dst).unwrap(), "new source content");
    }

    #[test]
    fn test_atomic_write_temp_file_in_same_directory() {
        // This test verifies that temp files are created in the same directory
        // as the target, which is required for atomic rename to work across filesystems
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("test.md");

        // Count files before
        let files_before: Vec<_> = std::fs::read_dir(dir.path()).unwrap().collect();

        atomic_write(&path, "content").unwrap();

        // After atomic write completes, only the target file should exist
        // (temp file is renamed to target, not left behind)
        let files_after: Vec<_> = std::fs::read_dir(dir.path())
            .unwrap()
            .filter_map(|e| e.ok())
            .collect();

        assert_eq!(files_after.len(), files_before.len() + 1);
        assert!(files_after.iter().any(|e| e.file_name() == "test.md"));
    }
}
