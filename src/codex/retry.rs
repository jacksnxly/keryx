//! Exponential backoff retry logic for Codex CLI.

use std::time::Duration;

use async_trait::async_trait;
use backoff::backoff::Backoff;
use backoff::ExponentialBackoff;

use crate::changelog::ChangelogOutput;
use crate::error::CodexError;

use super::subprocess::run_codex;

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

/// Configuration: 3 total attempts, base 1s, max 30s.
const MAX_ATTEMPTS: u32 = 3;
const INITIAL_INTERVAL_SECS: u64 = 1;
const MAX_INTERVAL_SECS: u64 = 30;

/// Generate changelog entries with retry logic.
///
/// Makes up to 3 attempts with exponential backoff on failure.
pub async fn generate_with_retry(prompt: &str) -> Result<ChangelogOutput, CodexError> {
    generate_with_retry_impl(prompt, &DefaultExecutor).await
}

/// Internal implementation that accepts any executor (for testing).
pub(crate) async fn generate_with_retry_impl<E: CodexExecutor>(
    prompt: &str,
    executor: &E,
) -> Result<ChangelogOutput, CodexError> {
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

    Err(CodexError::RetriesExhausted(Box::new(
        last_error.expect("last_error should be Some after failed retries"),
    )))
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
    serde_json::from_str(&json_str)
        .map_err(|e| CodexError::InvalidJson(format!("Failed to parse: {}. Content: {}", e, response)))
}

/// Extract JSON from Codex's response (may be wrapped in markdown).
fn extract_json(response: &str) -> String {
    if let Some(start) = response.find("```json")
        && let Some(end) = response[start + 7..].find("```")
    {
        return response[start + 7..start + 7 + end].trim().to_string();
    }

    if let Some(json_str) = find_valid_json_object(response) {
        return json_str;
    }

    response.to_string()
}

/// Find a valid JSON object in a string using proper brace matching.
fn find_valid_json_object(text: &str) -> Option<String> {
    for (start_idx, _) in text.match_indices('{') {
        let candidate = &text[start_idx..];

        if let Ok(value) = serde_json::from_str::<serde_json::Value>(candidate) {
            if let Ok(json_str) = serde_json::to_string(&value) {
                return Some(json_str);
            }
        }

        if let Some(json_str) = extract_balanced_braces(candidate) {
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
