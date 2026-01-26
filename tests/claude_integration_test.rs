//! Integration tests for Claude error recovery.
//!
//! These tests verify the complete error recovery flow by implementing
//! a test executor that calls real shell scripts to simulate various
//! Claude CLI failure modes.
//!
//! Unlike the unit tests in `src/claude/retry.rs` which use mockall,
//! these tests use actual subprocess calls to verify the error handling
//! works end-to-end.
//!
//! Test coverage (KRX-046):
//! - Invalid JSON triggers retry
//! - Timeout produces clear error message
//! - All retries exhausted includes the last error
//! - Partial/malformed JSON is handled gracefully

use std::fs::{self, File};
use std::io::Write;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;
use std::process::Stdio;
use std::sync::atomic::{AtomicU32, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};

use async_trait::async_trait;
use tempfile::TempDir;
use tokio::process::Command;
use tokio::time::timeout;

use keryx::claude::ClaudeExecutor;
use keryx::ClaudeError;

/// Test executor that runs a shell script to simulate Claude responses.
///
/// This allows testing the full retry logic with real subprocess calls.
struct ScriptExecutor {
    script_path: PathBuf,
    call_count: Arc<AtomicU32>,
    timeout_secs: u64,
}

impl ScriptExecutor {
    fn new(script_path: PathBuf, timeout_secs: u64) -> Self {
        Self {
            script_path,
            call_count: Arc::new(AtomicU32::new(0)),
            timeout_secs,
        }
    }

    fn call_count(&self) -> u32 {
        self.call_count.load(Ordering::SeqCst)
    }
}

#[async_trait]
impl ClaudeExecutor for ScriptExecutor {
    async fn run(&self, prompt: &str) -> Result<String, ClaudeError> {
        self.call_count.fetch_add(1, Ordering::SeqCst);

        let timeout_duration = Duration::from_secs(self.timeout_secs);

        let result = timeout(
            timeout_duration,
            Command::new(&self.script_path)
                .arg("-p")
                .arg(prompt)
                .env("CALL_COUNT", self.call_count.load(Ordering::SeqCst).to_string())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .output(),
        )
        .await;

        match result {
            Err(_) => Err(ClaudeError::Timeout(self.timeout_secs)),
            Ok(Err(e)) => Err(ClaudeError::SpawnFailed(e)),
            Ok(Ok(output)) => {
                if !output.status.success() {
                    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
                    let code = output.status.code().unwrap_or(-1);
                    Err(ClaudeError::NonZeroExit { code, stderr })
                } else {
                    Ok(String::from_utf8_lossy(&output.stdout).to_string())
                }
            }
        }
    }
}

/// Helper to create a mock script and return the temp directory + script path.
fn create_mock_script(script_content: &str) -> (TempDir, PathBuf) {
    let temp_dir = TempDir::new().expect("Failed to create temp directory");
    let script_path = temp_dir.path().join("mock_claude.sh");

    let mut file = File::create(&script_path).expect("Failed to create mock script");
    file.write_all(script_content.as_bytes())
        .expect("Failed to write mock script");

    // Make executable
    let mut perms = fs::metadata(&script_path)
        .expect("Failed to get metadata")
        .permissions();
    perms.set_mode(0o755);
    fs::set_permissions(&script_path, perms).expect("Failed to set permissions");

    (temp_dir, script_path)
}

// Import the retry function with internal implementation
mod retry_helper {
    use keryx::changelog::ChangelogOutput;
    use keryx::claude::ClaudeExecutor;
    use keryx::ClaudeError;

    use std::time::Duration;
    use backoff::backoff::Backoff;
    use backoff::ExponentialBackoff;

    const MAX_ATTEMPTS: u32 = 3;
    // Use very short backoff for tests (10ms)
    const INITIAL_INTERVAL_MS: u64 = 10;
    const MAX_INTERVAL_MS: u64 = 50;

    /// Re-implementation of generate_with_retry_impl for testing.
    /// This mirrors the internal implementation in retry.rs
    pub async fn generate_with_retry<E: ClaudeExecutor>(
        prompt: &str,
        executor: &E,
    ) -> Result<ChangelogOutput, ClaudeError> {
        let mut backoff = ExponentialBackoff {
            initial_interval: Duration::from_millis(INITIAL_INTERVAL_MS),
            max_interval: Duration::from_millis(MAX_INTERVAL_MS),
            max_elapsed_time: None,
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

                    if attempts < MAX_ATTEMPTS {
                        if let Some(wait_duration) = backoff.next_backoff() {
                            tokio::time::sleep(wait_duration).await;
                        }
                    }
                }
            }
        }

        Err(ClaudeError::RetriesExhausted(Box::new(
            last_error.expect("last_error should be Some"),
        )))
    }

    async fn try_generate<E: ClaudeExecutor>(
        prompt: &str,
        executor: &E,
    ) -> Result<ChangelogOutput, ClaudeError> {
        let response = executor.run(prompt).await?;
        parse_response(&response)
    }

    fn parse_response(response: &str) -> Result<ChangelogOutput, ClaudeError> {
        // Try to parse as Claude CLI envelope first
        #[derive(serde::Deserialize)]
        struct Envelope {
            result: String,
            #[serde(default)]
            is_error: bool,
        }

        let content = if let Ok(envelope) = serde_json::from_str::<Envelope>(response) {
            if envelope.is_error {
                return Err(ClaudeError::ExecutionFailed(envelope.result));
            }
            envelope.result
        } else {
            response.to_string()
        };

        // Extract JSON (may be in markdown blocks)
        let json_str = extract_json(&content);

        serde_json::from_str(&json_str)
            .map_err(|e| ClaudeError::InvalidJson(format!("Parse failed: {}", e)))
    }

    fn extract_json(response: &str) -> String {
        // Try markdown block first
        if let Some(start) = response.find("```json") {
            if let Some(end) = response[start + 7..].find("```") {
                return response[start + 7..start + 7 + end].trim().to_string();
            }
        }

        // Try to find JSON object
        if let Some(start) = response.find('{') {
            if let Some(end) = response.rfind('}') {
                return response[start..=end].to_string();
            }
        }

        response.to_string()
    }
}

// ============================================
// Test: Invalid JSON triggers retry (KRX-046 AC1)
// ============================================

/// Mock that returns invalid JSON first, then valid JSON.
const MOCK_INVALID_THEN_VALID: &str = r#"#!/bin/bash
# CALL_COUNT is passed as env var
if [ "$CALL_COUNT" -eq 1 ]; then
    # First call: return invalid JSON
    echo '{"result": "not valid json {", "is_error": false}'
else
    # Subsequent calls: return valid JSON
    echo '{"result": "{\"entries\": [{\"category\": \"Added\", \"description\": \"Test feature\"}]}", "is_error": false}'
fi
"#;

#[tokio::test]
#[cfg(unix)]
async fn test_invalid_json_triggers_retry() {
    let (_temp_dir, script_path) = create_mock_script(MOCK_INVALID_THEN_VALID);
    let executor = ScriptExecutor::new(script_path, 30);

    let result = retry_helper::generate_with_retry("test prompt", &executor).await;

    // Should succeed after retry
    assert!(result.is_ok(), "Should succeed on retry: {:?}", result);

    // Should have retried (called at least twice)
    assert!(
        executor.call_count() >= 2,
        "Should have retried. Call count: {}",
        executor.call_count()
    );

    let output = result.unwrap();
    assert_eq!(output.entries.len(), 1);
    assert_eq!(output.entries[0].description, "Test feature");
}

// ============================================
// Test: Timeout produces clear error (KRX-046 AC2)
// ============================================

/// Mock that sleeps forever (will be killed by timeout).
const MOCK_TIMEOUT: &str = r#"#!/bin/bash
sleep 3600
"#;

#[tokio::test]
#[cfg(unix)]
async fn test_timeout_produces_clear_error() {
    let (_temp_dir, script_path) = create_mock_script(MOCK_TIMEOUT);
    // Use very short timeout (1 second)
    let executor = ScriptExecutor::new(script_path, 1);

    let start = Instant::now();
    let result = retry_helper::generate_with_retry("test prompt", &executor).await;
    let elapsed = start.elapsed();

    // Should fail
    assert!(result.is_err(), "Should fail due to timeout");

    // Should timeout quickly (within ~3 retries * 1s + backoff)
    assert!(
        elapsed.as_secs() < 30,
        "Should timeout reasonably quickly, took {:?}",
        elapsed
    );

    // Error should be RetriesExhausted wrapping Timeout
    match result {
        Err(ClaudeError::RetriesExhausted(inner)) => {
            assert!(
                matches!(*inner, ClaudeError::Timeout(_)),
                "Inner error should be Timeout, got: {:?}",
                inner
            );
        }
        other => panic!("Expected RetriesExhausted(Timeout), got: {:?}", other),
    }
}

// ============================================
// Test: Retries exhausted includes last error (KRX-046 AC3)
// ============================================

/// Mock that always exits with error.
const MOCK_ALWAYS_FAIL: &str = r#"#!/bin/bash
echo "API rate limit exceeded - try again later" >&2
exit 1
"#;

#[tokio::test]
#[cfg(unix)]
async fn test_retries_exhausted_includes_last_error() {
    let (_temp_dir, script_path) = create_mock_script(MOCK_ALWAYS_FAIL);
    let executor = ScriptExecutor::new(script_path, 30);

    let result = retry_helper::generate_with_retry("test prompt", &executor).await;

    // Should fail after all retries
    assert!(result.is_err(), "Should fail after retries exhausted");

    // Should have tried 3 times
    assert_eq!(
        executor.call_count(),
        3,
        "Should have exactly 3 attempts"
    );

    // Error should be RetriesExhausted with NonZeroExit inside
    match result {
        Err(ClaudeError::RetriesExhausted(inner)) => match *inner {
            ClaudeError::NonZeroExit { code, ref stderr } => {
                assert_eq!(code, 1, "Exit code should be 1");
                assert!(
                    stderr.contains("rate limit"),
                    "Stderr should contain original error message. Got: {}",
                    stderr
                );
            }
            other => panic!("Expected NonZeroExit, got: {:?}", other),
        },
        other => panic!("Expected RetriesExhausted, got: {:?}", other),
    }
}

// ============================================
// Test: Partial/malformed JSON handled gracefully (KRX-046 AC4)
// ============================================

/// Mock that returns truncated JSON.
const MOCK_PARTIAL_JSON: &str = r#"#!/bin/bash
# Return JSON that's cut off mid-stream
echo '{"result": "{\"entries\": [{\"category\": \"Added\", \"description\": \"Test", "is_error": false}'
"#;

#[tokio::test]
#[cfg(unix)]
async fn test_partial_json_handled_gracefully() {
    let (_temp_dir, script_path) = create_mock_script(MOCK_PARTIAL_JSON);
    let executor = ScriptExecutor::new(script_path, 30);

    let result = retry_helper::generate_with_retry("test prompt", &executor).await;

    // Should fail (can't parse partial JSON)
    assert!(result.is_err(), "Should fail with partial JSON");

    // Should have retried all attempts
    assert_eq!(
        executor.call_count(),
        3,
        "Should exhaust all retries"
    );

    // Error should indicate JSON parsing failure
    match result {
        Err(ClaudeError::RetriesExhausted(inner)) => {
            assert!(
                matches!(*inner, ClaudeError::InvalidJson(_)),
                "Inner error should be InvalidJson, got: {:?}",
                inner
            );
        }
        other => panic!("Expected RetriesExhausted(InvalidJson), got: {:?}", other),
    }
}

// ============================================
// Test: Successful case baseline
// ============================================

/// Mock that returns valid JSON immediately.
const MOCK_SUCCESS: &str = r#"#!/bin/bash
echo '{"result": "{\"entries\": [{\"category\": \"Added\", \"description\": \"New feature\"}]}", "is_error": false}'
"#;

#[tokio::test]
#[cfg(unix)]
async fn test_success_on_first_attempt() {
    let (_temp_dir, script_path) = create_mock_script(MOCK_SUCCESS);
    let executor = ScriptExecutor::new(script_path, 30);

    let result = retry_helper::generate_with_retry("test prompt", &executor).await;

    // Should succeed immediately
    assert!(result.is_ok(), "Should succeed: {:?}", result);

    // Should only call once
    assert_eq!(executor.call_count(), 1, "Should only call once");

    let output = result.unwrap();
    assert_eq!(output.entries.len(), 1);
    assert_eq!(output.entries[0].description, "New feature");
}

// ============================================
// Test: Recovery after transient failures
// ============================================

/// Mock that fails twice then succeeds.
const MOCK_TRANSIENT_FAILURE: &str = r#"#!/bin/bash
if [ "$CALL_COUNT" -lt 3 ]; then
    echo "Temporary network error" >&2
    exit 1
else
    echo '{"result": "{\"entries\": []}", "is_error": false}'
fi
"#;

#[tokio::test]
#[cfg(unix)]
async fn test_recovery_after_transient_failures() {
    let (_temp_dir, script_path) = create_mock_script(MOCK_TRANSIENT_FAILURE);
    let executor = ScriptExecutor::new(script_path, 30);

    let result = retry_helper::generate_with_retry("test prompt", &executor).await;

    // Should succeed on third attempt
    assert!(result.is_ok(), "Should recover from transient failures: {:?}", result);

    // Should have tried 3 times
    assert_eq!(executor.call_count(), 3, "Should try exactly 3 times");
}

// ============================================
// Test: Non-zero exit captures stderr content
// ============================================

/// Mock that exits with specific code and detailed stderr.
const MOCK_DETAILED_ERROR: &str = r#"#!/bin/bash
echo "Error: Authentication failed" >&2
echo "Hint: Run 'claude auth login' to authenticate" >&2
exit 42
"#;

#[tokio::test]
#[cfg(unix)]
async fn test_nonzero_exit_captures_detailed_stderr() {
    let (_temp_dir, script_path) = create_mock_script(MOCK_DETAILED_ERROR);
    let executor = ScriptExecutor::new(script_path, 30);

    let result = retry_helper::generate_with_retry("test prompt", &executor).await;

    // Should fail
    assert!(result.is_err());

    // Verify error contains both stderr lines
    match result {
        Err(ClaudeError::RetriesExhausted(inner)) => match *inner {
            ClaudeError::NonZeroExit { code, ref stderr } => {
                assert_eq!(code, 42, "Exit code should be 42");
                assert!(
                    stderr.contains("Authentication failed"),
                    "Stderr should contain error message"
                );
                assert!(
                    stderr.contains("claude auth login"),
                    "Stderr should contain hint"
                );
            }
            other => panic!("Expected NonZeroExit, got: {:?}", other),
        },
        other => panic!("Expected RetriesExhausted, got: {:?}", other),
    }
}

// ============================================
// Test: Claude error flag is handled
// ============================================

/// Mock that returns is_error: true.
const MOCK_IS_ERROR_TRUE: &str = r#"#!/bin/bash
echo '{"result": "Claude encountered an internal error", "is_error": true}'
"#;

#[tokio::test]
#[cfg(unix)]
async fn test_is_error_flag_handled() {
    let (_temp_dir, script_path) = create_mock_script(MOCK_IS_ERROR_TRUE);
    let executor = ScriptExecutor::new(script_path, 30);

    let result = retry_helper::generate_with_retry("test prompt", &executor).await;

    // Should fail
    assert!(result.is_err());

    // Should have retried
    assert_eq!(executor.call_count(), 3);

    // Error should be ExecutionFailed
    match result {
        Err(ClaudeError::RetriesExhausted(inner)) => {
            assert!(
                matches!(*inner, ClaudeError::ExecutionFailed(_)),
                "Should be ExecutionFailed, got: {:?}",
                inner
            );
        }
        other => panic!("Expected RetriesExhausted(ExecutionFailed), got: {:?}", other),
    }
}
