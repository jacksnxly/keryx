//! Integration tests for version calculation.

use chrono::Utc;
use keryx::git::{CommitType, ParsedCommit};
use keryx::version::calculate_next_version;
use semver::Version;

fn make_commit(commit_type: Option<CommitType>, breaking: bool, message: &str) -> ParsedCommit {
    ParsedCommit {
        hash: "abc123def456".to_string(),
        message: message.to_string(),
        commit_type,
        scope: None,
        breaking,
        timestamp: Utc::now(),
    }
}

#[test]
fn test_initial_version_with_feat() {
    let commits = vec![make_commit(
        Some(CommitType::Feat),
        false,
        "feat: initial feature",
    )];

    let next = calculate_next_version(None, &commits);

    // No base version + feat = 0.1.0
    assert_eq!(next, Version::new(0, 1, 0));
}

#[test]
fn test_initial_version_with_fix() {
    let commits = vec![make_commit(
        Some(CommitType::Fix),
        false,
        "fix: initial fix",
    )];

    let next = calculate_next_version(None, &commits);

    // No base version + fix = 0.0.1
    assert_eq!(next, Version::new(0, 0, 1));
}

#[test]
fn test_initial_version_with_breaking() {
    let commits = vec![make_commit(
        Some(CommitType::Feat),
        true,
        "feat!: breaking initial",
    )];

    let next = calculate_next_version(None, &commits);

    // No base version + breaking = 1.0.0
    assert_eq!(next, Version::new(1, 0, 0));
}

#[test]
fn test_bump_major_from_breaking_change() {
    let base = Version::new(1, 5, 3);
    let commits = vec![
        make_commit(Some(CommitType::Fix), false, "fix: small fix"),
        make_commit(Some(CommitType::Feat), true, "feat!: breaking change"),
        make_commit(Some(CommitType::Feat), false, "feat: another feature"),
    ];

    let next = calculate_next_version(Some(&base), &commits);

    // Breaking change = major bump, resets minor and patch
    assert_eq!(next, Version::new(2, 0, 0));
}

#[test]
fn test_bump_minor_from_feat() {
    let base = Version::new(1, 5, 3);
    let commits = vec![
        make_commit(Some(CommitType::Fix), false, "fix: bug fix"),
        make_commit(Some(CommitType::Feat), false, "feat: new feature"),
        make_commit(Some(CommitType::Docs), false, "docs: update readme"),
    ];

    let next = calculate_next_version(Some(&base), &commits);

    // Feature = minor bump, resets patch
    assert_eq!(next, Version::new(1, 6, 0));
}

#[test]
fn test_bump_patch_from_fix_only() {
    let base = Version::new(1, 5, 3);
    let commits = vec![
        make_commit(Some(CommitType::Fix), false, "fix: bug 1"),
        make_commit(Some(CommitType::Fix), false, "fix: bug 2"),
        make_commit(Some(CommitType::Chore), false, "chore: cleanup"),
    ];

    let next = calculate_next_version(Some(&base), &commits);

    // Only fixes = patch bump
    assert_eq!(next, Version::new(1, 5, 4));
}

#[test]
fn test_bump_patch_from_perf() {
    let base = Version::new(2, 0, 0);
    let commits = vec![make_commit(
        Some(CommitType::Perf),
        false,
        "perf: improve query speed",
    )];

    let next = calculate_next_version(Some(&base), &commits);

    // Perf = patch bump
    assert_eq!(next, Version::new(2, 0, 1));
}

#[test]
fn test_no_commits_defaults_to_patch() {
    let base = Version::new(1, 0, 0);
    let commits: Vec<ParsedCommit> = vec![];

    let next = calculate_next_version(Some(&base), &commits);

    // Empty commits = patch bump (conservative default)
    assert_eq!(next, Version::new(1, 0, 1));
}

#[test]
fn test_non_conventional_commits_default_to_patch() {
    let base = Version::new(1, 0, 0);
    let commits = vec![
        make_commit(None, false, "Updated the thing"),
        make_commit(None, false, "Fixed another thing"),
    ];

    let next = calculate_next_version(Some(&base), &commits);

    // Non-conventional commits = patch bump
    assert_eq!(next, Version::new(1, 0, 1));
}

#[test]
fn test_prerelease_base_version() {
    let base = Version::parse("1.0.0-beta.1").unwrap();
    let commits = vec![make_commit(
        Some(CommitType::Feat),
        false,
        "feat: new feature",
    )];

    let next = calculate_next_version(Some(&base), &commits);

    // Should bump minor from 1.0.0 (ignoring prerelease)
    assert_eq!(next, Version::new(1, 1, 0));
}

#[test]
fn test_commit_with_scope_still_bumps_correctly() {
    let base = Version::new(1, 0, 0);
    let commits = vec![ParsedCommit {
        hash: "abc".to_string(),
        message: "feat(auth): add OAuth support".to_string(),
        commit_type: Some(CommitType::Feat),
        scope: Some("auth".to_string()),
        breaking: false,
        timestamp: Utc::now(),
    }];

    let next = calculate_next_version(Some(&base), &commits);

    assert_eq!(next, Version::new(1, 1, 0));
}

#[test]
fn test_breaking_change_in_footer() {
    let base = Version::new(1, 0, 0);
    let commits = vec![ParsedCommit {
        hash: "abc".to_string(),
        message: "feat: change API\n\nBREAKING CHANGE: removed old endpoint".to_string(),
        commit_type: Some(CommitType::Feat),
        scope: None,
        breaking: true, // Parser sets this from footer
        timestamp: Utc::now(),
    }];

    let next = calculate_next_version(Some(&base), &commits);

    assert_eq!(next, Version::new(2, 0, 0));
}
