//! Claude CLI spawning.

use std::process::Stdio;
use tokio::process::Command;

use crate::error::ClaudeError;

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
pub async fn run_claude(prompt: &str) -> Result<String, ClaudeError> {
    let output = Command::new("claude")
        .arg("-p")
        .arg(prompt)
        .arg("--output-format")
        .arg("json")
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .output()
        .await
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
    // Integration tests would require actual Claude CLI
}
