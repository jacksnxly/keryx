//! Codex CLI spawning.

use std::env;
use std::io::Write;
use std::process::Stdio;
use std::time::Duration;

use tempfile::NamedTempFile;
use tokio::process::Command;
use tokio::time::timeout;
use tracing::warn;

use crate::error::CodexError;

/// Default timeout for Codex subprocess execution (5 minutes).
const DEFAULT_TIMEOUT_SECS: u64 = 300;

/// Environment variable to override the default timeout.
const TIMEOUT_ENV_VAR: &str = "KERYX_CODEX_TIMEOUT";

/// JSON schema for changelog output (used by Codex CLI).
const CHANGELOG_SCHEMA: &str = r#"{
  "type": "object",
  "properties": {
    "entries": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "category": {
            "type": "string",
            "enum": ["Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"]
          },
          "description": { "type": "string" }
        },
        "required": ["category", "description"],
        "additionalProperties": false
      }
    }
  },
  "required": ["entries"],
  "additionalProperties": false
}"#;

/// Get the configured timeout duration.
///
/// Reads from KERYX_CODEX_TIMEOUT environment variable if set,
/// otherwise uses the default of 300 seconds.
///
/// Logs a warning if the environment variable is set but contains
/// an invalid value (non-numeric, empty, or negative).
fn get_timeout() -> Duration {
    match env::var(TIMEOUT_ENV_VAR) {
        Ok(v) if !v.is_empty() => match v.parse::<u64>() {
            Ok(secs) => Duration::from_secs(secs),
            Err(_) => {
                warn!(
                    "Invalid {} value '{}', using default {}s",
                    TIMEOUT_ENV_VAR, v, DEFAULT_TIMEOUT_SECS
                );
                Duration::from_secs(DEFAULT_TIMEOUT_SECS)
            }
        },
        _ => Duration::from_secs(DEFAULT_TIMEOUT_SECS),
    }
}

/// Check if Codex CLI is installed and accessible.
///
/// Uses the `which` crate for cross-platform executable detection.
/// Works on Windows (where.exe), Unix (which), and WASI.
pub async fn check_codex_installed() -> Result<(), CodexError> {
    if which::which("codex").is_err() {
        return Err(CodexError::NotInstalled);
    }

    let version_check = Command::new("codex")
        .arg("--version")
        .output()
        .await
        .map_err(CodexError::SpawnFailed)?;

    if !version_check.status.success() {
        return Err(CodexError::NotInstalled);
    }

    Ok(())
}

/// Run Codex CLI with a prompt and return the response.
///
/// Uses `codex exec` with --output-schema to enforce JSON output.
///
/// # Timeout
///
/// The subprocess has a default timeout of 5 minutes (300 seconds).
/// This can be configured via the `KERYX_CODEX_TIMEOUT` environment
/// variable (value in seconds).
///
/// If the timeout is exceeded, returns `CodexError::Timeout`.
pub async fn run_codex(prompt: &str) -> Result<String, CodexError> {
    let mut schema_file = NamedTempFile::new()
        .map_err(|e| CodexError::ExecutionFailed(format!("Failed to create schema file: {}", e)))?;
    schema_file
        .write_all(CHANGELOG_SCHEMA.as_bytes())
        .map_err(|e| CodexError::ExecutionFailed(format!("Failed to write schema file: {}", e)))?;

    run_codex_command(
        prompt,
        &["--output-schema", &schema_file.path().display().to_string()],
    )
    .await
}

/// Run Codex CLI with a prompt and return the raw text response.
///
/// Unlike `run_codex`, this does **not** use `--output-schema`,
/// so the response is free-form text rather than structured JSON.
/// Used for tasks like version-bump determination where the LLM
/// returns a simple JSON blob without needing a schema file.
pub async fn run_codex_raw(prompt: &str) -> Result<String, CodexError> {
    run_codex_command(prompt, &[]).await
}

/// Shared subprocess helper: runs `codex exec [extra_args...] <prompt>`.
async fn run_codex_command(prompt: &str, extra_args: &[&str]) -> Result<String, CodexError> {
    let timeout_duration = get_timeout();
    let timeout_secs = timeout_duration.as_secs();

    let mut cmd = Command::new("codex");
    cmd.arg("exec");
    for arg in extra_args {
        cmd.arg(arg);
    }
    cmd.arg(prompt)
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());

    let output = timeout(timeout_duration, cmd.output())
        .await
        .map_err(|_| CodexError::Timeout(timeout_secs))?
        .map_err(CodexError::SpawnFailed)?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let code = output.status.code().unwrap_or(-1);
        return Err(CodexError::NonZeroExit { code, stderr });
    }

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    Ok(stdout)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_timeout_default() {
        temp_env::with_var_unset(TIMEOUT_ENV_VAR, || {
            let timeout = get_timeout();
            assert_eq!(timeout, Duration::from_secs(DEFAULT_TIMEOUT_SECS));
        });
    }

    #[test]
    fn test_get_timeout_from_env() {
        temp_env::with_var(TIMEOUT_ENV_VAR, Some("60"), || {
            let timeout = get_timeout();
            assert_eq!(timeout, Duration::from_secs(60));
        });
    }

    #[test]
    fn test_get_timeout_invalid_env_uses_default() {
        temp_env::with_var(TIMEOUT_ENV_VAR, Some("not_a_number"), || {
            let timeout = get_timeout();
            assert_eq!(timeout, Duration::from_secs(DEFAULT_TIMEOUT_SECS));
        });
    }

    #[test]
    fn test_get_timeout_empty_env_uses_default() {
        temp_env::with_var(TIMEOUT_ENV_VAR, Some(""), || {
            let timeout = get_timeout();
            assert_eq!(timeout, Duration::from_secs(DEFAULT_TIMEOUT_SECS));
        });
    }

    #[test]
    fn test_schema_is_valid_json() {
        let value: serde_json::Value =
            serde_json::from_str(CHANGELOG_SCHEMA).expect("schema should be valid JSON");
        assert!(value.get("properties").is_some());
    }
}
