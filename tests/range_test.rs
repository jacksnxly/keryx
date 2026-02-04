//! Integration tests for commit range resolution.
//!
//! Tests the `resolve_range` function from `src/git/range.rs` using
//! temporary git repositories.

mod common;

use common::TestRepo;
use keryx::git::range::resolve_range;

#[test]
fn test_resolve_range_with_explicit_from_to() {
    let test_repo = TestRepo::new();

    // Create commits
    let commit1 = test_repo.commit("feat: first commit");
    let commit2 = test_repo.commit("feat: second commit");
    let commit3 = test_repo.commit("feat: third commit");

    // Resolve with explicit commit SHAs
    let range = resolve_range(
        &test_repo.repo,
        Some(&commit1.to_string()),
        Some(&commit3.to_string()),
        false,
    )
    .expect("Failed to resolve range");

    assert_eq!(range.from, commit1);
    assert_eq!(range.to, commit3);
    assert_eq!(range.from_ref, commit1.to_string());
    assert_eq!(range.to_ref, commit3.to_string());

    // Verify commit2 is in the middle (just to confirm our setup)
    assert_ne!(commit1, commit2);
    assert_ne!(commit2, commit3);
}

#[test]
fn test_resolve_range_head_as_default_to() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first commit");
    let commit2 = test_repo.commit("feat: second commit");

    // Resolve with explicit from, default to (HEAD)
    let range = resolve_range(&test_repo.repo, Some(&commit1.to_string()), None, false)
        .expect("Failed to resolve range");

    assert_eq!(range.from, commit1);
    assert_eq!(range.to, commit2); // HEAD should point to latest commit
    assert_eq!(range.to_ref, "HEAD");
}

#[test]
fn test_resolve_range_fallback_to_root_commit() {
    let test_repo = TestRepo::new();

    // Create commits but no tags
    let root_commit = test_repo.commit("feat: root commit");
    let _commit2 = test_repo.commit("feat: second commit");
    let commit3 = test_repo.commit("feat: third commit");

    // Resolve with no from (should fall back to root commit)
    let range = resolve_range(&test_repo.repo, None, None, false).expect("Failed to resolve range");

    assert_eq!(range.from, root_commit);
    assert_eq!(range.from_ref, "root");
    assert_eq!(range.to, commit3); // HEAD
    assert_eq!(range.to_ref, "HEAD");
}

#[test]
fn test_resolve_range_with_lightweight_tag() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first commit");
    test_repo.tag_lightweight("v1.0.0", commit1);

    let commit2 = test_repo.commit("feat: second commit");

    // Resolve with no from (should use latest tag)
    let range = resolve_range(&test_repo.repo, None, None, false).expect("Failed to resolve range");

    assert_eq!(range.from, commit1);
    assert_eq!(range.from_ref, "v1.0.0");
    assert_eq!(range.to, commit2);
}

#[test]
fn test_resolve_range_with_annotated_tag() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first commit");
    test_repo.tag_annotated("v1.0.0", commit1, "Release 1.0.0");

    let commit2 = test_repo.commit("feat: second commit");

    // Resolve with no from (should use latest annotated tag)
    let range = resolve_range(&test_repo.repo, None, None, false).expect("Failed to resolve range");

    assert_eq!(range.from, commit1);
    assert_eq!(range.from_ref, "v1.0.0");
    assert_eq!(range.to, commit2);
}

#[test]
fn test_resolve_range_selects_latest_semver_tag() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first commit");
    test_repo.tag_lightweight("v1.0.0", commit1);

    let commit2 = test_repo.commit("feat: second commit");
    test_repo.tag_lightweight("v1.1.0", commit2);

    let commit3 = test_repo.commit("feat: third commit");
    test_repo.tag_lightweight("v2.0.0", commit3);

    let commit4 = test_repo.commit("feat: fourth commit");

    // Resolve with no from (should use v2.0.0 as latest)
    let range = resolve_range(&test_repo.repo, None, None, false).expect("Failed to resolve range");

    assert_eq!(range.from, commit3);
    assert_eq!(range.from_ref, "v2.0.0");
    assert_eq!(range.to, commit4);
}

#[test]
fn test_resolve_range_with_tag_reference() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first commit");
    test_repo.tag_lightweight("v1.0.0", commit1);

    let commit2 = test_repo.commit("feat: second commit");
    test_repo.tag_lightweight("v2.0.0", commit2);

    let _commit3 = test_repo.commit("feat: third commit");

    // Resolve using tag names as references
    let range = resolve_range(&test_repo.repo, Some("v1.0.0"), Some("v2.0.0"), false)
        .expect("Failed to resolve range");

    assert_eq!(range.from, commit1);
    assert_eq!(range.to, commit2);
    assert_eq!(range.from_ref, "v1.0.0");
    assert_eq!(range.to_ref, "v2.0.0");
}

#[test]
fn test_resolve_range_with_branch_reference() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first commit");
    test_repo.branch("feature-branch", commit1);

    let commit2 = test_repo.commit("feat: second commit");

    // Resolve using branch name as from reference
    let range = resolve_range(&test_repo.repo, Some("feature-branch"), Some("HEAD"), false)
        .expect("Failed to resolve range");

    assert_eq!(range.from, commit1);
    assert_eq!(range.to, commit2);
    assert_eq!(range.from_ref, "feature-branch");
}

#[test]
fn test_resolve_range_invalid_from_reference() {
    let test_repo = TestRepo::new();
    test_repo.commit("feat: first commit");

    let result = resolve_range(&test_repo.repo, Some("nonexistent-ref"), None, false);

    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(err.to_string().contains("nonexistent-ref"));
}

#[test]
fn test_resolve_range_invalid_to_reference() {
    let test_repo = TestRepo::new();
    let commit1 = test_repo.commit("feat: first commit");

    let result = resolve_range(
        &test_repo.repo,
        Some(&commit1.to_string()),
        Some("nonexistent-ref"),
        false,
    );

    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(err.to_string().contains("nonexistent-ref"));
}

#[test]
fn test_resolve_range_with_short_sha() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first commit");
    let commit2 = test_repo.commit("feat: second commit");

    // Use full SHA (short SHA resolution depends on uniqueness in repo)
    let range = resolve_range(
        &test_repo.repo,
        Some(&commit1.to_string()),
        Some(&commit2.to_string()),
        false,
    )
    .expect("Failed to resolve range");

    assert_eq!(range.from, commit1);
    assert_eq!(range.to, commit2);
}

#[test]
fn test_resolve_range_ignores_non_semver_tags() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first commit");
    test_repo.tag_lightweight("release-candidate", commit1);

    let commit2 = test_repo.commit("feat: second commit");
    test_repo.tag_lightweight("latest", commit2);

    let commit3 = test_repo.commit("feat: third commit");

    // No semver tags, should fall back to root
    let range = resolve_range(&test_repo.repo, None, None, false).expect("Failed to resolve range");

    assert_eq!(range.from, commit1); // Root commit
    assert_eq!(range.from_ref, "root");
    assert_eq!(range.to, commit3);
}

#[test]
fn test_resolve_range_mixed_semver_and_non_semver_tags() {
    let test_repo = TestRepo::new();

    let commit1 = test_repo.commit("feat: first commit");
    test_repo.tag_lightweight("initial", commit1);

    let commit2 = test_repo.commit("feat: second commit");
    test_repo.tag_lightweight("v1.0.0", commit2);

    let commit3 = test_repo.commit("feat: third commit");
    test_repo.tag_lightweight("beta", commit3);

    let commit4 = test_repo.commit("feat: fourth commit");

    // Should use v1.0.0 (only semver tag)
    let range = resolve_range(&test_repo.repo, None, None, false).expect("Failed to resolve range");

    assert_eq!(range.from, commit2);
    assert_eq!(range.from_ref, "v1.0.0");
    assert_eq!(range.to, commit4);
}
