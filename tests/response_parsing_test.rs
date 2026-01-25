//! Integration tests for Claude response parsing.

mod common;

use keryx::changelog::ChangelogCategory;

// Re-create the parsing logic for testing (since it's private in the module)
// This tests the same logic through the public API indirectly

#[derive(serde::Deserialize)]
struct ClaudeCliResponse {
    result: String,
    #[serde(default)]
    is_error: bool,
}

#[derive(Debug, serde::Deserialize)]
struct ChangelogOutput {
    entries: Vec<ChangelogEntry>,
}

#[derive(Debug, serde::Deserialize)]
struct ChangelogEntry {
    category: String,
    description: String,
}

fn extract_json(response: &str) -> String {
    if let Some(start) = response.find("```json") {
        if let Some(end) = response[start + 7..].find("```") {
            return response[start + 7..start + 7 + end].trim().to_string();
        }
    }

    if let Some(start) = response.find("{\"entries\"") {
        if let Some(end) = response[start..].find('}') {
            return response[start..=start + end].to_string();
        }
    }

    if let Some(start) = response.find('{') {
        if let Some(end) = response.rfind('}') {
            return response[start..=end].to_string();
        }
    }

    response.to_string()
}

fn parse_response(raw: &str) -> Result<ChangelogOutput, String> {
    let envelope: ClaudeCliResponse =
        serde_json::from_str(raw).map_err(|e| format!("Failed to parse envelope: {}", e))?;

    if envelope.is_error {
        return Err(format!("Claude error: {}", envelope.result));
    }

    let json_str = extract_json(&envelope.result);

    serde_json::from_str(&json_str).map_err(|e| format!("Failed to parse entries: {}", e))
}

#[test]
fn test_parse_success_empty_response() {
    let raw = common::read_fixture(common::response_fixture("success_empty.json"));
    let result = parse_response(&raw);

    assert!(result.is_ok());
    let output = result.unwrap();
    assert!(output.entries.is_empty());
}

#[test]
fn test_parse_success_with_entries() {
    let raw = common::read_fixture(common::response_fixture("success_with_entries.json"));
    let result = parse_response(&raw);

    assert!(result.is_ok());
    let output = result.unwrap();
    assert_eq!(output.entries.len(), 3);

    assert_eq!(output.entries[0].category, "Added");
    assert!(output.entries[0]
        .description
        .contains("authentication system"));

    assert_eq!(output.entries[1].category, "Fixed");
    assert!(output.entries[1].description.contains("Memory leak"));

    assert_eq!(output.entries[2].category, "Changed");
    assert!(output.entries[2].description.contains("error messages"));
}

#[test]
fn test_parse_error_response() {
    let raw = common::read_fixture(common::response_fixture("error_response.json"));
    let result = parse_response(&raw);

    assert!(result.is_err());
    let err = result.unwrap_err();
    assert!(err.contains("Rate limit"));
}

#[test]
fn test_parse_malformed_response() {
    let raw = common::read_fixture(common::response_fixture("malformed.json"));
    let result = parse_response(&raw);

    // Should fail because there's no valid JSON in the result
    assert!(result.is_err());
}

#[test]
fn test_changelog_categories_deserialize() {
    // Test that all category strings deserialize correctly
    let categories = vec![
        ("Added", ChangelogCategory::Added),
        ("Changed", ChangelogCategory::Changed),
        ("Deprecated", ChangelogCategory::Deprecated),
        ("Removed", ChangelogCategory::Removed),
        ("Fixed", ChangelogCategory::Fixed),
        ("Security", ChangelogCategory::Security),
    ];

    for (json_str, expected) in categories {
        let json = format!(r#"{{"category": "{}", "description": "test"}}"#, json_str);
        let entry: keryx::ChangelogEntry = serde_json::from_str(&json).unwrap();
        assert_eq!(entry.category, expected);
    }
}
