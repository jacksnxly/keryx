//! Provider selection and fallback orchestration.

use std::fmt;

use async_trait::async_trait;

use crate::changelog::ChangelogOutput;
use crate::claude;
use crate::codex;
use crate::error::{ClaudeError, CodexError};

/// Supported LLM providers.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Provider {
    Claude,
    Codex,
}

impl Provider {
    pub fn as_str(&self) -> &'static str {
        match self {
            Provider::Claude => "Claude",
            Provider::Codex => "Codex",
        }
    }
}

impl fmt::Display for Provider {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

/// Primary + fallback selection.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ProviderSelection {
    pub primary: Provider,
    pub fallback: Provider,
}

impl ProviderSelection {
    pub fn from_primary(primary: Provider) -> Self {
        let fallback = match primary {
            Provider::Claude => Provider::Codex,
            Provider::Codex => Provider::Claude,
        };
        Self { primary, fallback }
    }
}

impl Default for ProviderSelection {
    fn default() -> Self {
        ProviderSelection::from_primary(Provider::Claude)
    }
}

/// Provider-specific error wrapper.
#[derive(Debug)]
pub enum LlmProviderError {
    Claude(ClaudeError),
    Codex(CodexError),
}

impl LlmProviderError {
    pub fn provider(&self) -> Provider {
        match self {
            LlmProviderError::Claude(_) => Provider::Claude,
            LlmProviderError::Codex(_) => Provider::Codex,
        }
    }

    pub fn summary(&self) -> String {
        match self {
            LlmProviderError::Claude(err) => summarize_claude_error(err),
            LlmProviderError::Codex(err) => summarize_codex_error(err),
        }
    }

    pub fn detail(&self) -> String {
        match self {
            LlmProviderError::Claude(err) => err.to_string(),
            LlmProviderError::Codex(err) => err.to_string(),
        }
    }
}

impl fmt::Display for LlmProviderError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.summary())
    }
}

impl std::error::Error for LlmProviderError {}

impl From<ClaudeError> for LlmProviderError {
    fn from(err: ClaudeError) -> Self {
        LlmProviderError::Claude(err)
    }
}

impl From<CodexError> for LlmProviderError {
    fn from(err: CodexError) -> Self {
        LlmProviderError::Codex(err)
    }
}

/// LLM orchestration error.
#[derive(Debug)]
pub enum LlmError {
    AllProvidersFailed {
        primary: Provider,
        primary_error: LlmProviderError,
        fallback: Provider,
        fallback_error: LlmProviderError,
    },
}

impl LlmError {
    pub fn summary(&self) -> String {
        match self {
            LlmError::AllProvidersFailed {
                primary,
                primary_error,
                fallback,
                fallback_error,
            } => format!(
                "Both LLM providers failed. {} error: {}. {} error: {}.",
                primary,
                primary_error.summary(),
                fallback,
                fallback_error.summary()
            ),
        }
    }

    pub fn detailed(&self) -> String {
        match self {
            LlmError::AllProvidersFailed {
                primary,
                primary_error,
                fallback,
                fallback_error,
            } => format!(
                "Both LLM providers failed. {} error: {}. {} error: {}.",
                primary,
                primary_error.detail(),
                fallback,
                fallback_error.detail()
            ),
        }
    }

    pub fn primary_error(&self) -> Option<&LlmProviderError> {
        match self {
            LlmError::AllProvidersFailed { primary_error, .. } => Some(primary_error),
        }
    }

    pub fn fallback_error(&self) -> Option<&LlmProviderError> {
        match self {
            LlmError::AllProvidersFailed { fallback_error, .. } => Some(fallback_error),
        }
    }
}

impl fmt::Display for LlmError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(&self.summary())
    }
}

impl std::error::Error for LlmError {}

/// Successful generation with metadata.
pub struct LlmCompletion {
    pub output: ChangelogOutput,
    pub provider: Provider,
    pub primary_error: Option<LlmProviderError>,
}

#[async_trait]
trait ProviderRunner {
    async fn run(&self, provider: Provider, prompt: &str) -> Result<ChangelogOutput, LlmProviderError>;
}

struct DefaultRunner;

#[async_trait]
impl ProviderRunner for DefaultRunner {
    async fn run(&self, provider: Provider, prompt: &str) -> Result<ChangelogOutput, LlmProviderError> {
        match provider {
            Provider::Claude => claude::generate_with_retry(prompt).await.map_err(LlmProviderError::from),
            Provider::Codex => codex::generate_with_retry(prompt).await.map_err(LlmProviderError::from),
        }
    }
}

/// Provider router with fallback and stickiness.
pub struct LlmRouter {
    primary: Provider,
    fallback: Provider,
}

impl LlmRouter {
    pub fn new(selection: ProviderSelection) -> Self {
        Self {
            primary: selection.primary,
            fallback: selection.fallback,
        }
    }

    pub fn primary(&self) -> Provider {
        self.primary
    }

    pub fn fallback(&self) -> Provider {
        self.fallback
    }

    pub async fn generate(&mut self, prompt: &str) -> Result<LlmCompletion, LlmError> {
        let runner = DefaultRunner;
        self.generate_with_runner(prompt, &runner).await
    }

    async fn generate_with_runner<R: ProviderRunner>(
        &mut self,
        prompt: &str,
        runner: &R,
    ) -> Result<LlmCompletion, LlmError> {
        let primary = self.primary;
        let fallback = self.fallback;

        match runner.run(primary, prompt).await {
            Ok(output) => Ok(LlmCompletion {
                output,
                provider: primary,
                primary_error: None,
            }),
            Err(primary_error) => match runner.run(fallback, prompt).await {
                Ok(output) => {
                    self.primary = fallback;
                    self.fallback = primary;
                    Ok(LlmCompletion {
                        output,
                        provider: fallback,
                        primary_error: Some(primary_error),
                    })
                }
                Err(fallback_error) => Err(LlmError::AllProvidersFailed {
                    primary,
                    primary_error,
                    fallback,
                    fallback_error,
                }),
            },
        }
    }
}

fn summarize_claude_error(err: &ClaudeError) -> String {
    match err {
        ClaudeError::NotInstalled => "Claude CLI not found".to_string(),
        ClaudeError::ExecutionFailed(_) => "Claude CLI reported an error".to_string(),
        ClaudeError::SpawnFailed(_) => "Failed to start Claude CLI".to_string(),
        ClaudeError::InvalidJson(_) => "Claude returned invalid JSON".to_string(),
        ClaudeError::Timeout(secs) => format!("Claude timed out after {}s", secs),
        ClaudeError::NonZeroExit { code, .. } => format!("Claude CLI exited with code {}", code),
        ClaudeError::RetriesExhausted(_) => "Claude failed after retries".to_string(),
        ClaudeError::SerializationFailed(_) => "Failed to build prompt".to_string(),
    }
}

fn summarize_codex_error(err: &CodexError) -> String {
    match err {
        CodexError::NotInstalled => "Codex CLI not found".to_string(),
        CodexError::ExecutionFailed(_) => "Codex CLI reported an error".to_string(),
        CodexError::SpawnFailed(_) => "Failed to start Codex CLI".to_string(),
        CodexError::InvalidJson(_) => "Codex returned invalid JSON".to_string(),
        CodexError::Timeout(secs) => format!("Codex timed out after {}s", secs),
        CodexError::NonZeroExit { code, .. } => format!("Codex CLI exited with code {}", code),
        CodexError::RetriesExhausted(_) => "Codex failed after retries".to_string(),
        CodexError::SerializationFailed(_) => "Failed to build prompt".to_string(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    struct FakeRunner {
        claude_ok: bool,
        codex_ok: bool,
    }

    #[async_trait]
    impl ProviderRunner for FakeRunner {
        async fn run(&self, provider: Provider, _prompt: &str) -> Result<ChangelogOutput, LlmProviderError> {
            match provider {
                Provider::Claude if self.claude_ok => Ok(ChangelogOutput { entries: Vec::new() }),
                Provider::Codex if self.codex_ok => Ok(ChangelogOutput { entries: Vec::new() }),
                Provider::Claude => Err(LlmProviderError::Claude(ClaudeError::NotInstalled)),
                Provider::Codex => Err(LlmProviderError::Codex(CodexError::NotInstalled)),
            }
        }
    }

    #[test]
    fn default_selection_is_claude_then_codex() {
        let selection = ProviderSelection::default();
        assert_eq!(selection.primary, Provider::Claude);
        assert_eq!(selection.fallback, Provider::Codex);
    }

    #[test]
    fn codex_selection_sets_fallback_to_claude() {
        let selection = ProviderSelection::from_primary(Provider::Codex);
        assert_eq!(selection.primary, Provider::Codex);
        assert_eq!(selection.fallback, Provider::Claude);
    }

    #[tokio::test]
    async fn router_swaps_primary_after_fallback_success() {
        let mut router = LlmRouter::new(ProviderSelection::default());
        let runner = FakeRunner {
            claude_ok: false,
            codex_ok: true,
        };

        let result = router.generate_with_runner("test", &runner).await;
        assert!(result.is_ok());
        assert_eq!(router.primary(), Provider::Codex);
        assert_eq!(router.fallback(), Provider::Claude);
    }
}
