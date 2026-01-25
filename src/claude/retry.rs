//! Exponential backoff retry logic for Claude CLI.

use std::time::Duration;

use backoff::backoff::Backoff;
use backoff::ExponentialBackoff;

use crate::changelog::ChangelogOutput;
use crate::error::ClaudeError;

use super::subprocess::run_claude;

/// Configuration per spec: 3 retries, base 1s, max 30s.
const MAX_RETRIES: u32 = 3;
const INITIAL_INTERVAL_SECS: u64 = 1;
const MAX_INTERVAL_SECS: u64 = 30;

/// Generate changelog entries with retry logic.
///
/// Retries up to 3 times with exponential backoff on failure.
pub async fn generate_with_retry(prompt: &str) -> Result<ChangelogOutput, ClaudeError> {
    let mut backoff = ExponentialBackoff {
        initial_interval: Duration::from_secs(INITIAL_INTERVAL_SECS),
        max_interval: Duration::from_secs(MAX_INTERVAL_SECS),
        max_elapsed_time: None, // We control retries manually
        ..Default::default()
    };

    let mut attempts = 0;
    let mut last_error = None;

    while attempts < MAX_RETRIES {
        attempts += 1;

        match try_generate(prompt).await {
            Ok(output) => return Ok(output),
            Err(e) => {
                last_error = Some(e);

                if attempts < MAX_RETRIES {
                    if let Some(wait_duration) = backoff.next_backoff() {
                        tokio::time::sleep(wait_duration).await;
                    }
                }
            }
        }
    }

    // All retries exhausted
    if let Some(e) = last_error {
        // Log the actual error for debugging
        eprintln!("All {} retry attempts failed. Last error: {}", MAX_RETRIES, e);
    }

    Err(ClaudeError::RetriesExhausted)
}

/// Single attempt to generate changelog.
async fn try_generate(prompt: &str) -> Result<ChangelogOutput, ClaudeError> {
    let response = run_claude(prompt).await?;

    // Parse the JSON response
    parse_claude_response(&response)
}

/// Claude CLI JSON envelope when using --output-format json
#[derive(serde::Deserialize)]
struct ClaudeCliResponse {
    result: String,
    #[serde(default)]
    is_error: bool,
}

/// Parse Claude's JSON response into ChangelogOutput.
fn parse_claude_response(response: &str) -> Result<ChangelogOutput, ClaudeError> {
    // First, try to parse as Claude CLI JSON envelope
    let content = if let Ok(envelope) = serde_json::from_str::<ClaudeCliResponse>(response) {
        if envelope.is_error {
            return Err(ClaudeError::ExecutionFailed(envelope.result));
        }
        envelope.result
    } else {
        // Fallback: treat as raw response
        response.to_string()
    };

    // Now extract the changelog JSON from Claude's response text
    let json_str = extract_json(&content);

    serde_json::from_str(&json_str)
        .map_err(|e| ClaudeError::InvalidJson(format!("Failed to parse: {}. Content: {}", e, content)))
}

/// Extract JSON from Claude's response (may be wrapped in markdown).
///
/// Uses proper JSON parsing to handle nested objects correctly.
fn extract_json(response: &str) -> String {
    // Try to find JSON block in markdown first
    if let Some(start) = response.find("```json") {
        if let Some(end) = response[start + 7..].find("```") {
            return response[start + 7..start + 7 + end].trim().to_string();
        }
    }

    // Use proper JSON parsing to find valid JSON objects
    // This handles nested braces correctly
    if let Some(json_str) = find_valid_json_object(response) {
        return json_str;
    }

    response.to_string()
}

/// Find a valid JSON object in a string using proper brace matching.
///
/// This solves the nested JSON bug where simple `find('}')` would match
/// the wrong closing brace in nested structures like `{"entries": [{"a": 1}]}`.
fn find_valid_json_object(text: &str) -> Option<String> {
    // Find all potential JSON start positions
    for (start_idx, _) in text.match_indices('{') {
        let candidate = &text[start_idx..];

        // Try to parse as JSON - serde_json handles nested braces correctly
        // Use serde_json::Value to accept any valid JSON structure
        if let Ok(value) = serde_json::from_str::<serde_json::Value>(candidate) {
            // Re-serialize to get the exact JSON portion
            // This ensures we return valid JSON even if there's trailing text
            if let Ok(json_str) = serde_json::to_string(&value) {
                return Some(json_str);
            }
        }

        // If full parse fails, try to find where this JSON object ends
        // by counting balanced braces
        if let Some(json_str) = extract_balanced_braces(candidate) {
            // Validate the extracted string is valid JSON
            if serde_json::from_str::<serde_json::Value>(&json_str).is_ok() {
                return Some(json_str);
            }
        }
    }

    None
}

/// Extract a substring with balanced braces starting from the first '{'.
fn extract_balanced_braces(text: &str) -> Option<String> {
    let mut depth = 0;
    let mut in_string = false;
    let mut escape_next = false;

    for (idx, ch) in text.char_indices() {
        if escape_next {
            escape_next = false;
            continue;
        }

        match ch {
            '\\' if in_string => escape_next = true,
            '"' => in_string = !in_string,
            '{' if !in_string => depth += 1,
            '}' if !in_string => {
                depth -= 1;
                if depth == 0 {
                    return Some(text[..=idx].to_string());
                }
            }
            _ => {}
        }
    }

    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_extract_json_from_markdown() {
        let response = r#"Here's the JSON:
```json
{"entries": []}
```"#;
        let json = extract_json(response);
        assert_eq!(json, r#"{"entries": []}"#);
    }

    #[test]
    fn test_extract_raw_json() {
        let response = r#"{"entries": []}"#;
        let json = extract_json(response);
        assert_eq!(json, r#"{"entries":[]}"#); // serde normalizes whitespace
    }

    #[test]
    fn test_extract_json_with_surrounding_text() {
        let response = r#"Here is the result: {"entries": []} Hope this helps!"#;
        let json = extract_json(response);
        // Verify it's valid JSON and has the right structure
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert!(parsed["entries"].is_array());
        assert_eq!(parsed["entries"].as_array().unwrap().len(), 0);
    }

    /// Issue #1 fix: Test nested JSON extraction (the bug that found wrong closing brace)
    #[test]
    fn test_extract_nested_json_correctly() {
        // This was the bug: find('}') would find the first '}' inside the nested object
        let response = r#"{"entries": [{"category": "Added", "description": "Test"}]}"#;
        let json = extract_json(response);

        // Parse to verify it's valid and complete
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert!(parsed["entries"].is_array());
        assert_eq!(parsed["entries"][0]["category"], "Added");
    }

    /// Test deeply nested JSON structures
    #[test]
    fn test_extract_deeply_nested_json() {
        let response = r#"Result: {"entries": [{"category": "Added", "metadata": {"author": {"name": "John"}}}]} done"#;
        let json = extract_json(response);

        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed["entries"][0]["metadata"]["author"]["name"], "John");
    }

    /// Test JSON with escaped quotes inside strings
    #[test]
    fn test_extract_json_with_escaped_quotes() {
        let response = r#"{"entries": [{"description": "Added \"new\" feature"}]}"#;
        let json = extract_json(response);

        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert!(parsed["entries"][0]["description"].as_str().unwrap().contains("\"new\""));
    }

    #[test]
    fn test_parse_claude_cli_envelope() {
        let response = r#"{"type":"result","subtype":"success","is_error":false,"result":"```json\n{\"entries\": []}\n```\n\nNo user-facing changes."}"#;
        let result = parse_claude_response(response);
        assert!(result.is_ok());
        assert_eq!(result.unwrap().entries.len(), 0);
    }

    #[test]
    fn test_parse_claude_cli_envelope_with_entries() {
        let response = r#"{"type":"result","is_error":false,"result":"```json\n{\"entries\": [{\"category\": \"Added\", \"description\": \"New feature\"}]}\n```"}"#;
        let result = parse_claude_response(response);
        assert!(result.is_ok());
        let output = result.unwrap();
        assert_eq!(output.entries.len(), 1);
        assert_eq!(output.entries[0].description, "New feature");
    }

    /// Test balanced brace extraction helper
    #[test]
    fn test_extract_balanced_braces() {
        let text = r#"{"a": {"b": 1}} extra"#;
        let result = extract_balanced_braces(text).unwrap();
        assert_eq!(result, r#"{"a": {"b": 1}}"#);
    }

    #[test]
    fn test_extract_balanced_braces_with_strings() {
        // Braces inside strings should not be counted
        let text = r#"{"msg": "use { and } carefully"} after"#;
        let result = extract_balanced_braces(text).unwrap();
        assert_eq!(result, r#"{"msg": "use { and } carefully"}"#);
    }
}
