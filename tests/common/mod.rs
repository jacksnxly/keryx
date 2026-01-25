//! Shared test utilities for integration tests.

use std::path::PathBuf;

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

/// Read a fixture file as a string.
pub fn read_fixture(path: PathBuf) -> String {
    std::fs::read_to_string(&path)
        .unwrap_or_else(|e| panic!("Failed to read fixture {:?}: {}", path, e))
}

/// Create a temporary directory for test output.
pub fn temp_test_dir() -> tempfile::TempDir {
    tempfile::tempdir().expect("Failed to create temp directory")
}
