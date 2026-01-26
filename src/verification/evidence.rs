//! Evidence types for changelog verification.

use serde::{Deserialize, Serialize};

/// Complete verification evidence for all changelog entries.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VerificationEvidence {
    /// Evidence gathered for each entry.
    pub entries: Vec<EntryEvidence>,
    /// Project structure summary.
    pub project_structure: Option<String>,
    /// Key files content (e.g., Cargo.toml, package.json).
    pub key_files: Vec<KeyFileContent>,
}

/// Evidence for a single changelog entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EntryEvidence {
    /// The original entry description.
    pub original_description: String,
    /// The category (Added, Changed, etc.).
    pub category: String,
    /// Keywords extracted and their matches in the codebase.
    pub keyword_matches: Vec<KeywordMatch>,
    /// Numeric claims found and their verification.
    pub count_checks: Vec<CountCheck>,
    /// Stub/TODO indicators found.
    pub stub_indicators: Vec<StubIndicator>,
    /// Overall confidence assessment.
    pub confidence: Confidence,
}

/// A keyword match found in the codebase.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeywordMatch {
    /// The keyword searched for.
    pub keyword: String,
    /// Files where the keyword was found.
    pub files_found: Vec<String>,
    /// Number of occurrences.
    pub occurrence_count: usize,
    /// Sample lines showing context (first few matches).
    pub sample_lines: Vec<String>,
    /// Whether the implementation appears complete (no TODO/stub markers nearby).
    pub appears_complete: bool,
}

/// Verification of a numeric claim.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CountCheck {
    /// The original claim text (e.g., "8 templates").
    pub claimed_text: String,
    /// The number claimed.
    pub claimed_count: Option<usize>,
    /// The actual count found.
    pub actual_count: Option<usize>,
    /// Where the count was found.
    pub source_location: Option<String>,
    /// Whether the counts match.
    pub matches: bool,
}

/// Indicator that code may be incomplete.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StubIndicator {
    /// The file where the indicator was found.
    pub file: String,
    /// The line number.
    pub line: usize,
    /// The indicator text (e.g., "TODO", "unimplemented!").
    pub indicator: String,
    /// Context around the indicator.
    pub context: String,
}

/// Confidence level for an entry.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Confidence {
    /// High confidence - multiple sources, no stubs.
    High,
    /// Medium confidence - some evidence found.
    Medium,
    /// Low confidence - minimal evidence or stub indicators.
    Low,
}

impl std::fmt::Display for Confidence {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Confidence::High => write!(f, "high"),
            Confidence::Medium => write!(f, "medium"),
            Confidence::Low => write!(f, "low"),
        }
    }
}

/// Content of a key file for context.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeyFileContent {
    /// File path.
    pub path: String,
    /// File content (may be truncated).
    pub content: String,
}

impl VerificationEvidence {
    /// Create empty evidence.
    pub fn empty() -> Self {
        Self {
            entries: Vec::new(),
            project_structure: None,
            key_files: Vec::new(),
        }
    }

    /// Check if any entries have low confidence.
    pub fn has_low_confidence_entries(&self) -> bool {
        self.entries.iter().any(|e| e.confidence == Confidence::Low)
    }

    /// Get entries with low confidence.
    pub fn low_confidence_entries(&self) -> Vec<&EntryEvidence> {
        self.entries
            .iter()
            .filter(|e| e.confidence == Confidence::Low)
            .collect()
    }
}
