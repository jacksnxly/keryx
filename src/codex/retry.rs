//! Exponential backoff retry logic for Codex CLI.

use async_trait::async_trait;

use crate::changelog::ChangelogOutput;
use crate::error::CodexError;
use crate::llm::extract_json;
use crate::llm::retry::retry_with_backoff;

use super::subprocess::{run_codex, run_codex_raw};

/// Trait for executing Codex CLI commands.
///
/// This abstraction allows mocking the Codex subprocess in tests.
#[cfg_attr(test, mockall::automock)]
#[async_trait]
pub trait CodexExecutor: Send + Sync {
    /// Run Codex with the given prompt and return the raw response.
    async fn run(&self, prompt: &str) -> Result<String, CodexError>;
}

/// Default executor that calls the real Codex CLI.
pub struct DefaultExecutor;

#[async_trait]
impl CodexExecutor for DefaultExecutor {
    async fn run(&self, prompt: &str) -> Result<String, CodexError> {
        run_codex(prompt).await
    }
}

/// Generate changelog entries with retry logic.
///
/// Makes up to 3 attempts with exponential backoff on failure.
pub async fn generate_with_retry(prompt: &str) -> Result<ChangelogOutput, CodexError> {
    generate_with_retry_impl(prompt, &DefaultExecutor).await
}

/// Executor for raw (non-schema) Codex calls.
pub struct RawExecutor;

#[async_trait]
impl CodexExecutor for RawExecutor {
    async fn run(&self, prompt: &str) -> Result<String, CodexError> {
        run_codex_raw(prompt).await
    }
}

/// Generate a raw string response with retry logic (no ChangelogOutput parsing).
///
/// Uses `codex exec` without `--output-schema`, with the same retry pattern.
pub async fn generate_raw_with_retry(prompt: &str) -> Result<String, CodexError> {
    generate_raw_with_retry_impl(prompt, &RawExecutor).await
}

/// Internal raw retry implementation that accepts any executor (for testing).
pub(crate) async fn generate_raw_with_retry_impl<E: CodexExecutor>(
    prompt: &str,
    executor: &E,
) -> Result<String, CodexError> {
    retry_with_backoff(
        || async { executor.run(prompt).await },
        |e| CodexError::RetriesExhausted(Box::new(e)),
    )
    .await
}

/// Internal implementation that accepts any executor (for testing).
pub(crate) async fn generate_with_retry_impl<E: CodexExecutor>(
    prompt: &str,
    executor: &E,
) -> Result<ChangelogOutput, CodexError> {
    retry_with_backoff(
        || async { try_generate(prompt, executor).await },
        |e| CodexError::RetriesExhausted(Box::new(e)),
    )
    .await
}

/// Single attempt to generate changelog.
async fn try_generate<E: CodexExecutor>(
    prompt: &str,
    executor: &E,
) -> Result<ChangelogOutput, CodexError> {
    let response = executor.run(prompt).await?;
    parse_codex_response(&response)
}

/// Parse Codex's response into ChangelogOutput.
fn parse_codex_response(response: &str) -> Result<ChangelogOutput, CodexError> {
    if let Ok(output) = serde_json::from_str::<ChangelogOutput>(response) {
        return Ok(output);
    }

    let json_str = extract_json(response);
    serde_json::from_str(&json_str).map_err(|e| {
        CodexError::InvalidJson(format!("Failed to parse: {}. Content: {}", e, response))
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;
    use std::sync::atomic::{AtomicU32, Ordering};

    // ============================================
    // Raw Retry Behavior Tests (using mocked executor)
    // ============================================

    /// Test that generate_raw_with_retry_impl exhausts all 3 attempts on persistent failure.
    #[tokio::test(start_paused = true)]
    async fn test_codex_raw_retry_exhaustion() {
        let mut mock = MockCodexExecutor::new();

        let call_count = Arc::new(AtomicU32::new(0));
        let call_count_clone = call_count.clone();

        mock.expect_run().times(3).returning(move |_| {
            call_count_clone.fetch_add(1, Ordering::SeqCst);
            Err(CodexError::ExecutionFailed("persistent error".to_string()))
        });

        let result = generate_raw_with_retry_impl("test prompt", &mock).await;

        assert!(matches!(result, Err(CodexError::RetriesExhausted(_))));
        assert_eq!(call_count.load(Ordering::SeqCst), 3);
    }

    /// Test that generate_raw_with_retry_impl succeeds immediately on first attempt.
    #[tokio::test(start_paused = true)]
    async fn test_codex_raw_success_on_first_attempt() {
        let mut mock = MockCodexExecutor::new();

        mock.expect_run()
            .times(1)
            .returning(|_| Ok("patch".to_string()));

        let result = generate_raw_with_retry_impl("test prompt", &mock).await;
        assert_eq!(result.unwrap(), "patch");
    }

    /// Test that generate_raw_with_retry_impl succeeds after transient failures.
    #[tokio::test(start_paused = true)]
    async fn test_codex_raw_retry_succeeds_after_failure() {
        let mut mock = MockCodexExecutor::new();

        let call_count = Arc::new(AtomicU32::new(0));
        let call_count_clone = call_count.clone();

        mock.expect_run().times(2).returning(move |_| {
            let count = call_count_clone.fetch_add(1, Ordering::SeqCst);
            if count == 0 {
                Err(CodexError::ExecutionFailed("transient".to_string()))
            } else {
                Ok("minor".to_string())
            }
        });

        let result = generate_raw_with_retry_impl("test prompt", &mock).await;
        assert_eq!(result.unwrap(), "minor");
        assert_eq!(call_count.load(Ordering::SeqCst), 2);
    }

    /// Test that the last error is preserved in RetriesExhausted.
    #[tokio::test(start_paused = true)]
    async fn test_codex_raw_retry_preserves_last_error() {
        let mut mock = MockCodexExecutor::new();

        let call_count = Arc::new(AtomicU32::new(0));
        let call_count_clone = call_count.clone();

        mock.expect_run().times(3).returning(move |_| {
            let count = call_count_clone.fetch_add(1, Ordering::SeqCst);
            match count {
                0 => Err(CodexError::Timeout(30)),
                1 => Err(CodexError::NonZeroExit {
                    code: 1,
                    stderr: "error".to_string(),
                }),
                _ => Err(CodexError::ExecutionFailed("final error".to_string())),
            }
        });

        let result = generate_raw_with_retry_impl("test", &mock).await;

        match result {
            Err(CodexError::RetriesExhausted(inner)) => {
                assert!(matches!(*inner, CodexError::ExecutionFailed(_)));
            }
            _ => panic!("Expected RetriesExhausted error"),
        }
    }

    // ============================================
    // Structured Retry Behavior Tests
    // ============================================

    /// Test that generate_with_retry_impl exhausts all 3 attempts on persistent failure.
    #[tokio::test(start_paused = true)]
    async fn test_codex_structured_retry_exhaustion() {
        let mut mock = MockCodexExecutor::new();

        let call_count = Arc::new(AtomicU32::new(0));
        let call_count_clone = call_count.clone();

        mock.expect_run().times(3).returning(move |_| {
            call_count_clone.fetch_add(1, Ordering::SeqCst);
            Err(CodexError::ExecutionFailed("persistent error".to_string()))
        });

        let result = generate_with_retry_impl("test prompt", &mock).await;

        assert!(matches!(result, Err(CodexError::RetriesExhausted(_))));
        assert_eq!(call_count.load(Ordering::SeqCst), 3);
    }

    /// Test that generate_with_retry_impl succeeds on first attempt with valid JSON.
    #[tokio::test(start_paused = true)]
    async fn test_codex_structured_success_on_first_attempt() {
        let mut mock = MockCodexExecutor::new();

        mock.expect_run()
            .times(1)
            .returning(|_| Ok(r#"{"entries": []}"#.to_string()));

        let result = generate_with_retry_impl("test prompt", &mock).await;

        assert!(result.is_ok());
        assert_eq!(result.unwrap().entries.len(), 0);
    }
}
