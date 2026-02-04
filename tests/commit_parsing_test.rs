//! Integration tests for conventional commit parsing.

use keryx::git::{CommitType, parse_commit_message};

#[test]
fn test_parse_all_commit_types() {
    let types = vec![
        ("feat: add feature", CommitType::Feat),
        ("fix: fix bug", CommitType::Fix),
        ("docs: update docs", CommitType::Docs),
        ("style: format code", CommitType::Style),
        ("refactor: restructure", CommitType::Refactor),
        ("perf: optimize query", CommitType::Perf),
        ("test: add tests", CommitType::Test),
        ("build: update deps", CommitType::Build),
        ("ci: fix pipeline", CommitType::Ci),
        ("chore: cleanup", CommitType::Chore),
    ];

    for (message, expected_type) in types {
        let (parsed_type, _, _) = parse_commit_message(message);
        assert_eq!(
            parsed_type,
            Some(expected_type),
            "Failed to parse: {}",
            message
        );
    }
}

#[test]
fn test_parse_with_various_scopes() {
    let cases = vec![
        ("feat(api): new endpoint", Some("api")),
        ("fix(ui): button alignment", Some("ui")),
        ("feat(auth/oauth): add provider", Some("auth/oauth")),
        ("fix(db-layer): connection leak", Some("db-layer")),
        ("feat: no scope", None),
    ];

    for (message, expected_scope) in cases {
        let (_, scope, _) = parse_commit_message(message);
        assert_eq!(
            scope.as_deref(),
            expected_scope,
            "Failed scope for: {}",
            message
        );
    }
}

#[test]
fn test_parse_breaking_change_variations() {
    // Breaking with exclamation after type
    let (_, _, breaking) = parse_commit_message("feat!: breaking feature");
    assert!(breaking);

    // Breaking with exclamation after scope
    let (_, _, breaking) = parse_commit_message("feat(api)!: breaking api change");
    assert!(breaking);

    // Breaking in footer (BREAKING CHANGE:)
    let (_, _, breaking) =
        parse_commit_message("feat: some change\n\nBREAKING CHANGE: this breaks stuff");
    assert!(breaking);

    // Breaking in footer (BREAKING-CHANGE:)
    let (_, _, breaking) =
        parse_commit_message("feat: some change\n\nBREAKING-CHANGE: this also breaks stuff");
    assert!(breaking);

    // Not breaking
    let (_, _, breaking) = parse_commit_message("feat: normal feature");
    assert!(!breaking);
}

#[test]
fn test_parse_case_insensitive_types() {
    let cases = vec![
        "FEAT: uppercase",
        "Feat: title case",
        "FIX: uppercase fix",
        "Fix: title case fix",
    ];

    for message in cases {
        let (commit_type, _, _) = parse_commit_message(message);
        assert!(commit_type.is_some(), "Failed to parse: {}", message);
    }
}

#[test]
fn test_parse_non_conventional_commits() {
    let non_conventional = vec![
        "Updated the README",
        "Fixed a bug",
        "WIP: work in progress",
        "Merge branch 'feature' into main",
        "Initial commit",
        "v1.0.0",
    ];

    for message in non_conventional {
        let (commit_type, scope, breaking) = parse_commit_message(message);
        assert!(
            commit_type.is_none(),
            "Should not parse as conventional: {}",
            message
        );
        assert!(scope.is_none());
        assert!(!breaking);
    }
}

#[test]
fn test_parse_multiline_commit_messages() {
    let message = r#"feat(auth): implement OAuth2 flow

This commit adds OAuth2 authentication support with the following:
- Google provider
- GitHub provider
- Token refresh logic

Closes #123"#;

    let (commit_type, scope, breaking) = parse_commit_message(message);

    assert_eq!(commit_type, Some(CommitType::Feat));
    assert_eq!(scope, Some("auth".to_string()));
    assert!(!breaking);
}

#[test]
fn test_parse_commit_with_colon_in_description() {
    let message = "fix: error: connection timeout handling";
    let (commit_type, _, _) = parse_commit_message(message);

    assert_eq!(commit_type, Some(CommitType::Fix));
}

#[test]
fn test_parse_commit_with_emoji() {
    // Some projects use emojis in commit messages
    let message = "feat: ✨ add sparkles";
    let (commit_type, _, _) = parse_commit_message(message);

    assert_eq!(commit_type, Some(CommitType::Feat));
}

#[test]
fn test_parse_empty_commit_message() {
    let (commit_type, scope, breaking) = parse_commit_message("");

    assert!(commit_type.is_none());
    assert!(scope.is_none());
    assert!(!breaking);
}

#[test]
fn test_parse_whitespace_variations() {
    // With extra spaces
    let (commit_type, _, _) = parse_commit_message("feat:   extra spaces");
    assert_eq!(commit_type, Some(CommitType::Feat));

    // No space after colon (should still work)
    let (commit_type, _, _) = parse_commit_message("feat:no space");
    assert_eq!(commit_type, Some(CommitType::Feat));
}
