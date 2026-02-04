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

    // Write prompt to a temp file to avoid shell escaping issues
    // The prompt may contain diffs with special shell characters
    let temp_dir = std::env::temp_dir();
    let prompt_file = temp_dir.join(format!("keryx-prompt-{}.txt", std::process::id()));
    std::fs::write(&prompt_file, prompt).map_err(|e| ClaudeError::SpawnFailed(e))?;

    // Build command that reads prompt from file
    let claude_cmd = format!(
        "claude -p \"$(cat {})\" --output-format json --dangerously-skip-permissions",
        prompt_file.display()
    );

    // Use `script` to provide a pseudo-TTY for Claude Code
    // This works around Claude Code's TTY requirement bug (GitHub #9026)
    // Linux: script -q -c "command" /dev/null
    // macOS: script -q /dev/null command
    #[cfg(target_os = "macos")]
    let output = timeout(
        timeout_duration,
        Command::new("script")
            .arg("-q")
            .arg("/dev/null")
            .arg("sh")
            .arg("-c")
            .arg(&claude_cmd)
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output(),
    )
    .await
    .map_err(|_| ClaudeError::Timeout(timeout_secs))?
    .map_err(ClaudeError::SpawnFailed)?;

    #[cfg(not(target_os = "macos"))]
    let output = timeout(
        timeout_duration,
        Command::new("script")
            .arg("-q")
            .arg("-c")
            .arg(&claude_cmd)
            .arg("/dev/null")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output(),
    )
    .await
    .map_err(|_| ClaudeError::Timeout(timeout_secs))?
    .map_err(ClaudeError::SpawnFailed)?;

    // Clean up temp file
    let _ = std::fs::remove_file(&prompt_file);

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr).to_string();
        let code = output.status.code().unwrap_or(-1);
        return Err(ClaudeError::NonZeroExit { code, stderr });
    }

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    
    // Strip ANSI escape codes added by the script TTY wrapper
    let stdout = strip_ansi_codes(&stdout);
    Ok(stdout)
}

/// Strip ANSI escape codes from a string.
/// The `script` command adds terminal control sequences that we need to remove.
fn strip_ansi_codes(s: &str) -> String {
    // Use regex-like state machine to strip all ANSI sequences
    // Patterns: ESC [ ... letter, ESC ] ... BEL, ESC [ ? ... letter
    let mut result = String::with_capacity(s.len());
    let bytes = s.as_bytes();
    let mut i = 0;
    
    while i < bytes.len() {
        if bytes[i] == 0x1b {
            // ESC character - start of escape sequence
            i += 1;
            if i >= bytes.len() {
                break;
            }
            
            match bytes[i] {
                b'[' => {
                    // CSI sequence: ESC [ (params) (letter)
                    i += 1;
                    // Skip until we hit a letter (0x40-0x7E)
                    while i < bytes.len() {
                        let b = bytes[i];
                        i += 1;
                        if (0x40..=0x7E).contains(&b) {
                            break;
                        }
                    }
                }
                b']' => {
                    // OSC sequence: ESC ] ... BEL or ESC ] ... ESC \
                    i += 1;
                    while i < bytes.len() {
                        if bytes[i] == 0x07 {
                            // BEL terminates OSC
                            i += 1;
                            break;
                        } else if bytes[i] == 0x1b && i + 1 < bytes.len() && bytes[i + 1] == b'\\' {
                            // ST (ESC \) terminates OSC
                            i += 2;
                            break;
                        }
                        i += 1;
                    }
                }
                b'<' => {
                    // Private sequence ESC < ... - skip to end
                    i += 1;
                    while i < bytes.len() && !bytes[i].is_ascii_alphabetic() {
                        i += 1;
                    }
                    if i < bytes.len() {
                        i += 1; // skip terminating letter
                    }
                }
                _ => {
                    // Other ESC sequences - skip next char
                    i += 1;
                }
            }
        } else if bytes[i] == b'\r' {
            // Skip carriage returns
            i += 1;
        } else {
            result.push(bytes[i] as char);
            i += 1;
        }
    }
    
    result
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
        // Use /usr/bin/printf to ensure we get raw bytes (not shell built-in)
        // \xFF is invalid UTF-8 (it's a continuation byte without a start byte)
        let output = Command::new("/usr/bin/printf")
            .arg("valid\\xFFtext")
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
        assert!(
            stdout.contains("valid"),
            "Should contain valid text before invalid byte"
        );
        assert!(
            stdout.contains("text"),
            "Should contain valid text after invalid byte"
        );
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
        // Use /usr/bin/printf to ensure we get raw bytes
        // Redirect to stderr and exit with error code
        let output = Command::new("sh")
            .arg("-c")
            .arg("/usr/bin/printf 'error\\xFE\\xFFmsg' >&2; exit 1")
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .output()
            .await
            .expect("failed to execute command");

        assert!(!output.status.success());

        // from_utf8_lossy should handle invalid UTF-8 gracefully
        let stderr = String::from_utf8_lossy(&output.stderr);
        assert!(
            stderr.contains("error"),
            "Should contain text before invalid bytes"
        );
        assert!(
            stderr.contains("msg"),
            "Should contain text after invalid bytes"
        );

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

        let version_check = Command::new("false")
            .output()
            .await
            .expect("failed to run false");

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

    // ============================================
    // ANSI Escape Code Stripping Tests
    // ============================================

    /// Test that plain text without ANSI codes passes through unchanged.
    #[test]
    fn test_strip_ansi_plain_text() {
        let input = "Hello, World!";
        assert_eq!(strip_ansi_codes(input), "Hello, World!");
    }

    /// Test that simple CSI color codes are removed.
    #[test]
    fn test_strip_ansi_color_codes() {
        // Red text: ESC[31m ... ESC[0m
        let input = "\x1b[31mRed text\x1b[0m";
        assert_eq!(strip_ansi_codes(input), "Red text");
    }

    /// Test that multiple ANSI codes in sequence are all removed.
    #[test]
    fn test_strip_ansi_multiple_codes() {
        // Bold + Red + text + Reset
        let input = "\x1b[1m\x1b[31mBold Red\x1b[0m normal";
        assert_eq!(strip_ansi_codes(input), "Bold Red normal");
    }

    /// Test that cursor movement codes are removed.
    #[test]
    fn test_strip_ansi_cursor_codes() {
        // Cursor up 2 lines: ESC[2A
        let input = "line1\x1b[2Aline2";
        assert_eq!(strip_ansi_codes(input), "line1line2");
    }

    /// Test that private mode sequences (ESC[?...) are removed.
    #[test]
    fn test_strip_ansi_private_modes() {
        // Enable/disable cursor: ESC[?25h ESC[?25l
        let input = "\x1b[?25hvisible\x1b[?25l";
        assert_eq!(strip_ansi_codes(input), "visible");
    }

    /// Test that OSC sequences (ESC]...) with BEL terminator are removed.
    #[test]
    fn test_strip_ansi_osc_bel() {
        // Set window title: ESC]0;title BEL
        let input = "\x1b]0;Window Title\x07content";
        assert_eq!(strip_ansi_codes(input), "content");
    }

    /// Test that carriage returns are removed.
    #[test]
    fn test_strip_ansi_carriage_return() {
        let input = "line1\r\nline2\rline3";
        assert_eq!(strip_ansi_codes(input), "line1\nline2line3");
    }

    /// Test real-world Claude Code output pattern.
    #[test]
    fn test_strip_ansi_claude_output() {
        // Simulates the escape sequences added by script TTY wrapper
        let input = "{\"result\":\"test\"}\x1b[?1004l\x1b[?2004l\x1b[?25h\x1b]9;4;0;\x07\x1b[?25h";
        assert_eq!(strip_ansi_codes(input), "{\"result\":\"test\"}");
    }

    /// Test that JSON content is preserved while ANSI codes are stripped.
    #[test]
    fn test_strip_ansi_preserves_json() {
        let json = r#"{"subject": "test", "body": "content with\nnewlines"}"#;
        let input = format!("\x1b[32m{}\x1b[0m\r\n", json);
        assert_eq!(strip_ansi_codes(&input), format!("{}\n", json));
    }

    /// Test ESC < sequences (less common but seen in some terminals).
    #[test]
    fn test_strip_ansi_esc_less_than() {
        let input = "\x1b<utext\x1b<v";
        // ESC < followed by letter should be stripped
        assert_eq!(strip_ansi_codes(input), "text");
    }

    /// Test empty string.
    #[test]
    fn test_strip_ansi_empty() {
        assert_eq!(strip_ansi_codes(""), "");
    }

    /// Test string with only ANSI codes.
    #[test]
    fn test_strip_ansi_only_codes() {
        let input = "\x1b[31m\x1b[0m\x1b[?25h";
        assert_eq!(strip_ansi_codes(input), "");
    }
}
