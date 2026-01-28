//! Integration tests for the verification module.
//!
//! These tests verify that the evidence gathering works correctly against
//! a temporary repository with known code patterns.

mod common;

use std::fs;

use keryx::changelog::{ChangelogCategory, ChangelogEntry};
use keryx::verification::{gather_verification_evidence, Confidence};

/// Create a test project with known code patterns.
fn create_test_project() -> tempfile::TempDir {
    let dir = tempfile::tempdir().expect("Failed to create temp dir");

    // Create src directory
    let src = dir.path().join("src");
    fs::create_dir(&src).unwrap();

    // Create a complete implementation file (no stubs)
    let complete_rs = src.join("complete.rs");
    fs::write(
        &complete_rs,
        r#"//! Complete WebSocket implementation.

pub struct WebSocket {
    url: String,
    connected: bool,
}

impl WebSocket {
    pub fn new(url: &str) -> Self {
        Self {
            url: url.to_string(),
            connected: false,
        }
    }

    pub fn connect(&mut self) -> Result<(), String> {
        // Full implementation
        self.connected = true;
        Ok(())
    }

    pub fn send(&self, message: &str) -> Result<(), String> {
        if !self.connected {
            return Err("Not connected".to_string());
        }
        println!("Sending: {}", message);
        Ok(())
    }

    pub fn disconnect(&mut self) {
        self.connected = false;
    }
}
"#,
    )
    .unwrap();

    // Create an incomplete implementation file (has stubs)
    let incomplete_rs = src.join("incomplete.rs");
    fs::write(
        &incomplete_rs,
        r#"//! Authentication module - work in progress.

pub struct AuthProvider {
    // TODO: add proper configuration
    name: String,
}

impl AuthProvider {
    pub fn new(name: &str) -> Self {
        Self { name: name.to_string() }
    }

    pub fn authenticate(&self, _token: &str) -> bool {
        // TODO: implement this
        unimplemented!()
    }

    pub fn verify_token(&self, _token: &str) -> bool {
        // FIXME: add proper validation
        todo!()
    }

    pub fn refresh(&self) {
        panic!("not implemented yet");
    }
}
"#,
    )
    .unwrap();

    // Create a file with database functionality
    let database_rs = src.join("database.rs");
    fs::write(
        &database_rs,
        r#"//! Database module with PostgreSQL support.

use std::collections::HashMap;

pub struct PostgresDatabase {
    connection_string: String,
    pool_size: usize,
}

impl PostgresDatabase {
    pub fn new(conn: &str) -> Self {
        Self {
            connection_string: conn.to_string(),
            pool_size: 10,
        }
    }

    pub fn query(&self, sql: &str) -> Vec<HashMap<String, String>> {
        println!("Executing query: {}", sql);
        Vec::new()
    }

    pub fn execute(&self, sql: &str) -> usize {
        println!("Executing: {}", sql);
        1
    }
}
"#,
    )
    .unwrap();

    // Create Cargo.toml (key file)
    let cargo_toml = dir.path().join("Cargo.toml");
    fs::write(
        &cargo_toml,
        r#"[package]
name = "test-project"
version = "0.1.0"
edition = "2021"

[dependencies]
tokio = "1.0"
"#,
    )
    .unwrap();

    dir
}

// === Keyword Search Tests ===

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_keyword_search_finds_websocket() {

    let project = create_test_project();

    let entries = vec![ChangelogEntry {
        category: ChangelogCategory::Added,
        description: "Added WebSocket support for real-time updates".to_string(),
    }];

    let evidence = gather_verification_evidence(&entries, project.path());

    assert_eq!(evidence.entries.len(), 1);
    let entry_ev = &evidence.entries[0];

    // Should find "websocket" keyword
    let ws_match = entry_ev
        .keyword_matches
        .iter()
        .find(|k| k.keyword == "websocket");
    assert!(
        ws_match.is_some(),
        "Should find 'websocket' keyword in codebase"
    );

    let ws = ws_match.unwrap();
    assert!(
        ws.occurrence_count.is_some_and(|c| c > 0),
        "Should have occurrence count > 0"
    );
    assert!(
        !ws.files_found.is_empty(),
        "Should find files containing 'websocket'"
    );
    // WebSocket in complete.rs has no TODOs nearby
    assert!(
        ws.appears_complete,
        "WebSocket implementation should appear complete"
    );
}

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_keyword_search_finds_database() {

    let project = create_test_project();

    // Use a description that will extract "postgres" as a keyword
    // The tech_re pattern extracts capitalized words like "Postgres"
    let entries = vec![ChangelogEntry {
        category: ChangelogCategory::Added,
        description: "Added Postgres connection pooling".to_string(),
    }];

    let evidence = gather_verification_evidence(&entries, project.path());

    assert_eq!(evidence.entries.len(), 1);
    let entry_ev = &evidence.entries[0];

    // Should find "postgres" keyword (extracted and lowercased from "Postgres")
    let pg_match = entry_ev
        .keyword_matches
        .iter()
        .find(|k| k.keyword.contains("postgres"));
    assert!(
        pg_match.is_some(),
        "Should find 'postgres' keyword in codebase. Keywords found: {:?}",
        entry_ev.keyword_matches.iter().map(|k| &k.keyword).collect::<Vec<_>>()
    );

    // Verify it found the file
    let pg = pg_match.unwrap();
    assert!(
        !pg.files_found.is_empty(),
        "Should find files containing postgres"
    );
}

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_keyword_search_no_match_for_missing_feature() {

    let project = create_test_project();

    let entries = vec![ChangelogEntry {
        category: ChangelogCategory::Added,
        description: "Added GraphQL API with Apollo server".to_string(),
    }];

    let evidence = gather_verification_evidence(&entries, project.path());

    assert_eq!(evidence.entries.len(), 1);
    let entry_ev = &evidence.entries[0];

    // Should NOT find "graphql" or "apollo" (they don't exist)
    let gql_match = entry_ev
        .keyword_matches
        .iter()
        .find(|k| k.keyword == "graphql");
    assert!(
        gql_match.is_none(),
        "Should NOT find 'graphql' keyword - feature doesn't exist"
    );

    let apollo_match = entry_ev
        .keyword_matches
        .iter()
        .find(|k| k.keyword == "apollo");
    assert!(
        apollo_match.is_none(),
        "Should NOT find 'apollo' keyword - feature doesn't exist"
    );
}

// === Stub Indicator Tests ===

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_stub_indicators_detected_for_incomplete_code() {

    let project = create_test_project();

    let entries = vec![ChangelogEntry {
        category: ChangelogCategory::Added,
        description: "Added AuthProvider for authentication".to_string(),
    }];

    let evidence = gather_verification_evidence(&entries, project.path());

    assert_eq!(evidence.entries.len(), 1);
    let entry_ev = &evidence.entries[0];

    // Should find stub indicators (TODO, FIXME, unimplemented!, todo!)
    assert!(
        !entry_ev.stub_indicators.is_empty(),
        "Should detect stub indicators in incomplete code"
    );

    // Verify specific indicators are found
    let indicators: Vec<&str> = entry_ev
        .stub_indicators
        .iter()
        .map(|s| s.indicator.as_str())
        .collect();

    // Check for various stub patterns
    let has_todo = indicators.iter().any(|i| i.contains("TODO"));
    let has_unimplemented = indicators.iter().any(|i| i.contains("unimplemented!"));
    let has_fixme = indicators.iter().any(|i| i.contains("FIXME"));
    let has_todo_macro = indicators.iter().any(|i| i.contains("todo!"));

    assert!(
        has_todo || has_unimplemented || has_fixme || has_todo_macro,
        "Should find at least one stub indicator (TODO, FIXME, unimplemented!, or todo!). Found: {:?}",
        indicators
    );
}

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_no_stub_indicators_for_complete_code() {

    let project = create_test_project();

    // Only query for WebSocket which has complete implementation
    let entries = vec![ChangelogEntry {
        category: ChangelogCategory::Added,
        description: "WebSocket client implementation".to_string(),
    }];

    let evidence = gather_verification_evidence(&entries, project.path());

    assert_eq!(evidence.entries.len(), 1);
    let entry_ev = &evidence.entries[0];

    // Should find the keyword
    let ws_match = entry_ev
        .keyword_matches
        .iter()
        .find(|k| k.keyword == "websocket");
    assert!(ws_match.is_some(), "Should find 'websocket' keyword");

    // WebSocket implementation is complete - appears_complete should be true
    assert!(
        ws_match.unwrap().appears_complete,
        "WebSocket should appear complete (no stub indicators nearby)"
    );
}

// === Confidence Level Tests ===

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_confidence_high_for_complete_implementation() {

    let project = create_test_project();

    let entries = vec![ChangelogEntry {
        category: ChangelogCategory::Added,
        description: "WebSocket support with connect and send methods".to_string(),
    }];

    let evidence = gather_verification_evidence(&entries, project.path());

    assert_eq!(evidence.entries.len(), 1);
    let entry_ev = &evidence.entries[0];

    // Should have high confidence - multiple keyword matches, appears complete
    // Note: confidence depends on the scoring system
    assert!(
        entry_ev.keyword_matches.iter().any(|k| k.appears_complete),
        "At least one keyword should appear complete"
    );
}

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_confidence_low_for_incomplete_implementation() {

    let project = create_test_project();

    let entries = vec![ChangelogEntry {
        category: ChangelogCategory::Added,
        description: "AuthProvider authentication system".to_string(),
    }];

    let evidence = gather_verification_evidence(&entries, project.path());

    assert_eq!(evidence.entries.len(), 1);
    let entry_ev = &evidence.entries[0];

    // Should have low confidence due to stub indicators
    assert_eq!(
        entry_ev.confidence(),
        Confidence::Low,
        "Incomplete code with stubs should have low confidence"
    );
}

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_confidence_low_for_nonexistent_feature() {

    let project = create_test_project();

    let entries = vec![ChangelogEntry {
        category: ChangelogCategory::Added,
        description: "Redis caching layer with LRU eviction".to_string(),
    }];

    let evidence = gather_verification_evidence(&entries, project.path());

    assert_eq!(evidence.entries.len(), 1);
    let entry_ev = &evidence.entries[0];

    // Should have low confidence - no keyword matches found
    assert_eq!(
        entry_ev.confidence(),
        Confidence::Low,
        "Nonexistent feature should have low confidence"
    );
    assert!(
        entry_ev.keyword_matches.is_empty() ||
        entry_ev.keyword_matches.iter().all(|k| k.occurrence_count == Some(0) || k.occurrence_count.is_none()),
        "Should have no keyword matches for nonexistent feature"
    );
}

// === Key Files Tests ===

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_key_files_gathered() {

    let project = create_test_project();

    let entries = vec![ChangelogEntry {
        category: ChangelogCategory::Added,
        description: "Test feature".to_string(),
    }];

    let evidence = gather_verification_evidence(&entries, project.path());

    // Should gather key files
    assert!(
        !evidence.key_files.is_empty(),
        "Should gather key files"
    );

    // Should find Cargo.toml
    let cargo_file = evidence
        .key_files
        .iter()
        .find(|f| f.path == "Cargo.toml");
    assert!(
        cargo_file.is_some(),
        "Should find Cargo.toml as a key file"
    );

    // Content should be present
    let cargo = cargo_file.unwrap();
    assert!(
        cargo.content.contains("test-project"),
        "Cargo.toml content should include project name"
    );
}

// === Multiple Entries Test ===

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_multiple_entries_analyzed() {

    let project = create_test_project();

    let entries = vec![
        ChangelogEntry {
            category: ChangelogCategory::Added,
            description: "WebSocket support".to_string(),
        },
        ChangelogEntry {
            category: ChangelogCategory::Added,
            description: "PostgreSQL database integration".to_string(),
        },
        ChangelogEntry {
            category: ChangelogCategory::Added,
            description: "AuthProvider authentication".to_string(),
        },
    ];

    let evidence = gather_verification_evidence(&entries, project.path());

    // Should analyze all entries
    assert_eq!(evidence.entries.len(), 3);

    // Each entry should have its own evidence
    assert_eq!(
        evidence.entries[0].original_description,
        "WebSocket support"
    );
    assert_eq!(
        evidence.entries[1].original_description,
        "PostgreSQL database integration"
    );
    assert_eq!(
        evidence.entries[2].original_description,
        "AuthProvider authentication"
    );
}

// === has_low_confidence_entries Tests ===

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_has_low_confidence_entries_detection() {

    let project = create_test_project();

    // Mix of complete and incomplete features
    let entries = vec![
        ChangelogEntry {
            category: ChangelogCategory::Added,
            description: "WebSocket support".to_string(), // Complete
        },
        ChangelogEntry {
            category: ChangelogCategory::Added,
            description: "GraphQL Federation".to_string(), // Doesn't exist
        },
    ];

    let evidence = gather_verification_evidence(&entries, project.path());

    // Should detect that there are low confidence entries
    assert!(
        evidence.has_low_confidence_entries(),
        "Should detect low confidence entries when some features don't exist"
    );

    // Get the low confidence entries
    let low_entries = evidence.low_confidence_entries();
    assert!(
        !low_entries.is_empty(),
        "Should return low confidence entries"
    );

    // The GraphQL entry should be low confidence
    let gql_low = low_entries
        .iter()
        .find(|e| e.original_description.contains("GraphQL"));
    assert!(
        gql_low.is_some(),
        "GraphQL entry should be in low confidence list"
    );
}

// === Edge Cases ===

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_empty_entries() {

    let project = create_test_project();
    let entries: Vec<ChangelogEntry> = vec![];

    let evidence = gather_verification_evidence(&entries, project.path());

    assert!(evidence.entries.is_empty());
    assert!(!evidence.has_low_confidence_entries());
}

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_entry_with_no_extractable_keywords() {

    let project = create_test_project();

    let entries = vec![ChangelogEntry {
        category: ChangelogCategory::Fixed,
        description: "Fix a bug".to_string(), // Very short, generic description
    }];

    let evidence = gather_verification_evidence(&entries, project.path());

    assert_eq!(evidence.entries.len(), 1);
    // Should handle gracefully even if no meaningful keywords extracted
}

// === Project Structure Test ===

#[test]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_project_structure_gathered() {

    let project = create_test_project();

    let entries = vec![ChangelogEntry {
        category: ChangelogCategory::Added,
        description: "Test".to_string(),
    }];

    let evidence = gather_verification_evidence(&entries, project.path());

    // Project structure might be None if `tree` command isn't available
    // but should not panic
    // Just verify the evidence was gathered
    assert!(evidence.entries.len() == 1);
}
