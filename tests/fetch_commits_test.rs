//! Integration tests for the fetch_commits function.
//!
//! Tests the `fetch_commits` function from `src/git/commits.rs` using
//! temporary git repositories.

mod common;

use common::TestRepo;
use keryx::git::fetch_commits;

// =============================================================================
// BASIC FUNCTIONALITY TESTS
// =============================================================================

#[test]
fn test_fetch_commits_empty_range_same_commit() {
    let test_repo = TestRepo::new();

    // Create a single commit
    let commit1 = test_repo.commit("feat: initial commit");

    // Fetch commits from commit1 to commit1 (same commit = empty range)
    let commits =
        fetch_commits(&test_repo.repo, commit1, commit1, false).expect("Failed to fetch commits");

    assert!(commits.is_empty(), "Expected empty vec when from == to");
}

#[test]
fn test_fetch_commits_single_commit_range() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first commit");
    let commit2 = test_repo.commit("fix: second commit");

    // Fetch commits between commit1 and commit2
    let commits =
        fetch_commits(&test_repo.repo, commit1, commit2, false).expect("Failed to fetch commits");

    assert_eq!(commits.len(), 1);
    assert_eq!(commits[0].hash, commit2.to_string());
    assert!(commits[0].message.contains("fix: second commit"));
}

#[test]
fn test_fetch_commits_multiple_commits_range() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first commit");
    let commit2 = test_repo.commit("fix: second commit");
    let commit3 = test_repo.commit("docs: third commit");
    let commit4 = test_repo.commit("refactor: fourth commit");

    // Fetch commits between commit1 and commit4
    let commits =
        fetch_commits(&test_repo.repo, commit1, commit4, false).expect("Failed to fetch commits");

    // Should have 3 commits (2, 3, 4) - commit1 is excluded
    assert_eq!(commits.len(), 3);

    // Commits are returned in reverse chronological order (newest first)
    assert_eq!(commits[0].hash, commit4.to_string());
    assert_eq!(commits[1].hash, commit3.to_string());
    assert_eq!(commits[2].hash, commit2.to_string());
}

#[test]
fn test_fetch_commits_preserves_order() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first");
    let commit2 = test_repo.commit("feat: second");
    let commit3 = test_repo.commit("feat: third");
    let commit4 = test_repo.commit("feat: fourth");
    let commit5 = test_repo.commit("feat: fifth");

    let commits =
        fetch_commits(&test_repo.repo, commit1, commit5, false).expect("Failed to fetch commits");

    assert_eq!(commits.len(), 4);

    // Verify order is newest to oldest
    assert_eq!(commits[0].hash, commit5.to_string());
    assert_eq!(commits[1].hash, commit4.to_string());
    assert_eq!(commits[2].hash, commit3.to_string());
    assert_eq!(commits[3].hash, commit2.to_string());
}

// =============================================================================
// MERGE COMMIT TESTS
// =============================================================================

#[test]
fn test_fetch_commits_with_merge_commit() {
    let test_repo = TestRepo::new();

    // Create a linear history first
    let base = test_repo.commit("feat: base commit");
    let main_commit = test_repo.commit("feat: main commit");

    // Create a separate commit on a "feature branch" (simulated by creating commit
    // with explicit parent)
    let feature_commit = {
        // Create a commit that branches from base (not from main_commit)
        let sig = git2::Signature::now("Test User", "test@example.com").unwrap();
        let base_commit = test_repo.repo.find_commit(base).unwrap();
        let _base_tree = base_commit.tree().unwrap();

        // Create a slightly modified tree for the feature commit
        let file_path = test_repo.dir.path().join("feature.txt");
        std::fs::write(&file_path, "feature content").unwrap();

        let mut index = test_repo.repo.index().unwrap();
        index.add_path(std::path::Path::new("feature.txt")).unwrap();
        index.write().unwrap();
        let tree_id = index.write_tree().unwrap();
        let tree = test_repo.repo.find_tree(tree_id).unwrap();

        test_repo
            .repo
            .commit(
                None,
                &sig,
                &sig,
                "feat: feature commit",
                &tree,
                &[&base_commit],
            )
            .unwrap()
    };

    // Create a merge commit with main_commit as first parent
    let merge = test_repo.merge_commit("Merge branch 'feature'", main_commit, feature_commit);

    // Fetch commits from base to merge
    let commits =
        fetch_commits(&test_repo.repo, base, merge, false).expect("Failed to fetch commits");

    // Should include: merge commit, main_commit, and feature_commit (3 commits total)
    assert!(
        commits.len() >= 2,
        "Expected at least 2 commits, got {}",
        commits.len()
    );

    // The merge commit should be included
    let hashes: Vec<String> = commits.iter().map(|c| c.hash.clone()).collect();
    assert!(
        hashes.contains(&merge.to_string()),
        "Merge commit should be in results"
    );
}

// =============================================================================
// CONVENTIONAL COMMIT PARSING TESTS
// =============================================================================

#[test]
fn test_fetch_commits_parses_conventional_commits() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("chore: initial setup");
    let commit2 = test_repo.commit("feat(auth): add login feature");
    let commit3 = test_repo.commit("fix(api)!: breaking change to endpoints");

    let commits =
        fetch_commits(&test_repo.repo, commit1, commit3, false).expect("Failed to fetch commits");

    assert_eq!(commits.len(), 2);

    // Check the breaking change commit
    let breaking_commit = &commits[0];
    assert_eq!(breaking_commit.hash, commit3.to_string());
    assert!(breaking_commit.commit_type.is_some());
    assert_eq!(breaking_commit.scope, Some("api".to_string()));
    assert!(breaking_commit.breaking);

    // Check the feature commit
    let feat_commit = &commits[1];
    assert_eq!(feat_commit.hash, commit2.to_string());
    assert!(feat_commit.commit_type.is_some());
    assert_eq!(feat_commit.scope, Some("auth".to_string()));
    assert!(!feat_commit.breaking);
}

#[test]
fn test_fetch_commits_handles_non_conventional_messages() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("Initial commit");
    let _commit2 = test_repo.commit("This is not a conventional commit");
    let commit3 = test_repo.commit("Another non-standard message");

    let commits =
        fetch_commits(&test_repo.repo, commit1, commit3, false).expect("Failed to fetch commits");

    assert_eq!(commits.len(), 2);

    // Non-conventional commits should have None for commit_type
    for commit in &commits {
        assert!(commit.commit_type.is_none());
        assert!(commit.scope.is_none());
        assert!(!commit.breaking);
    }
}

// =============================================================================
// TIMESTAMP TESTS
// =============================================================================

#[test]
fn test_fetch_commits_has_timestamps() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first");
    let commit2 = test_repo.commit("feat: second");

    let commits =
        fetch_commits(&test_repo.repo, commit1, commit2, false).expect("Failed to fetch commits");

    assert_eq!(commits.len(), 1);

    // Timestamp should be set and recent
    let now = chrono::Utc::now();
    let commit_time = commits[0].timestamp;

    // The commit should have been created within the last minute
    let diff = now.signed_duration_since(commit_time);
    assert!(
        diff.num_seconds() < 60,
        "Commit timestamp should be recent, got {} seconds ago",
        diff.num_seconds()
    );
}

// =============================================================================
// EDGE CASES
// =============================================================================

#[test]
fn test_fetch_commits_with_empty_message() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: initial");
    // git2 doesn't allow truly empty messages, but we can test with whitespace
    let commit2 = test_repo.commit("   ");

    let commits =
        fetch_commits(&test_repo.repo, commit1, commit2, false).expect("Failed to fetch commits");

    assert_eq!(commits.len(), 1);
    // Should not crash, commit_type should be None
    assert!(commits[0].commit_type.is_none());
}

#[test]
fn test_fetch_commits_with_multiline_message() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: initial");
    let commit2 = test_repo.commit("feat(scope): short description\n\nThis is a longer body\nwith multiple lines\n\nBREAKING CHANGE: something changed");

    let commits =
        fetch_commits(&test_repo.repo, commit1, commit2, false).expect("Failed to fetch commits");

    assert_eq!(commits.len(), 1);
    assert!(commits[0].commit_type.is_some());
    assert_eq!(commits[0].scope, Some("scope".to_string()));
    // Should detect breaking change in footer
    assert!(commits[0].breaking);
}

#[test]
fn test_fetch_commits_with_special_characters_in_message() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("chore: setup");
    let commit2 = test_repo.commit("feat: add emoji support 🚀 and unicode: äöü");

    let commits =
        fetch_commits(&test_repo.repo, commit1, commit2, false).expect("Failed to fetch commits");

    assert_eq!(commits.len(), 1);
    assert!(commits[0].message.contains("🚀"));
    assert!(commits[0].message.contains("äöü"));
}

#[test]
fn test_fetch_commits_long_commit_history() {
    let test_repo = TestRepo::new();

    let first = test_repo.commit("feat: first commit");

    // Create 50 commits
    let mut last = first;
    for i in 2..=51 {
        last = test_repo.commit(&format!("feat: commit number {}", i));
    }

    let commits =
        fetch_commits(&test_repo.repo, first, last, false).expect("Failed to fetch commits");

    // Should have 50 commits (excluding the first)
    assert_eq!(commits.len(), 50);
}

// =============================================================================
// HASH VERIFICATION TESTS
// =============================================================================

#[test]
fn test_fetch_commits_returns_full_hashes() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first");
    let commit2 = test_repo.commit("feat: second");

    let commits =
        fetch_commits(&test_repo.repo, commit1, commit2, false).expect("Failed to fetch commits");

    assert_eq!(commits.len(), 1);
    // SHA-1 hashes are 40 characters
    assert_eq!(commits[0].hash.len(), 40);
    // Hash should match the commit OID
    assert_eq!(commits[0].hash, commit2.to_string());
}
