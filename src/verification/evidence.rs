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
#[derive(Debug, Clone, Deserialize)]
pub struct CountCheck {
    /// The original claim text (e.g., "8 templates").
    pub claimed_text: String,
    /// The number claimed.
    pub claimed_count: Option<usize>,
    /// The actual count found.
    pub actual_count: Option<usize>,
    /// Where the count was found.
    pub source_location: Option<String>,
}

impl CountCheck {
    /// Returns true if counts match or if actual_count is unknown.
    ///
    /// When `actual_count` is `None`, we give the benefit of the doubt
    /// and assume the claim matches (we couldn't verify it either way).
    pub fn matches(&self) -> bool {
        match (self.claimed_count, self.actual_count) {
            (Some(claimed), Some(actual)) => claimed == actual,
            _ => true, // Unknown actual count = assume match
        }
    }
}

impl Serialize for CountCheck {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        use serde::ser::SerializeStruct;

        let mut state = serializer.serialize_struct("CountCheck", 5)?;
        state.serialize_field("claimed_text", &self.claimed_text)?;
        state.serialize_field("claimed_count", &self.claimed_count)?;
        state.serialize_field("actual_count", &self.actual_count)?;
        state.serialize_field("source_location", &self.source_location)?;
        state.serialize_field("matches", &self.matches())?;
        state.end()
    }
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
///
/// Confidence is calculated from a score starting at 50, with boosts for
/// keyword matches and penalties for stub indicators and count mismatches.
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum Confidence {
    /// High confidence (score >= 70).
    ///
    /// Strong evidence: multiple keyword matches found across files,
    /// implementations appear complete (no stub markers nearby),
    /// and numeric claims match actual counts.
    High,
    /// Medium confidence (score 40-69).
    ///
    /// Moderate evidence: some keyword matches found, but may have
    /// stub indicators, single-file matches, or minor count discrepancies.
    Medium,
    /// Low confidence (score < 40).
    ///
    /// Weak evidence: minimal or no keyword matches, multiple stub
    /// indicators, significant count mismatches, or combinations thereof.
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

#[cfg(test)]
mod tests {
    use super::*;

    fn create_entry(description: &str, confidence: Confidence) -> EntryEvidence {
        EntryEvidence {
            original_description: description.to_string(),
            category: "Added".to_string(),
            keyword_matches: vec![],
            count_checks: vec![],
            stub_indicators: vec![],
            confidence,
        }
    }

    #[test]
    fn test_verification_evidence_empty() {
        let evidence = VerificationEvidence::empty();

        assert!(evidence.entries.is_empty());
        assert!(evidence.project_structure.is_none());
        assert!(evidence.key_files.is_empty());
    }

    #[test]
    fn test_has_low_confidence_entries_false_when_empty() {
        let evidence = VerificationEvidence::empty();
        assert!(!evidence.has_low_confidence_entries());
    }

    #[test]
    fn test_has_low_confidence_entries_false_when_all_high() {
        let mut evidence = VerificationEvidence::empty();
        evidence.entries.push(create_entry("Feature A", Confidence::High));
        evidence.entries.push(create_entry("Feature B", Confidence::High));

        assert!(!evidence.has_low_confidence_entries());
    }

    #[test]
    fn test_has_low_confidence_entries_false_when_all_medium() {
        let mut evidence = VerificationEvidence::empty();
        evidence.entries.push(create_entry("Feature A", Confidence::Medium));
        evidence.entries.push(create_entry("Feature B", Confidence::Medium));

        assert!(!evidence.has_low_confidence_entries());
    }

    #[test]
    fn test_has_low_confidence_entries_true_when_has_low() {
        let mut evidence = VerificationEvidence::empty();
        evidence.entries.push(create_entry("Feature A", Confidence::High));
        evidence.entries.push(create_entry("Feature B", Confidence::Low));

        assert!(evidence.has_low_confidence_entries());
    }

    #[test]
    fn test_has_low_confidence_entries_true_when_all_low() {
        let mut evidence = VerificationEvidence::empty();
        evidence.entries.push(create_entry("Feature A", Confidence::Low));
        evidence.entries.push(create_entry("Feature B", Confidence::Low));

        assert!(evidence.has_low_confidence_entries());
    }

    #[test]
    fn test_low_confidence_entries_empty_when_none() {
        let mut evidence = VerificationEvidence::empty();
        evidence.entries.push(create_entry("Feature A", Confidence::High));
        evidence.entries.push(create_entry("Feature B", Confidence::Medium));

        let low_entries = evidence.low_confidence_entries();
        assert!(low_entries.is_empty());
    }

    #[test]
    fn test_low_confidence_entries_returns_correct_entries() {
        let mut evidence = VerificationEvidence::empty();
        evidence.entries.push(create_entry("High confidence", Confidence::High));
        evidence.entries.push(create_entry("Low confidence A", Confidence::Low));
        evidence.entries.push(create_entry("Medium confidence", Confidence::Medium));
        evidence.entries.push(create_entry("Low confidence B", Confidence::Low));

        let low_entries = evidence.low_confidence_entries();
        assert_eq!(low_entries.len(), 2);

        let descriptions: Vec<&str> = low_entries
            .iter()
            .map(|e| e.original_description.as_str())
            .collect();
        assert!(descriptions.contains(&"Low confidence A"));
        assert!(descriptions.contains(&"Low confidence B"));
    }

    #[test]
    fn test_confidence_display() {
        assert_eq!(format!("{}", Confidence::High), "high");
        assert_eq!(format!("{}", Confidence::Medium), "medium");
        assert_eq!(format!("{}", Confidence::Low), "low");
    }

    #[test]
    fn test_count_check_matches_when_counts_equal() {
        let check = CountCheck {
            claimed_text: "5 items".to_string(),
            claimed_count: Some(5),
            actual_count: Some(5),
            source_location: None,
        };
        assert!(check.matches());
    }

    #[test]
    fn test_count_check_not_matches_when_counts_differ() {
        let check = CountCheck {
            claimed_text: "8 templates".to_string(),
            claimed_count: Some(8),
            actual_count: Some(5),
            source_location: None,
        };
        assert!(!check.matches());
    }

    #[test]
    fn test_count_check_matches_when_actual_unknown() {
        let check = CountCheck {
            claimed_text: "10 widgets".to_string(),
            claimed_count: Some(10),
            actual_count: None,
            source_location: None,
        };
        assert!(check.matches(), "Unknown actual count should assume match");
    }

    #[test]
    fn test_count_check_matches_when_claimed_unknown() {
        let check = CountCheck {
            claimed_text: "several items".to_string(),
            claimed_count: None,
            actual_count: Some(3),
            source_location: None,
        };
        assert!(check.matches(), "Unknown claimed count should assume match");
    }

    #[test]
    fn test_count_check_matches_when_both_unknown() {
        let check = CountCheck {
            claimed_text: "some things".to_string(),
            claimed_count: None,
            actual_count: None,
            source_location: None,
        };
        assert!(check.matches(), "Both unknown should assume match");
    }

    #[test]
    fn test_count_check_serialization_includes_matches() {
        let check = CountCheck {
            claimed_text: "3 items".to_string(),
            claimed_count: Some(3),
            actual_count: Some(5),
            source_location: Some("test.rs".to_string()),
        };

        let json = serde_json::to_string(&check).expect("serialization should succeed");

        // matches should be false (3 != 5)
        assert!(
            json.contains(r#""matches":false"#),
            "JSON should include computed matches field"
        );
        assert!(json.contains(r#""claimed_text":"3 items""#));
    }

    #[test]
    fn test_count_check_serialization_matches_true() {
        let check = CountCheck {
            claimed_text: "5 items".to_string(),
            claimed_count: Some(5),
            actual_count: Some(5),
            source_location: None,
        };

        let json = serde_json::to_string(&check).expect("serialization should succeed");

        // matches should be true (5 == 5)
        assert!(
            json.contains(r#""matches":true"#),
            "JSON should include computed matches field"
        );
    }
}
