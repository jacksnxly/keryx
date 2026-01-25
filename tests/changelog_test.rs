//! Integration tests for changelog parsing and writing.

mod common;

use keryx::changelog::{
    format::{ChangelogCategory, ChangelogEntry, ChangelogOutput},
    parser::{find_insertion_point, read_changelog},
    writer::write_changelog,
};
use semver::Version;
use std::fs;

#[test]
fn test_read_empty_changelog() {
    let path = common::changelog_fixture("empty.md");
    let result = read_changelog(&path);

    // parse-changelog errors when no releases exist, which is expected
    // The write_changelog function handles creating new changelogs
    assert!(result.is_err() || result.unwrap().is_none());
}

#[test]
fn test_read_changelog_with_unreleased() {
    let path = common::changelog_fixture("with_unreleased.md");
    let result = read_changelog(&path).unwrap();

    assert!(result.is_some());
    let parsed = result.unwrap();
    assert!(parsed.has_unreleased);
    assert_eq!(parsed.latest_version, Some("1.0.0".to_string()));
}

#[test]
fn test_read_changelog_with_versions() {
    let path = common::changelog_fixture("with_versions.md");
    let result = read_changelog(&path).unwrap();

    assert!(result.is_some());
    let parsed = result.unwrap();
    assert!(!parsed.has_unreleased);
    assert_eq!(parsed.latest_version, Some("2.0.0".to_string()));
}

#[test]
fn test_read_nonexistent_changelog() {
    let path = common::fixtures_dir().join("changelogs/nonexistent.md");
    let result = read_changelog(&path).unwrap();

    assert!(result.is_none());
}

#[test]
fn test_find_insertion_point_empty_changelog() {
    let content = common::read_fixture(common::changelog_fixture("empty.md"));
    let pos = find_insertion_point(&content);

    // Should insert at end of file for empty changelog
    assert_eq!(pos, content.len());
}

#[test]
fn test_find_insertion_point_with_unreleased() {
    let content = common::read_fixture(common::changelog_fixture("with_unreleased.md"));
    let pos = find_insertion_point(&content);

    // Should insert after [Unreleased] section, before [1.0.0]
    assert!(content[pos..].starts_with("## [1.0.0]"));
}

#[test]
fn test_find_insertion_point_with_versions() {
    let content = common::read_fixture(common::changelog_fixture("with_versions.md"));
    let pos = find_insertion_point(&content);

    // Should insert before first version [2.0.0]
    assert!(content[pos..].starts_with("## [2.0.0]"));
}

#[test]
fn test_write_changelog_creates_new_file() {
    let temp_dir = common::temp_test_dir();
    let output_path = temp_dir.path().join("CHANGELOG.md");

    let entries = ChangelogOutput {
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

    write_changelog(&output_path, &entries, &Version::new(1, 0, 0)).unwrap();

    assert!(output_path.exists());

    let content = fs::read_to_string(&output_path).unwrap();
    assert!(content.contains("# Changelog"));
    assert!(content.contains("## [1.0.0]"));
    assert!(content.contains("### Added"));
    assert!(content.contains("- New feature"));
    assert!(content.contains("### Fixed"));
    assert!(content.contains("- Bug fix"));
}

#[test]
fn test_write_changelog_creates_backup() {
    let temp_dir = common::temp_test_dir();
    let output_path = temp_dir.path().join("CHANGELOG.md");
    let backup_path = temp_dir.path().join("CHANGELOG.md.bak");

    // Create initial changelog
    let initial_content = "# Changelog\n\n## [1.0.0] - 2024-01-01\n\n### Added\n\n- Initial\n";
    fs::write(&output_path, initial_content).unwrap();

    let entries = ChangelogOutput {
        entries: vec![ChangelogEntry {
            category: ChangelogCategory::Added,
            description: "New in 2.0".to_string(),
        }],
    };

    write_changelog(&output_path, &entries, &Version::new(2, 0, 0)).unwrap();

    // Backup should exist with original content
    assert!(backup_path.exists());
    let backup_content = fs::read_to_string(&backup_path).unwrap();
    assert!(backup_content.contains("## [1.0.0]"));
    assert!(!backup_content.contains("## [2.0.0]"));

    // Original should have new content
    let new_content = fs::read_to_string(&output_path).unwrap();
    assert!(new_content.contains("## [2.0.0]"));
    assert!(new_content.contains("## [1.0.0]"));
}

#[test]
fn test_write_changelog_inserts_before_existing_versions() {
    let temp_dir = common::temp_test_dir();
    let output_path = temp_dir.path().join("CHANGELOG.md");

    // Copy fixture to temp
    let fixture_content = common::read_fixture(common::changelog_fixture("with_versions.md"));
    fs::write(&output_path, &fixture_content).unwrap();

    let entries = ChangelogOutput {
        entries: vec![ChangelogEntry {
            category: ChangelogCategory::Added,
            description: "Feature in 3.0".to_string(),
        }],
    };

    write_changelog(&output_path, &entries, &Version::new(3, 0, 0)).unwrap();

    let content = fs::read_to_string(&output_path).unwrap();

    // New version should appear before existing versions
    let pos_3 = content.find("## [3.0.0]").unwrap();
    let pos_2 = content.find("## [2.0.0]").unwrap();
    let pos_1 = content.find("## [1.0.0]").unwrap();

    assert!(pos_3 < pos_2);
    assert!(pos_2 < pos_1);
}
