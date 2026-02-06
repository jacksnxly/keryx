mod common;

use std::path::PathBuf;
use std::process::Command;

use serial_test::serial;

use keryx::ShipError;
use keryx::llm::ProviderSelection;
use keryx::ship::preflight::run_checks;

use common::TestRepo;

struct DirGuard {
    original: PathBuf,
}

impl DirGuard {
    fn new(original: PathBuf) -> Self {
        Self { original }
    }
}

impl Drop for DirGuard {
    fn drop(&mut self) {
        let _ = std::env::set_current_dir(&self.original);
    }
}

fn run_git(args: &[&str]) {
    let status = Command::new("git")
        .args(args)
        .status()
        .expect("Failed to run git command in test");
    assert!(
        status.success(),
        "git command failed: git {}",
        args.join(" ")
    );
}

#[test]
#[serial]
fn test_preflight_single_commit_initial_repo() {
    let repo = TestRepo::new();
    repo.commit("feat: initial commit");

    let remote_dir = tempfile::tempdir().expect("Failed to create remote dir");
    git2::Repository::init_bare(remote_dir.path()).expect("Failed to init bare repo");

    repo.repo
        .remote(
            "origin",
            remote_dir.path().to_str().expect("Invalid remote path"),
        )
        .expect("Failed to add origin remote");

    let original_dir = std::env::current_dir().expect("Failed to get current dir");
    std::env::set_current_dir(repo.dir.path()).expect("Failed to change to repo dir");
    let _guard = DirGuard::new(original_dir);

    let branch = repo
        .repo
        .head()
        .ok()
        .and_then(|h| h.shorthand().map(|s| s.to_string()))
        .unwrap_or_else(|| "master".to_string());

    run_git(&[
        "push",
        "-u",
        "origin",
        &format!("HEAD:refs/heads/{}", branch),
    ]);

    let result = run_checks(&repo.repo, false, ProviderSelection::default(), false)
        .expect("preflight should succeed for single-commit repo");

    assert!(result.latest_tag.is_none());
    assert_eq!(result.commits_since_tag.len(), 1);
}

#[test]
#[serial]
fn test_preflight_multi_commit_initial_repo_includes_root() {
    let repo = TestRepo::new();
    repo.commit("feat: first commit");
    repo.commit("feat: second commit");

    let remote_dir = tempfile::tempdir().expect("Failed to create remote dir");
    git2::Repository::init_bare(remote_dir.path()).expect("Failed to init bare repo");

    repo.repo
        .remote(
            "origin",
            remote_dir.path().to_str().expect("Invalid remote path"),
        )
        .expect("Failed to add origin remote");

    let original_dir = std::env::current_dir().expect("Failed to get current dir");
    std::env::set_current_dir(repo.dir.path()).expect("Failed to change to repo dir");
    let _guard = DirGuard::new(original_dir);

    let branch = repo
        .repo
        .head()
        .ok()
        .and_then(|h| h.shorthand().map(|s| s.to_string()))
        .unwrap_or_else(|| "master".to_string());

    run_git(&[
        "push",
        "-u",
        "origin",
        &format!("HEAD:refs/heads/{}", branch),
    ]);

    let result = run_checks(&repo.repo, false, ProviderSelection::default(), false)
        .expect("preflight should succeed for multi-commit repo");

    assert!(result.latest_tag.is_none());
    assert_eq!(result.commits_since_tag.len(), 2);

    let messages: Vec<&str> = result
        .commits_since_tag
        .iter()
        .map(|c| c.message.as_str())
        .collect();
    assert!(messages.iter().any(|m| m.contains("feat: first commit")));
    assert!(messages.iter().any(|m| m.contains("feat: second commit")));
}

#[test]
#[serial]
fn test_preflight_fails_on_detached_head() {
    let repo = TestRepo::new();
    let commit_oid = repo.commit("feat: initial commit");

    repo.repo
        .set_head_detached(commit_oid)
        .expect("Failed to detach HEAD");

    let commit = repo
        .repo
        .find_commit(commit_oid)
        .expect("Failed to find detached commit");
    repo.repo
        .checkout_tree(commit.as_object(), None)
        .expect("Failed to checkout detached commit");

    let original_dir = std::env::current_dir().expect("Failed to get current dir");
    std::env::set_current_dir(repo.dir.path()).expect("Failed to change to repo dir");
    let _guard = DirGuard::new(original_dir);

    let result = run_checks(&repo.repo, false, ProviderSelection::default(), false);
    assert!(matches!(result, Err(ShipError::DetachedHead)));
}

#[test]
#[serial]
fn test_preflight_respects_tracked_upstream_when_branch_names_differ() {
    let repo = TestRepo::new();
    repo.commit("feat: initial commit");

    let remote_dir = tempfile::tempdir().expect("Failed to create remote dir");
    git2::Repository::init_bare(remote_dir.path()).expect("Failed to init bare repo");

    repo.repo
        .remote(
            "origin",
            remote_dir.path().to_str().expect("Invalid remote path"),
        )
        .expect("Failed to add origin remote");

    let original_dir = std::env::current_dir().expect("Failed to get current dir");
    std::env::set_current_dir(repo.dir.path()).expect("Failed to change to repo dir");
    let _guard = DirGuard::new(original_dir);

    let local_branch = repo
        .repo
        .head()
        .ok()
        .and_then(|h| h.shorthand().map(|s| s.to_string()))
        .unwrap_or_else(|| "master".to_string());

    // Create origin/main and set upstream on the local default branch.
    run_git(&["push", "-u", "origin", "HEAD:refs/heads/main"]);
    // Create a release branch that tracks origin/main.
    run_git(&["switch", "-c", "release", "--track", "origin/main"]);
    // Ensure shell `git commit` works in CI environments without global identity.
    run_git(&["config", "user.name", "Test User"]);
    run_git(&["config", "user.email", "test@example.com"]);

    // Advance origin/main while keeping release behind.
    run_git(&["switch", &local_branch]);
    std::fs::write(repo.dir.path().join("tracked.txt"), "remote moves ahead\n")
        .expect("Failed to write tracked test file");
    run_git(&["add", "tracked.txt"]);
    run_git(&["commit", "-m", "feat: upstream commit"]);
    run_git(&["push", "origin", "HEAD:refs/heads/main"]);
    run_git(&["switch", "release"]);

    let result = run_checks(&repo.repo, false, ProviderSelection::default(), false);
    assert!(matches!(result, Err(ShipError::BehindRemote)));
}
