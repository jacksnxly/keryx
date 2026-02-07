//! Exponential backoff retry logic for Claude CLI.

use async_trait::async_trait;

use crate::changelog::ChangelogOutput;
use crate::error::ClaudeError;
use crate::llm::extract_json;
use crate::llm::retry::retry_with_backoff;

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

/// Generate changelog entries with retry logic.
///
/// Makes up to 3 attempts with exponential backoff on failure.
pub async fn generate_with_retry(prompt: &str) -> Result<ChangelogOutput, ClaudeError> {
    generate_with_retry_impl(prompt, &DefaultExecutor).await
}

/// Generate a raw string response with retry logic (no ChangelogOutput parsing).
///
/// Makes up to 3 attempts with exponential backoff on failure.
/// The Claude CLI JSON envelope is unwrapped, but no further parsing is done.
pub async fn generate_raw_with_retry(prompt: &str) -> Result<String, ClaudeError> {
    generate_raw_with_retry_impl(prompt, &DefaultExecutor).await
}

/// Internal raw retry implementation that accepts any executor (for testing).
pub(crate) async fn generate_raw_with_retry_impl<E: ClaudeExecutor>(
    prompt: &str,
    executor: &E,
) -> Result<String, ClaudeError> {
    retry_with_backoff(
        || async {
            let response = executor.run(prompt).await?;
            unwrap_claude_envelope(&response)
        },
        |e| ClaudeError::RetriesExhausted(Box::new(e)),
    )
    .await
}

/// Internal implementation that accepts any executor (for testing).
pub(crate) async fn generate_with_retry_impl<E: ClaudeExecutor>(
    prompt: &str,
    executor: &E,
) -> Result<ChangelogOutput, ClaudeError> {
    retry_with_backoff(
        || async { try_generate(prompt, executor).await },
        |e| ClaudeError::RetriesExhausted(Box::new(e)),
    )
    .await
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

/// Unwrap the Claude CLI JSON envelope, returning the inner `result` string.
///
/// If the response cannot be parsed as an envelope, returns the raw response as-is.
/// If the envelope indicates an error (`is_error: true`), returns
/// `Err(ClaudeError::ExecutionFailed(...))` so callers can retry or surface the failure.
///
/// When Claude CLI is invoked via `script` (pseudo-TTY wrapper), stderr from
/// hooks or other processes may be interleaved with stdout.  The direct
/// `serde_json::from_str` call fails in that case because of trailing
/// non-JSON text.  We fall back to `extract_json` which uses balanced-brace
/// extraction and handles surrounding garbage gracefully.
pub(crate) fn unwrap_claude_envelope(response: &str) -> Result<String, ClaudeError> {
    // Fast path: response is clean JSON (no trailing garbage)
    if let Ok(envelope) = serde_json::from_str::<ClaudeCliResponse>(response) {
        if envelope.is_error {
            return Err(ClaudeError::ExecutionFailed(envelope.result));
        }
        return Ok(envelope.result);
    }

    // Slow path: extract JSON from noisy output (e.g., hook stderr mixed
    // into the PTY stream by the `script` wrapper)
    let extracted = extract_json(response);
    if let Ok(envelope) = serde_json::from_str::<ClaudeCliResponse>(&extracted) {
        if envelope.is_error {
            return Err(ClaudeError::ExecutionFailed(envelope.result));
        }
        return Ok(envelope.result);
    }

    tracing::warn!(
        "Could not parse as Claude CLI envelope - treating as raw response. \
         This may indicate a Claude CLI version mismatch. Consider running \
         'claude --version' to check your installation."
    );
    Ok(response.to_string())
}

/// Parse Claude's JSON response into ChangelogOutput.
fn parse_claude_response(response: &str) -> Result<ChangelogOutput, ClaudeError> {
    // Unwrap the Claude CLI JSON envelope (handles is_error detection)
    let content = unwrap_claude_envelope(response)?;

    // Now extract the changelog JSON from Claude's response text
    let json_str = extract_json(&content);

    serde_json::from_str(&json_str).map_err(|e| {
        ClaudeError::InvalidJson(format!("Failed to parse: {}. Content: {}", e, content))
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::sync::atomic::{AtomicU32, Ordering};

    // ============================================
    // Retry Behavior Tests (using mocked executor)
    // ============================================

    /// Test that exactly 3 attempts are made before giving up.
    #[tokio::test(start_paused = true)]
    async fn test_retry_exhausts_after_three_attempts() {
        let mut mock = MockClaudeExecutor::new();

        let call_count = Arc::new(AtomicU32::new(0));
        let call_count_clone = call_count.clone();

        mock.expect_run().times(3).returning(move |_| {
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

        mock.expect_run().times(3).returning(move |_| {
            let count = call_count_clone.fetch_add(1, Ordering::SeqCst);
            if count < 2 {
                Err(ClaudeError::ExecutionFailed("transient error".to_string()))
            } else {
                // Return valid JSON on third attempt
                Ok(
                    r#"{"entries": [{"category": "Added", "description": "Test feature"}]}"#
                        .to_string(),
                )
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

        mock.expect_run().times(3).returning(move |_| {
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

        mock.expect_run().times(3).returning(move |_| {
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

        mock.expect_run().times(2).returning(move |_| {
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

        mock.expect_run().times(2).returning(move |_| {
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
    // Envelope Unwrapping Tests
    // ============================================

    /// Test unwrapping a valid Claude CLI envelope with is_error=false.
    #[test]
    fn test_unwrap_envelope_valid() {
        let response = r#"{"type":"result","is_error":false,"result":"hello world"}"#;
        let result = unwrap_claude_envelope(response);
        assert_eq!(result.unwrap(), "hello world");
    }

    /// Test that non-JSON input falls back to returning the raw string.
    #[test]
    fn test_unwrap_envelope_non_json_fallback() {
        let response = "plain text response";
        let result = unwrap_claude_envelope(response);
        assert_eq!(result.unwrap(), "plain text response");
    }

    /// Test that an error envelope (is_error=true) returns Err(ExecutionFailed).
    #[test]
    fn test_unwrap_envelope_error_flag() {
        let response = r#"{"type":"result","is_error":true,"result":"Authentication failed: invalid API key"}"#;
        let result = unwrap_claude_envelope(response);
        match result {
            Err(ClaudeError::ExecutionFailed(msg)) => {
                assert_eq!(msg, "Authentication failed: invalid API key");
            }
            other => panic!("Expected ExecutionFailed, got: {:?}", other),
        }
    }

    /// Test that is_error defaults to false when omitted from the envelope.
    #[test]
    fn test_unwrap_envelope_missing_is_error_defaults_false() {
        let response = r#"{"result":"no error field"}"#;
        let result = unwrap_claude_envelope(response);
        assert_eq!(result.unwrap(), "no error field");
    }

    /// Test that envelope is extracted when hook stderr is mixed into PTY output.
    ///
    /// When Claude CLI runs via `script` (pseudo-TTY), stderr from hooks
    /// (e.g. SessionEnd) gets interleaved with stdout, producing trailing
    /// garbage after the JSON envelope.
    #[test]
    fn test_unwrap_envelope_with_trailing_hook_stderr() {
        let response = concat!(
            r#"{"type":"result","subtype":"success","is_error":false,"result":"{\"groups\": [{\"label\": \"test\", \"files\": [\"a.rs\"]}]}"}"#,
            "\nSessionEnd hook [python3 hooks/kill.py] failed: Traceback (most recent call last):\n",
            "  File \"hooks/kill.py\", line 43, in <module>\n",
            "    os.kill(pid, signal.SIGKILL)\n",
            "ProcessLookupError: [Errno 3] No such process\n",
        );
        let result = unwrap_claude_envelope(response).unwrap();
        assert_eq!(
            result,
            r#"{"groups": [{"label": "test", "files": ["a.rs"]}]}"#
        );
    }

    /// Test that error envelopes are still detected even with trailing garbage.
    #[test]
    fn test_unwrap_envelope_error_with_trailing_garbage() {
        let response = concat!(
            r#"{"type":"result","is_error":true,"result":"rate limited"}"#,
            "\nsome trailing output\n",
        );
        let result = unwrap_claude_envelope(response);
        match result {
            Err(ClaudeError::ExecutionFailed(msg)) => {
                assert_eq!(msg, "rate limited");
            }
            other => panic!("Expected ExecutionFailed, got: {:?}", other),
        }
    }

    // ============================================
    // Raw Retry Behavior Tests
    // ============================================

    /// Test that generate_raw_with_retry_impl exhausts all 3 attempts on persistent failure.
    #[tokio::test(start_paused = true)]
    async fn test_raw_retry_exhausts_after_three_attempts() {
        let mut mock = MockClaudeExecutor::new();

        let call_count = Arc::new(AtomicU32::new(0));
        let call_count_clone = call_count.clone();

        mock.expect_run().times(3).returning(move |_| {
            call_count_clone.fetch_add(1, Ordering::SeqCst);
            Err(ClaudeError::ExecutionFailed("persistent error".to_string()))
        });

        let result = generate_raw_with_retry_impl("test prompt", &mock).await;

        assert!(matches!(result, Err(ClaudeError::RetriesExhausted(_))));
        assert_eq!(call_count.load(Ordering::SeqCst), 3);
    }

    /// Test that generate_raw_with_retry_impl succeeds immediately on first attempt.
    #[tokio::test(start_paused = true)]
    async fn test_raw_success_on_first_attempt() {
        let mut mock = MockClaudeExecutor::new();

        mock.expect_run().times(1).returning(|_| {
            Ok(r#"{"type":"result","is_error":false,"result":"patch"}"#.to_string())
        });

        let result = generate_raw_with_retry_impl("test prompt", &mock).await;
        assert_eq!(result.unwrap(), "patch");
    }

    /// Test that generate_raw_with_retry_impl retries when the envelope has is_error=true.
    #[tokio::test(start_paused = true)]
    async fn test_raw_retry_on_envelope_error() {
        let mut mock = MockClaudeExecutor::new();

        let call_count = Arc::new(AtomicU32::new(0));
        let call_count_clone = call_count.clone();

        mock.expect_run().times(2).returning(move |_| {
            let count = call_count_clone.fetch_add(1, Ordering::SeqCst);
            if count == 0 {
                // First call: Claude returns an error envelope (subprocess succeeds, but envelope says error)
                Ok(r#"{"type":"result","is_error":true,"result":"rate limited"}"#.to_string())
            } else {
                // Second call: valid response
                Ok(r#"{"type":"result","is_error":false,"result":"patch"}"#.to_string())
            }
        });

        let result = generate_raw_with_retry_impl("test", &mock).await;
        assert_eq!(result.unwrap(), "patch");
        assert_eq!(call_count.load(Ordering::SeqCst), 2);
    }

    /// Test that parse_claude_response also rejects error envelopes (via unwrap_claude_envelope).
    #[test]
    fn test_parse_claude_response_error_envelope() {
        let response = r#"{"type":"result","is_error":true,"result":"internal server error"}"#;
        let result = parse_claude_response(response);
        assert!(matches!(result, Err(ClaudeError::ExecutionFailed(_))));
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
}
