//! Exponential backoff retry logic for Claude CLI.

use std::time::Duration;

use async_trait::async_trait;
use backoff::backoff::Backoff;
use backoff::ExponentialBackoff;

use crate::changelog::ChangelogOutput;
use crate::error::ClaudeError;

use super::subprocess::run_claude;

/// Trait for executing Claude CLI commands.
///
/// This abstraction allows mocking the Claude subprocess in tests.
#[cfg_attr(test, mockall::automock)]
#[async_trait]
pub trait ClaudeExecutor: Send + Sync {
    /// Run Claude with the given prompt and return the raw response.
    async fn run(&self, prompt: &str) -> Result<String, ClaudeError>;
}

/// Default executor that calls the real Claude CLI.
pub struct DefaultExecutor;

#[async_trait]
impl ClaudeExecutor for DefaultExecutor {
    async fn run(&self, prompt: &str) -> Result<String, ClaudeError> {
        run_claude(prompt).await
    }
}

/// Configuration: 3 total attempts, base 1s, max 30s.
const MAX_ATTEMPTS: u32 = 3;
const INITIAL_INTERVAL_SECS: u64 = 1;
const MAX_INTERVAL_SECS: u64 = 30;

/// Generate changelog entries with retry logic.
///
/// Makes up to 3 attempts with exponential backoff on failure.
pub async fn generate_with_retry(prompt: &str) -> Result<ChangelogOutput, ClaudeError> {
    generate_with_retry_impl(prompt, &DefaultExecutor).await
}

/// Internal implementation that accepts any executor (for testing).
pub(crate) async fn generate_with_retry_impl<E: ClaudeExecutor>(
    prompt: &str,
    executor: &E,
) -> Result<ChangelogOutput, ClaudeError> {
    let mut backoff = ExponentialBackoff {
        initial_interval: Duration::from_secs(INITIAL_INTERVAL_SECS),
        max_interval: Duration::from_secs(MAX_INTERVAL_SECS),
        max_elapsed_time: None, // We control retries manually
        ..Default::default()
    };

    let mut attempts = 0;
    let mut last_error = None;

    while attempts < MAX_ATTEMPTS {
        attempts += 1;

        match try_generate(prompt, executor).await {
            Ok(output) => return Ok(output),
            Err(e) => {
                last_error = Some(e);

                if attempts < MAX_ATTEMPTS
                    && let Some(wait_duration) = backoff.next_backoff()
                {
                    tokio::time::sleep(wait_duration).await;
                }
            }
        }
    }

    // All retries exhausted - include the last error for debugging
    Err(ClaudeError::RetriesExhausted(Box::new(
        last_error.expect("last_error should be Some after failed retries"),
    )))
}

/// Single attempt to generate changelog.
async fn try_generate<E: ClaudeExecutor>(
    prompt: &str,
    executor: &E,
) -> Result<ChangelogOutput, ClaudeError> {
    let response = executor.run(prompt).await?;

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
        tracing::warn!(
            "Could not parse as Claude CLI envelope - treating as raw response. \
             This may indicate a Claude CLI version mismatch. Consider running \
             'claude --version' to check your installation."
        );
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
    if let Some(start) = response.find("```json")
        && let Some(end) = response[start + 7..].find("```")
    {
        return response[start + 7..start + 7 + end].trim().to_string();
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
    use std::sync::atomic::{AtomicU32, Ordering};
    use std::sync::Arc;

    // ============================================
    // Retry Behavior Tests (using mocked executor)
    // ============================================

    /// Test that exactly 3 attempts are made before giving up.
    #[tokio::test(start_paused = true)]
    async fn test_retry_exhausts_after_three_attempts() {
        let mut mock = MockClaudeExecutor::new();

        let call_count = Arc::new(AtomicU32::new(0));
        let call_count_clone = call_count.clone();

        mock.expect_run()
            .times(3)
            .returning(move |_| {
                call_count_clone.fetch_add(1, Ordering::SeqCst);
                Err(ClaudeError::ExecutionFailed("test error".to_string()))
            });

        let result = generate_with_retry_impl("test prompt", &mock).await;

        assert!(matches!(result, Err(ClaudeError::RetriesExhausted(_))));
        assert_eq!(call_count.load(Ordering::SeqCst), 3);
    }

    /// Test successful response after 2 failures.
    #[tokio::test(start_paused = true)]
    async fn test_retry_succeeds_after_failures() {
        let mut mock = MockClaudeExecutor::new();

        let call_count = Arc::new(AtomicU32::new(0));
        let call_count_clone = call_count.clone();

        mock.expect_run()
            .times(3)
            .returning(move |_| {
                let count = call_count_clone.fetch_add(1, Ordering::SeqCst);
                if count < 2 {
                    Err(ClaudeError::ExecutionFailed("transient error".to_string()))
                } else {
                    // Return valid JSON on third attempt
                    Ok(r#"{"entries": [{"category": "Added", "description": "Test feature"}]}"#
                        .to_string())
                }
            });

        let result = generate_with_retry_impl("test prompt", &mock).await;

        assert!(result.is_ok());
        let output = result.unwrap();
        assert_eq!(output.entries.len(), 1);
        assert_eq!(output.entries[0].description, "Test feature");
    }

    /// Test immediate success on first attempt.
    #[tokio::test(start_paused = true)]
    async fn test_success_on_first_attempt() {
        let mut mock = MockClaudeExecutor::new();

        mock.expect_run()
            .times(1)
            .returning(|_| Ok(r#"{"entries": []}"#.to_string()));

        let result = generate_with_retry_impl("test prompt", &mock).await;

        assert!(result.is_ok());
    }

    /// Test that backoff timing includes delays between retries.
    ///
    /// Note: The backoff crate uses randomized jitter by default, so we only
    /// verify that delays occur (are non-zero) rather than specific values.
    #[tokio::test(start_paused = true)]
    async fn test_backoff_delays_occur() {
        use tokio::time::Instant;

        let mut mock = MockClaudeExecutor::new();

        let start = Instant::now();
        let timestamps = Arc::new(std::sync::Mutex::new(Vec::new()));
        let timestamps_clone = timestamps.clone();

        mock.expect_run()
            .times(3)
            .returning(move |_| {
                timestamps_clone.lock().unwrap().push(Instant::now());
                Err(ClaudeError::ExecutionFailed("test".to_string()))
            });

        let _ = generate_with_retry_impl("test", &mock).await;

        let ts = timestamps.lock().unwrap();
        assert_eq!(ts.len(), 3);

        // First call is immediate
        let first_delay = ts[0].duration_since(start);
        assert!(
            first_delay.as_millis() < 100,
            "First call should be immediate, was {:?}",
            first_delay
        );

        // Second call has some backoff delay (with jitter, could be 0.5s-1.5s)
        let second_delay = ts[1].duration_since(ts[0]);
        assert!(
            second_delay.as_millis() >= 100,
            "Second delay should have backoff, was {:?}",
            second_delay
        );

        // Third call also has backoff delay
        let third_delay = ts[2].duration_since(ts[1]);
        assert!(
            third_delay.as_millis() >= 100,
            "Third delay should have backoff, was {:?}",
            third_delay
        );

        // Total elapsed time should be significant (at least 500ms with jitter)
        let total_elapsed = ts[2].duration_since(start);
        assert!(
            total_elapsed.as_millis() >= 500,
            "Total elapsed time should show backoff occurred, was {:?}",
            total_elapsed
        );
    }

    /// Test that different error types are handled correctly.
    #[tokio::test(start_paused = true)]
    async fn test_retry_with_different_errors() {
        let mut mock = MockClaudeExecutor::new();

        let call_count = Arc::new(AtomicU32::new(0));
        let call_count_clone = call_count.clone();

        mock.expect_run()
            .times(3)
            .returning(move |_| {
                let count = call_count_clone.fetch_add(1, Ordering::SeqCst);
                match count {
                    0 => Err(ClaudeError::Timeout(30)),
                    1 => Err(ClaudeError::NonZeroExit {
                        code: 1,
                        stderr: "error".to_string(),
                    }),
                    _ => Err(ClaudeError::ExecutionFailed("final error".to_string())),
                }
            });

        let result = generate_with_retry_impl("test", &mock).await;

        // Verify the last error (ExecutionFailed) is preserved in the error chain
        match result {
            Err(ClaudeError::RetriesExhausted(inner)) => {
                assert!(matches!(*inner, ClaudeError::ExecutionFailed(_)));
            }
            _ => panic!("Expected RetriesExhausted error"),
        }
    }

    /// Test that invalid JSON triggers retry.
    #[tokio::test(start_paused = true)]
    async fn test_retry_on_invalid_json() {
        let mut mock = MockClaudeExecutor::new();

        let call_count = Arc::new(AtomicU32::new(0));
        let call_count_clone = call_count.clone();

        mock.expect_run()
            .times(2)
            .returning(move |_| {
                let count = call_count_clone.fetch_add(1, Ordering::SeqCst);
                if count == 0 {
                    Ok("not valid json".to_string())
                } else {
                    Ok(r#"{"entries": []}"#.to_string())
                }
            });

        let result = generate_with_retry_impl("test", &mock).await;

        assert!(result.is_ok());
    }

    /// Test success after exactly 1 failure.
    #[tokio::test(start_paused = true)]
    async fn test_retry_succeeds_after_one_failure() {
        let mut mock = MockClaudeExecutor::new();

        let call_count = Arc::new(AtomicU32::new(0));
        let call_count_clone = call_count.clone();

        mock.expect_run()
            .times(2)
            .returning(move |_| {
                let count = call_count_clone.fetch_add(1, Ordering::SeqCst);
                if count == 0 {
                    Err(ClaudeError::ExecutionFailed("first failure".to_string()))
                } else {
                    Ok(r#"{"entries": []}"#.to_string())
                }
            });

        let result = generate_with_retry_impl("test", &mock).await;

        assert!(result.is_ok());
        assert_eq!(call_count.load(Ordering::SeqCst), 2);
    }

    // ============================================
    // JSON Extraction Tests (existing tests)
    // ============================================

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
