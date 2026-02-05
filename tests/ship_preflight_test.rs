mod common;

use std::path::PathBuf;
use std::process::Command;

use serial_test::serial;

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

    let status = Command::new("git")
        .args(["push", "origin", &format!("HEAD:refs/heads/{}", branch)])
        .status()
        .expect("Failed to push to origin");
    assert!(status.success(), "git push failed in test setup");

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

    let status = Command::new("git")
        .args(["push", "origin", &format!("HEAD:refs/heads/{}", branch)])
        .status()
        .expect("Failed to push to origin");
    assert!(status.success(), "git push failed in test setup");

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
