//! Shared test utilities for integration tests.
//!
//! Not all functions are used by every test file, but they're shared across tests.
#![allow(dead_code)]

use std::path::PathBuf;

use git2::{Oid, Repository, Signature};

/// Get the path to test fixtures directory.
pub fn fixtures_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures")
}

/// Get the path to a changelog fixture.
pub fn changelog_fixture(name: &str) -> PathBuf {
    fixtures_dir().join("changelogs").join(name)
}

/// Get the path to a response fixture.
pub fn response_fixture(name: &str) -> PathBuf {
    fixtures_dir().join("responses").join(name)
}

/// Get the path to a GitHub API fixture.
pub fn github_fixture(name: &str) -> PathBuf {
    fixtures_dir().join("github").join(name)
}

/// Read a fixture file as a string.
pub fn read_fixture(path: PathBuf) -> String {
    std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("Failed to read fixture {:?}: {}", path, e))
}

/// Create a temporary directory for test output.
pub fn temp_test_dir() -> tempfile::TempDir {
    tempfile::tempdir().expect("Failed to create temp directory")
}

/// A test git repository builder for integration tests.
pub struct TestRepo {
    pub dir: tempfile::TempDir,
    pub repo: Repository,
}

impl TestRepo {
    /// Create a new empty git repository in a temp directory.
    pub fn new() -> Self {
        let dir = tempfile::tempdir().expect("Failed to create temp directory");
        let repo = Repository::init(dir.path()).expect("Failed to init git repo");
        Self { dir, repo }
    }

    /// Get the test signature for commits.
    fn signature(&self) -> Signature<'_> {
        Signature::now("Test User", "test@example.com").expect("Failed to create signature")
    }

    /// Create a commit with the given message. Returns the commit OID.
    pub fn commit(&self, message: &str) -> Oid {
        let sig = self.signature();

        // Create or update a file to have something to commit
        let file_path = self.dir.path().join("test.txt");
        let content = format!(
            "{}\n{}",
            message,
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        );
        std::fs::write(&file_path, content).expect("Failed to write test file");

        // Add the file to the index
        let mut index = self.repo.index().expect("Failed to get index");
        index
            .add_path(std::path::Path::new("test.txt"))
            .expect("Failed to add file");
        index.write().expect("Failed to write index");
        let tree_id = index.write_tree().expect("Failed to write tree");
        let tree = self.repo.find_tree(tree_id).expect("Failed to find tree");

        // Get parent commit if exists
        let parent = self.repo.head().ok().and_then(|h| h.peel_to_commit().ok());

        let parents: Vec<&git2::Commit> = parent.iter().collect();

        self.repo
            .commit(Some("HEAD"), &sig, &sig, message, &tree, &parents)
            .expect("Failed to create commit")
    }

    /// Create a lightweight tag pointing to the given OID.
    pub fn tag_lightweight(&self, name: &str, oid: Oid) {
        let obj = self
            .repo
            .find_object(oid, None)
            .expect("Failed to find object");
        self.repo
            .tag_lightweight(name, &obj, false)
            .expect("Failed to create lightweight tag");
    }

    /// Create an annotated tag pointing to the given OID.
    pub fn tag_annotated(&self, name: &str, oid: Oid, message: &str) {
        let sig = self.signature();
        let obj = self
            .repo
            .find_object(oid, None)
            .expect("Failed to find object");
        self.repo
            .tag(name, &obj, &sig, message, false)
            .expect("Failed to create annotated tag");
    }

    /// Create a branch pointing to the given OID.
    pub fn branch(&self, name: &str, oid: Oid) {
        let commit = self.repo.find_commit(oid).expect("Failed to find commit");
        self.repo
            .branch(name, &commit, false)
            .expect("Failed to create branch");
    }

    /// Create a merge commit with two parents.
    /// Returns the merge commit OID. Does not update HEAD.
    pub fn merge_commit(&self, message: &str, parent1: Oid, parent2: Oid) -> Oid {
        let sig = self.signature();

        // Get both parent commits
        let parent1_commit = self
            .repo
            .find_commit(parent1)
            .expect("Failed to find parent1");
        let parent2_commit = self
            .repo
            .find_commit(parent2)
            .expect("Failed to find parent2");

        // For test purposes, just use parent1's tree (simulates a trivial merge)
        let tree = parent1_commit.tree().expect("Failed to get parent1 tree");

        // Create the merge commit without updating HEAD
        self.repo
            .commit(
                None, // Don't update any ref - avoids "first parent" check
                &sig,
                &sig,
                message,
                &tree,
                &[&parent1_commit, &parent2_commit],
            )
            .expect("Failed to create merge commit")
    }

    /// Checkout a branch by name.
    pub fn checkout_branch(&self, name: &str) {
        let branch = self
            .repo
            .find_branch(name, git2::BranchType::Local)
            .expect("Failed to find branch");
        let commit = branch.get().peel_to_commit().expect("Failed to get commit");
        self.repo
            .set_head(&format!("refs/heads/{}", name))
            .expect("Failed to set head");
        self.repo
            .checkout_tree(commit.as_object(), None)
            .expect("Failed to checkout");
    }
}
