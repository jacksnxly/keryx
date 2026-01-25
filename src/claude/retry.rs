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

/// Parse Claude's JSON response into ChangelogOutput.
fn parse_claude_response(response: &str) -> Result<ChangelogOutput, ClaudeError> {
    // Claude's response may contain markdown code blocks, extract JSON
    let json_str = extract_json(response);

    serde_json::from_str(&json_str)
        .map_err(|e| ClaudeError::InvalidJson(format!("Failed to parse: {}. Response: {}", e, response)))
}

/// Extract JSON from Claude's response (may be wrapped in markdown).
fn extract_json(response: &str) -> String {
    // Try to find JSON block in markdown
    if let Some(start) = response.find("```json") {
        if let Some(end) = response[start + 7..].find("```") {
            return response[start + 7..start + 7 + end].trim().to_string();
        }
    }

    // Try to find raw JSON (starts with {)
    if let Some(start) = response.find('{') {
        if let Some(end) = response.rfind('}') {
            return response[start..=end].to_string();
        }
    }

    response.to_string()
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
        assert_eq!(json, r#"{"entries": []}"#);
    }

    #[test]
    fn test_extract_json_with_surrounding_text() {
        let response = r#"Here is the result: {"entries": []} Hope this helps!"#;
        let json = extract_json(response);
        assert_eq!(json, r#"{"entries": []}"#);
    }
}
