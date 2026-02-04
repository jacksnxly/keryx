//! Shared JSON extraction utilities for LLM responses.
//!
//! LLM providers often return JSON wrapped in markdown code blocks or
//! surrounded by conversational text. This module provides robust
//! extraction that handles nested braces and string escaping correctly.

/// Extract a JSON object from an LLM response that may be wrapped in markdown.
///
/// Tries, in order:
/// 1. Markdown ` ```json ... ``` ` fenced block
/// 2. Bare ` ``` ... ``` ` fenced block (if the content starts with `{`)
/// 3. Proper JSON parsing / balanced-brace extraction from surrounding text
/// 4. Returns the input unchanged as a last resort
pub fn extract_json(response: &str) -> String {
    let trimmed = response.trim();

    // Try ` ```json ` fenced block
    if let Some(start) = trimmed.find("```json")
        && let Some(end) = trimmed[start + 7..].find("```")
    {
        return trimmed[start + 7..start + 7 + end].trim().to_string();
    }

    // Try bare ` ``` ` fenced block
    if let Some(start) = trimmed.find("```")
        && let Some(end) = trimmed[start + 3..].find("```")
    {
        let inner = trimmed[start + 3..start + 3 + end].trim();
        if inner.starts_with('{') {
            return inner.to_string();
        }
    }

    // Use proper JSON parsing to find valid JSON objects
    if let Some(json_str) = find_valid_json_object(trimmed) {
        return json_str;
    }

    trimmed.to_string()
}

/// Find a valid JSON object in a string using proper brace matching.
///
/// Iterates through every `{` in the input. For each one, first tries a full
/// `serde_json` parse (which handles nested braces correctly), then falls
/// back to balanced-brace extraction with string-escape awareness.
fn find_valid_json_object(text: &str) -> Option<String> {
    for (start_idx, _) in text.match_indices('{') {
        let candidate = &text[start_idx..];

        // Fast path: serde_json handles nested braces and trailing text
        if let Ok(value) = serde_json::from_str::<serde_json::Value>(candidate) {
            if let Ok(json_str) = serde_json::to_string(&value) {
                return Some(json_str);
            }
        }

        // Slow path: balanced-brace extraction then validation
        if let Some(json_str) = extract_balanced_braces(candidate) {
            if serde_json::from_str::<serde_json::Value>(&json_str).is_ok() {
                return Some(json_str);
            }
        }
    }

    None
}

/// Extract a substring with balanced braces starting from the first `{`.
///
/// Tracks brace depth while respecting JSON string literals (including
/// escaped characters), so `{"msg": "use { and } carefully"}` is handled
/// correctly.
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
        let response = "Here's the JSON:\n```json\n{\"entries\": []}\n```";
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
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert!(parsed["entries"].is_array());
    }

    #[test]
    fn test_extract_nested_json_correctly() {
        let response = r#"{"entries": [{"category": "Added", "description": "Test"}]}"#;
        let json = extract_json(response);
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed["entries"][0]["category"], "Added");
    }

    #[test]
    fn test_extract_deeply_nested_json() {
        let response = r#"Result: {"entries": [{"category": "Added", "metadata": {"author": {"name": "John"}}}]} done"#;
        let json = extract_json(response);
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed["entries"][0]["metadata"]["author"]["name"], "John");
    }

    #[test]
    fn test_extract_json_with_escaped_quotes() {
        let response = r#"{"entries": [{"description": "Added \"new\" feature"}]}"#;
        let json = extract_json(response);
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert!(
            parsed["entries"][0]["description"]
                .as_str()
                .unwrap()
                .contains("\"new\"")
        );
    }

    #[test]
    fn test_extract_balanced_braces() {
        let text = r#"{"a": {"b": 1}} extra"#;
        let result = extract_balanced_braces(text).unwrap();
        assert_eq!(result, r#"{"a": {"b": 1}}"#);
    }

    #[test]
    fn test_extract_balanced_braces_with_strings() {
        let text = r#"{"msg": "use { and } carefully"} after"#;
        let result = extract_balanced_braces(text).unwrap();
        assert_eq!(result, r#"{"msg": "use { and } carefully"}"#);
    }

    #[test]
    fn test_extract_bare_code_block() {
        let response = "```\n{\"bump_type\": \"patch\", \"reasoning\": \"Fix\"}\n```";
        let json = extract_json(response);
        let parsed: serde_json::Value = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed["bump_type"], "patch");
    }

    #[test]
    fn test_extract_empty_code_block() {
        let response = "```json\n```";
        let result = extract_json(response);
        assert_eq!(result, "");
    }

    #[test]
    fn test_extract_no_json_present() {
        let response = "This is just plain text with no JSON";
        let result = extract_json(response);
        assert_eq!(result, response);
    }

    #[test]
    fn test_extract_only_closing_braces() {
        let response = "}}";
        let result = extract_json(response);
        assert_eq!(result, "}}");
    }
}
