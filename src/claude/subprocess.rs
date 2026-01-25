//! Claude CLI spawning.

use std::env;
use std::process::Stdio;
use std::time::Duration;

use tokio::process::Command;
use tokio::time::timeout;

use crate::error::ClaudeError;

/// Default timeout for Claude subprocess execution (5 minutes).
const DEFAULT_TIMEOUT_SECS: u64 = 300;

/// Environment variable to override the default timeout.
const TIMEOUT_ENV_VAR: &str = "KERYX_CLAUDE_TIMEOUT";

/// Get the configured timeout duration.
///
/// Reads from KERYX_CLAUDE_TIMEOUT environment variable if set,
/// otherwise uses the default of 300 seconds.
fn get_timeout() -> Duration {
    env::var(TIMEOUT_ENV_VAR)
        .ok()
        .and_then(|v| v.parse::<u64>().ok())
        .map(Duration::from_secs)
        .unwrap_or_else(|| Duration::from_secs(DEFAULT_TIMEOUT_SECS))
}

/// Check if Claude Code CLI is installed and accessible.
///
/// Uses the `which` crate for cross-platform executable detection.
/// Works on Windows (where.exe), Unix (which), and WASI.
pub async fn check_claude_installed() -> Result<(), ClaudeError> {
    // Use `which` crate for cross-platform executable detection
    // This replaces the Unix-only `which` command with a solution that
    // works on Windows, macOS, Linux, and WASI
    if which::which("claude").is_err() {
        return Err(ClaudeError::NotInstalled);
    }

    // Verify it actually runs (check version)
    let version_check = Command::new("claude")
        .arg("--version")
        .output()
        .await
        .map_err(ClaudeError::SpawnFailed)?;

    if !version_check.status.success() {
        return Err(ClaudeError::NotInstalled);
    }

    Ok(())
}

/// Run Claude CLI with a prompt and return the response.
///
/// Uses the -p flag for prompt and --output-format json per spec.
///
/// # Timeout
///
/// The subprocess has a default timeout of 5 minutes (300 seconds).
/// This can be configured via the `KERYX_CLAUDE_TIMEOUT` environment
/// variable (value in seconds).
///
/// If the timeout is exceeded, returns `ClaudeError::Timeout`.
pub async fn run_claude(prompt: &str) -> Result<String, ClaudeError> {
    let timeout_duration = get_timeout();
    let timeout_secs = timeout_duration.as_secs();

    let output = timeout(
        timeout_duration,
        Command::new("claude")
            .arg("-p")
            .arg(prompt)
            .arg("--output-format")
            .arg("json")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output(),
    )
    .await
    .map_err(|_| ClaudeError::Timeout(timeout_secs))?
    .map_err(ClaudeError::SpawnFailed)?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let code = output.status.code().unwrap_or(-1);
        return Err(ClaudeError::NonZeroExit { code, stderr });
    }

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    Ok(stdout)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_get_timeout_default() {
        // Clear any existing env var
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
}
