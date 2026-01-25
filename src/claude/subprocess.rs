//! Claude CLI spawning.

use std::env;
use std::process::Stdio;
use std::time::Duration;

use tokio::process::Command;
use tokio::time::timeout;
use tracing::warn;

use crate::error::ClaudeError;

/// Default timeout for Claude subprocess execution (5 minutes).
const DEFAULT_TIMEOUT_SECS: u64 = 300;

/// Environment variable to override the default timeout.
const TIMEOUT_ENV_VAR: &str = "KERYX_CLAUDE_TIMEOUT";

/// Get the configured timeout duration.
///
/// Reads from KERYX_CLAUDE_TIMEOUT environment variable if set,
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

    // ============================================
    // Timeout Configuration Tests
    // ============================================

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

    // ============================================
    // Subprocess Error Handling Tests (KRX-034)
    // ============================================
    //
    // These tests verify the subprocess error handling patterns used in run_claude.
    // Since run_claude is hardcoded to call the claude binary, we test the underlying
    // patterns using simple shell commands that produce the same types of outputs.

    /// Test that non-zero exit codes are properly detected and converted to errors.
    /// This mirrors the behavior in run_claude lines 98-101.
    #[tokio::test]
    #[cfg(unix)]
    async fn test_subprocess_non_zero_exit_code() {
        // Use 'false' command which always exits with code 1
        let output = Command::new("false")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .expect("failed to execute 'false' command");

        assert!(!output.status.success());
        assert_eq!(output.status.code(), Some(1));

        // Verify our error construction pattern works
        let code = output.status.code().unwrap_or(-1);
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let error = ClaudeError::NonZeroExit { code, stderr };

        match error {
            ClaudeError::NonZeroExit { code: c, .. } => assert_eq!(c, 1),
            _ => panic!("Expected NonZeroExit error"),
        }
    }

    /// Test that specific exit codes are captured correctly.
    #[tokio::test]
    #[cfg(unix)]
    async fn test_subprocess_specific_exit_code() {
        let output = Command::new("sh")
            .arg("-c")
            .arg("exit 42")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .expect("failed to execute shell command");

        assert!(!output.status.success());
        assert_eq!(output.status.code(), Some(42));
    }

    /// Test that stderr output is captured correctly in error cases.
    /// This mirrors the behavior in run_claude lines 99-101.
    #[tokio::test]
    #[cfg(unix)]
    async fn test_subprocess_stderr_captured_in_error() {
        let error_message = "Claude API rate limit exceeded";
        let output = Command::new("sh")
            .arg("-c")
            .arg(format!("echo '{}' >&2; exit 1", error_message))
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .expect("failed to execute shell command");

        assert!(!output.status.success());

        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        assert!(
            stderr.contains(error_message),
            "Expected stderr to contain '{}', got: '{}'",
            error_message,
            stderr
        );

        // Verify error construction includes stderr
        let error = ClaudeError::NonZeroExit {
            code: output.status.code().unwrap_or(-1),
            stderr: stderr.clone(),
        };
        let error_str = format!("{}", error);
        assert!(
            error_str.contains(error_message),
            "Error message should contain stderr content"
        );
    }

    /// Test that multi-line stderr is captured completely.
    #[tokio::test]
    #[cfg(unix)]
    async fn test_subprocess_multiline_stderr() {
        let output = Command::new("sh")
            .arg("-c")
            .arg("echo 'line 1' >&2; echo 'line 2' >&2; echo 'line 3' >&2; exit 1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .expect("failed to execute shell command");

        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        assert!(stderr.contains("line 1"));
        assert!(stderr.contains("line 2"));
        assert!(stderr.contains("line 3"));
    }

    /// Test that timeout is respected when subprocess hangs.
    /// Uses a short 100ms timeout to keep tests fast.
    #[tokio::test]
    #[cfg(unix)]
    async fn test_subprocess_timeout_is_respected() {
        let timeout_duration = Duration::from_millis(100);

        let result = timeout(
            timeout_duration,
            Command::new("sleep")
                .arg("10") // 10 seconds - will definitely timeout
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .output(),
        )
        .await;

        // Should timeout, not complete
        assert!(result.is_err(), "Expected timeout but command completed");

        // Verify we can construct the appropriate error
        if result.is_err() {
            let error = ClaudeError::Timeout(timeout_duration.as_secs());
            match error {
                ClaudeError::Timeout(secs) => assert_eq!(secs, 0), // 100ms = 0 whole seconds
                _ => panic!("Expected Timeout error"),
            }
        }
    }

    /// Test that fast commands complete before timeout.
    #[tokio::test]
    #[cfg(unix)]
    async fn test_subprocess_completes_before_timeout() {
        let timeout_duration = Duration::from_secs(5);

        let result = timeout(
            timeout_duration,
            Command::new("echo")
                .arg("quick response")
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .output(),
        )
        .await;

        assert!(result.is_ok(), "Command should complete before timeout");
        let output = result.unwrap().expect("Command should succeed");
        assert!(output.status.success());
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(stdout.contains("quick response"));
    }

    /// Test that non-UTF8 output in stdout is handled gracefully.
    /// This tests the String::from_utf8_lossy pattern used in run_claude line 104.
    #[tokio::test]
    #[cfg(unix)]
    async fn test_subprocess_non_utf8_stdout_handled() {
        // printf outputs raw bytes - \xFF is invalid UTF-8
        let output = Command::new("sh")
            .arg("-c")
            .arg("printf 'valid\\xFFtext'")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .expect("failed to execute printf command");

        assert!(output.status.success());

        // Raw bytes should contain invalid UTF-8
        assert!(
            String::from_utf8(output.stdout.clone()).is_err(),
            "Raw output should contain invalid UTF-8"
        );

        // from_utf8_lossy should handle it gracefully (replaces invalid bytes)
        let stdout = String::from_utf8_lossy(&output.stdout);
        assert!(stdout.contains("valid"), "Should contain valid text before invalid byte");
        assert!(stdout.contains("text"), "Should contain valid text after invalid byte");
        assert!(
            stdout.contains('\u{FFFD}'),
            "Should contain Unicode replacement character for invalid bytes"
        );
    }

    /// Test that non-UTF8 output in stderr is handled gracefully.
    /// This tests the String::from_utf8_lossy pattern used in run_claude line 99.
    #[tokio::test]
    #[cfg(unix)]
    async fn test_subprocess_non_utf8_stderr_handled() {
        let output = Command::new("sh")
            .arg("-c")
            .arg("printf 'error\\xFE\\xFFmsg' >&2; exit 1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .expect("failed to execute command");

        assert!(!output.status.success());

        // from_utf8_lossy should handle invalid UTF-8 gracefully
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(stderr.contains("error"), "Should contain text before invalid bytes");
        assert!(stderr.contains("msg"), "Should contain text after invalid bytes");

        // Error should be constructable with lossy string
        let error = ClaudeError::NonZeroExit {
            code: output.status.code().unwrap_or(-1),
            stderr: stderr.to_string(),
        };
        assert!(matches!(error, ClaudeError::NonZeroExit { .. }));
    }

    /// Test check_claude_installed behavior when version check fails.
    /// Since we can't easily mock `which::which`, we test the version check path
    /// by calling a command that exists but returns non-zero for --version.
    #[tokio::test]
    #[cfg(unix)]
    async fn test_version_check_non_zero_exit() {
        // Test the pattern: if a command's --version returns non-zero, it should be treated as not installed
        // We use 'false' as a stand-in since it always returns non-zero

        let version_check = Command::new("false").output().await.expect("failed to run false");

        assert!(!version_check.status.success());

        // This is how check_claude_installed would treat it (lines 61-63)
        if !version_check.status.success() {
            let error = ClaudeError::NotInstalled;
            assert!(
                error.to_string().contains("not found"),
                "NotInstalled error should mention CLI not found"
            );
        }
    }

    /// Test spawn failure produces appropriate error.
    #[tokio::test]
    async fn test_subprocess_spawn_failure() {
        // Try to run a command that doesn't exist
        let result = Command::new("nonexistent_command_12345")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await;

        assert!(result.is_err());

        // Verify we can construct SpawnFailed error from io::Error
        let io_error = result.unwrap_err();
        let error = ClaudeError::SpawnFailed(io_error);
        assert!(matches!(error, ClaudeError::SpawnFailed(_)));
    }

    /// Test that both stdout and stderr are captured simultaneously.
    #[tokio::test]
    #[cfg(unix)]
    async fn test_subprocess_captures_both_streams() {
        let output = Command::new("sh")
            .arg("-c")
            .arg("echo 'stdout content'; echo 'stderr content' >&2; exit 0")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .expect("failed to execute command");

        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);

        assert!(stdout.contains("stdout content"));
        assert!(stderr.contains("stderr content"));
    }
}
