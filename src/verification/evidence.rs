//! Evidence types for changelog verification.

use serde::{Deserialize, Serialize};

use crate::changelog::ChangelogCategory;

/// Complete verification evidence for all changelog entries.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct VerificationEvidence {
    /// Evidence gathered for each entry.
    pub entries: Vec<EntryEvidence>,
    /// Project structure summary.
    pub project_structure: Option<String>,
    /// How the project structure was obtained: `"tree"`, `"ls"`, or `None` if unavailable.
    pub project_structure_source: Option<String>,
    /// Key files content (e.g., Cargo.toml, package.json).
    pub key_files: Vec<KeyFileContent>,
    /// Warnings encountered during evidence gathering.
    ///
    /// This tracks issues like failed file reads, command failures, or other
    /// problems that may have degraded the quality of evidence. Callers can
    /// check `warnings.is_empty()` to determine if evidence is complete.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub warnings: Vec<String>,
}

/// Evidence for a single changelog entry.
///
/// The confidence level is computed from the evidence data (keyword matches,
/// stub indicators, count checks, scan summary) rather than stored, ensuring
/// it's always consistent with the evidence.
#[derive(Debug, Clone, Deserialize)]
pub struct EntryEvidence {
    /// The original entry description.
    pub original_description: String,
    /// The category (Added, Changed, etc.).
    pub category: ChangelogCategory,
    /// Keywords extracted and their matches in the codebase.
    pub keyword_matches: Vec<KeywordMatch>,
    /// Numeric claims found and their verification.
    pub count_checks: Vec<CountCheck>,
    /// Stub/TODO indicators found.
    pub stub_indicators: Vec<StubIndicator>,
    /// Summary of search operations performed for this entry.
    #[serde(default)]
    pub scan_summary: ScanSummary,
}

impl EntryEvidence {
    /// Create new entry evidence.
    pub fn new(
        original_description: String,
        category: ChangelogCategory,
        keyword_matches: Vec<KeywordMatch>,
        count_checks: Vec<CountCheck>,
        stub_indicators: Vec<StubIndicator>,
        scan_summary: ScanSummary,
    ) -> Self {
        Self {
            original_description,
            category,
            keyword_matches,
            count_checks,
            stub_indicators,
            scan_summary,
        }
    }

    /// Calculate confidence based on evidence.
    ///
    /// Confidence is computed from a score starting at 50, with boosts for
    /// keyword matches and penalties for stub indicators and count mismatches.
    pub fn confidence(&self) -> Confidence {
        // Start with medium confidence
        let mut score: i32 = 50;

        // Boost for keyword matches
        for km in &self.keyword_matches {
            if let Some(count) = km.occurrence_count
                && count > 0
            {
                // Verified occurrences found - boost confidence
                score += 10;
                if km.appears_complete {
                    score += 10;
                }
            }
            // Some(0) = explicitly counted zero occurrences - no boost
            // None = counting failed - no boost (cannot verify)

            if km.files_found.len() > 2 {
                score += 5;
            }
        }

        // Penalty for stub indicators
        score -= (self.stub_indicators.len() as i32) * 15;

        // Penalty for count mismatches or unverifiable counts
        for check in &self.count_checks {
            match check.matches() {
                Some(true) => {} // Verified match - no penalty
                Some(false) => score -= 20, // Verified mismatch - significant penalty
                None => score -= 10, // Could not verify - smaller penalty (suspicious but not proven wrong)
            }
        }

        // Penalty for search failures - each failed search means we couldn't verify
        // that keyword, similar to an unverifiable count (-10 per failure)
        score -= (self.scan_summary.failed_searches as i32) * 10;

        // No keyword matches at all is suspicious
        if self.keyword_matches.is_empty() {
            score -= 30;
        }

        if score >= 70 {
            Confidence::High
        } else if score >= 40 {
            Confidence::Medium
        } else {
            Confidence::Low
        }
    }
}

impl Serialize for EntryEvidence {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        use serde::ser::SerializeStruct;

        let mut state = serializer.serialize_struct("EntryEvidence", 7)?;
        state.serialize_field("original_description", &self.original_description)?;
        state.serialize_field("category", &self.category)?;
        state.serialize_field("keyword_matches", &self.keyword_matches)?;
        state.serialize_field("count_checks", &self.count_checks)?;
        state.serialize_field("stub_indicators", &self.stub_indicators)?;
        state.serialize_field("scan_summary", &self.scan_summary)?;
        state.serialize_field("confidence", &self.confidence())?;
        state.end()
    }
}

/// A keyword match found in the codebase.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct KeywordMatch {
    /// The keyword searched for.
    pub keyword: String,
    /// Files where the keyword was found.
    pub files_found: Vec<String>,
    /// Number of occurrences: `Some(n)` = counted n occurrences, `None` = counting failed.
    /// This distinction matters for confidence scoring: `None` should not boost confidence,
    /// while `Some(0)` explicitly means zero occurrences were found.
    pub occurrence_count: Option<usize>,
    /// Sample lines showing context (first few matches).
    /// `Some(vec)` = samples fetched (possibly empty), `None` = sampling failed.
    pub sample_lines: Option<Vec<String>>,
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
    /// Returns whether the claimed count matches the actual count.
    ///
    /// - `Some(true)` - counts were verified and match
    /// - `Some(false)` - counts were verified and don't match
    /// - `None` - could not verify (either claimed or actual count is unknown)
    ///
    /// Previously this returned `true` when `actual_count` was `None`, which
    /// incorrectly marked unverifiable claims as "verified matching." Now
    /// callers must explicitly handle the "could not verify" case.
    pub fn matches(&self) -> Option<bool> {
        match (self.claimed_count, self.actual_count) {
            (Some(claimed), Some(actual)) => Some(claimed == actual),
            _ => None, // Could not verify - either claimed or actual is unknown
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
        // matches is now Option<bool>: null = could not verify, true/false = verified result
        state.serialize_field("matches", &self.matches())?;
        state.end()
    }
}

/// Type of stub indicator found in code.
///
/// Each variant corresponds to a pattern from `STUB_PATTERNS` in scanner.rs.
/// Serializes to lowercase strings (e.g., `"todo"`, `"fixme"`).
#[derive(Debug, Clone, Copy, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "lowercase")]
pub enum StubType {
    /// TODO comment marker.
    Todo,
    /// FIXME comment marker.
    Fixme,
    /// XXX comment marker.
    Xxx,
    /// HACK comment marker.
    Hack,
    /// Rust `unimplemented!()` macro.
    Unimplemented,
    /// Rust `todo!()` macro.
    TodoMacro,
    /// `panic!("not implemented")` pattern.
    PanicNotImplemented,
    /// `panic!("unimplemented")` pattern.
    PanicUnimplemented,
    /// `// stub` comment.
    Stub,
    /// `// placeholder` comment.
    Placeholder,
    /// Python `NotImplemented` constant.
    NotImplemented,
    /// Python `raise NotImplementedError` statement.
    RaiseNotImplementedError,
    /// Unknown stub pattern (fallback for unmatched patterns).
    Unknown,
}

impl std::fmt::Display for StubType {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            StubType::Todo => write!(f, "TODO"),
            StubType::Fixme => write!(f, "FIXME"),
            StubType::Xxx => write!(f, "XXX"),
            StubType::Hack => write!(f, "HACK"),
            StubType::Unimplemented => write!(f, "unimplemented!"),
            StubType::TodoMacro => write!(f, "todo!"),
            StubType::PanicNotImplemented => write!(f, "panic!(\"not implemented\")"),
            StubType::PanicUnimplemented => write!(f, "panic!(\"unimplemented\")"),
            StubType::Stub => write!(f, "// stub"),
            StubType::Placeholder => write!(f, "// placeholder"),
            StubType::NotImplemented => write!(f, "NotImplemented"),
            StubType::RaiseNotImplementedError => write!(f, "raise NotImplementedError"),
            StubType::Unknown => write!(f, "stub"),
        }
    }
}

/// Indicator that code may be incomplete.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StubIndicator {
    /// The file where the indicator was found.
    pub file: String,
    /// The line number.
    pub line: usize,
    /// The type of stub indicator.
    pub indicator: StubType,
    /// Context around the indicator.
    pub context: String,
}

/// Summary of search operations during entry analysis.
///
/// Tracks the outcomes of keyword searches to help assess evidence quality.
/// A high failure rate indicates that confidence scoring may be unreliable.
#[derive(Debug, Clone, Default, Serialize, Deserialize)]
pub struct ScanSummary {
    /// Total number of keywords extracted from the entry.
    pub total_keywords: usize,
    /// Number of keywords that were searched successfully (found or not found).
    pub successful_searches: usize,
    /// Number of keyword searches that failed due to errors.
    pub failed_searches: usize,
}

impl ScanSummary {
    /// Create a new scan summary.
    pub fn new() -> Self {
        Self::default()
    }

    /// Record a keyword extraction.
    pub fn add_keyword(&mut self) {
        self.total_keywords += 1;
    }

    /// Record a successful search (regardless of whether matches were found).
    pub fn add_success(&mut self) {
        self.successful_searches += 1;
    }

    /// Record a failed search.
    pub fn add_failure(&mut self) {
        self.failed_searches += 1;
    }

    /// Check if any searches failed.
    pub fn has_failures(&self) -> bool {
        self.failed_searches > 0
    }

    /// Calculate the failure rate as a fraction (0.0 to 1.0).
    ///
    /// Returns 0.0 if no keywords were searched.
    pub fn failure_rate(&self) -> f64 {
        let total_searched = self.successful_searches + self.failed_searches;
        if total_searched == 0 {
            0.0
        } else {
            self.failed_searches as f64 / total_searched as f64
        }
    }
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
            project_structure_source: None,
            key_files: Vec::new(),
            warnings: Vec::new(),
        }
    }

    /// Add a warning to the evidence.
    pub fn add_warning(&mut self, warning: impl Into<String>) {
        self.warnings.push(warning.into());
    }

    /// Check if evidence gathering was degraded (had warnings).
    pub fn is_degraded(&self) -> bool {
        !self.warnings.is_empty()
    }

    /// Check if any entries have low confidence.
    pub fn has_low_confidence_entries(&self) -> bool {
        self.entries.iter().any(|e| e.confidence() == Confidence::Low)
    }

    /// Get entries with low confidence.
    pub fn low_confidence_entries(&self) -> Vec<&EntryEvidence> {
        self.entries
            .iter()
            .filter(|e| e.confidence() == Confidence::Low)
            .collect()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Create test entry that computes to high confidence (many keyword matches).
    fn create_high_confidence_entry(description: &str) -> EntryEvidence {
        EntryEvidence::new(
            description.to_string(),
            ChangelogCategory::Added,
            vec![
                KeywordMatch {
                    keyword: "test".to_string(),
                    files_found: vec!["a.rs".to_string(), "b.rs".to_string(), "c.rs".to_string()],
                    occurrence_count: Some(10),
                    sample_lines: Some(vec![]),
                    appears_complete: true,
                },
            ],
            vec![],
            vec![],
            ScanSummary::default(),
        )
    }

    /// Create test entry that computes to medium confidence (some matches).
    fn create_medium_confidence_entry(description: &str) -> EntryEvidence {
        EntryEvidence::new(
            description.to_string(),
            ChangelogCategory::Added,
            vec![
                KeywordMatch {
                    keyword: "test".to_string(),
                    files_found: vec!["a.rs".to_string()],
                    occurrence_count: Some(1),
                    sample_lines: Some(vec![]),
                    appears_complete: false,
                },
            ],
            vec![],
            vec![],
            ScanSummary::default(),
        )
    }

    /// Create test entry that computes to low confidence (no matches, stubs).
    fn create_low_confidence_entry(description: &str) -> EntryEvidence {
        EntryEvidence::new(
            description.to_string(),
            ChangelogCategory::Added,
            vec![],  // No keyword matches
            vec![],
            vec![
                StubIndicator {
                    file: "a.rs".to_string(),
                    line: 10,
                    indicator: StubType::Todo,
                    context: "// TODO".to_string(),
                },
            ],
            ScanSummary::default(),
        )
    }

    #[test]
    fn test_verification_evidence_empty() {
        let evidence = VerificationEvidence::empty();

        assert!(evidence.entries.is_empty());
        assert!(evidence.project_structure.is_none());
        assert!(evidence.project_structure_source.is_none());
        assert!(evidence.key_files.is_empty());
        assert!(evidence.warnings.is_empty());
        assert!(!evidence.is_degraded());
    }

    #[test]
    fn test_verification_evidence_add_warning() {
        let mut evidence = VerificationEvidence::empty();
        assert!(!evidence.is_degraded());

        evidence.add_warning("First warning");
        assert!(evidence.is_degraded());
        assert_eq!(evidence.warnings.len(), 1);
        assert_eq!(evidence.warnings[0], "First warning");

        evidence.add_warning(String::from("Second warning"));
        assert_eq!(evidence.warnings.len(), 2);
    }

    #[test]
    fn test_verification_evidence_warnings_serialization() {
        let mut evidence = VerificationEvidence::empty();
        evidence.add_warning("Test warning");

        let json = serde_json::to_string(&evidence).expect("serialization should succeed");
        assert!(
            json.contains(r#""warnings":["Test warning"]"#),
            "JSON should include warnings: {}",
            json
        );
    }

    #[test]
    fn test_verification_evidence_empty_warnings_skipped_in_json() {
        let evidence = VerificationEvidence::empty();

        let json = serde_json::to_string(&evidence).expect("serialization should succeed");
        // Empty warnings should be skipped due to skip_serializing_if
        assert!(
            !json.contains("warnings"),
            "Empty warnings should be skipped in JSON: {}",
            json
        );
    }

    #[test]
    fn test_has_low_confidence_entries_false_when_empty() {
        let evidence = VerificationEvidence::empty();
        assert!(!evidence.has_low_confidence_entries());
    }

    #[test]
    fn test_has_low_confidence_entries_false_when_all_high() {
        let mut evidence = VerificationEvidence::empty();
        evidence.entries.push(create_high_confidence_entry("Feature A"));
        evidence.entries.push(create_high_confidence_entry("Feature B"));

        assert!(!evidence.has_low_confidence_entries());
    }

    #[test]
    fn test_has_low_confidence_entries_false_when_all_medium() {
        let mut evidence = VerificationEvidence::empty();
        evidence.entries.push(create_medium_confidence_entry("Feature A"));
        evidence.entries.push(create_medium_confidence_entry("Feature B"));

        assert!(!evidence.has_low_confidence_entries());
    }

    #[test]
    fn test_has_low_confidence_entries_true_when_has_low() {
        let mut evidence = VerificationEvidence::empty();
        evidence.entries.push(create_high_confidence_entry("Feature A"));
        evidence.entries.push(create_low_confidence_entry("Feature B"));

        assert!(evidence.has_low_confidence_entries());
    }

    #[test]
    fn test_has_low_confidence_entries_true_when_all_low() {
        let mut evidence = VerificationEvidence::empty();
        evidence.entries.push(create_low_confidence_entry("Feature A"));
        evidence.entries.push(create_low_confidence_entry("Feature B"));

        assert!(evidence.has_low_confidence_entries());
    }

    #[test]
    fn test_low_confidence_entries_empty_when_none() {
        let mut evidence = VerificationEvidence::empty();
        evidence.entries.push(create_high_confidence_entry("Feature A"));
        evidence.entries.push(create_medium_confidence_entry("Feature B"));

        let low_entries = evidence.low_confidence_entries();
        assert!(low_entries.is_empty());
    }

    #[test]
    fn test_low_confidence_entries_returns_correct_entries() {
        let mut evidence = VerificationEvidence::empty();
        evidence.entries.push(create_high_confidence_entry("High confidence"));
        evidence.entries.push(create_low_confidence_entry("Low confidence A"));
        evidence.entries.push(create_medium_confidence_entry("Medium confidence"));
        evidence.entries.push(create_low_confidence_entry("Low confidence B"));

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
        assert_eq!(check.matches(), Some(true), "Equal counts should return Some(true)");
    }

    #[test]
    fn test_count_check_not_matches_when_counts_differ() {
        let check = CountCheck {
            claimed_text: "8 templates".to_string(),
            claimed_count: Some(8),
            actual_count: Some(5),
            source_location: None,
        };
        assert_eq!(check.matches(), Some(false), "Different counts should return Some(false)");
    }

    #[test]
    fn test_count_check_returns_none_when_actual_unknown() {
        let check = CountCheck {
            claimed_text: "10 widgets".to_string(),
            claimed_count: Some(10),
            actual_count: None,
            source_location: None,
        };
        assert_eq!(check.matches(), None, "Unknown actual count should return None (could not verify)");
    }

    #[test]
    fn test_count_check_returns_none_when_claimed_unknown() {
        let check = CountCheck {
            claimed_text: "several items".to_string(),
            claimed_count: None,
            actual_count: Some(3),
            source_location: None,
        };
        assert_eq!(check.matches(), None, "Unknown claimed count should return None (could not verify)");
    }

    #[test]
    fn test_count_check_returns_none_when_both_unknown() {
        let check = CountCheck {
            claimed_text: "some things".to_string(),
            claimed_count: None,
            actual_count: None,
            source_location: None,
        };
        assert_eq!(check.matches(), None, "Both unknown should return None (could not verify)");
    }

    #[test]
    fn test_count_check_serialization_matches_false() {
        let check = CountCheck {
            claimed_text: "3 items".to_string(),
            claimed_count: Some(3),
            actual_count: Some(5),
            source_location: Some("test.rs".to_string()),
        };

        let json = serde_json::to_string(&check).expect("serialization should succeed");

        // matches should be false (3 != 5) - verified mismatch
        assert!(
            json.contains(r#""matches":false"#),
            "JSON should include computed matches field as false: {}", json
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

        // matches should be true (5 == 5) - verified match
        assert!(
            json.contains(r#""matches":true"#),
            "JSON should include computed matches field as true: {}", json
        );
    }

    #[test]
    fn test_count_check_serialization_matches_null_when_unverifiable() {
        let check = CountCheck {
            claimed_text: "10 widgets".to_string(),
            claimed_count: Some(10),
            actual_count: None, // Verification failed
            source_location: None,
        };

        let json = serde_json::to_string(&check).expect("serialization should succeed");

        // matches should be null (could not verify)
        assert!(
            json.contains(r#""matches":null"#),
            "JSON should include matches as null when unverifiable: {}", json
        );
    }

    #[test]
    fn test_entry_evidence_serialization_includes_computed_confidence() {
        // Create entry with high confidence (many keyword matches, appears complete)
        let entry = create_high_confidence_entry("Test feature");

        let json = serde_json::to_string(&entry).expect("serialization should succeed");

        // Confidence should be included in serialized output
        assert!(
            json.contains(r#""confidence":"high""#),
            "JSON should include computed confidence field: {}",
            json
        );
        assert!(
            json.contains(r#""original_description":"Test feature""#),
            "JSON should include original_description"
        );
    }

    #[test]
    fn test_entry_evidence_serialization_includes_low_confidence() {
        // Create entry with low confidence (no keyword matches, has stubs)
        let entry = create_low_confidence_entry("Incomplete feature");

        let json = serde_json::to_string(&entry).expect("serialization should succeed");

        // Low confidence should be serialized
        assert!(
            json.contains(r#""confidence":"low""#),
            "JSON should include computed low confidence field: {}",
            json
        );
    }

    #[test]
    fn test_entry_evidence_confidence_computed_consistently() {
        // Create entry and verify confidence is computed each time (not cached incorrectly)
        let entry = create_medium_confidence_entry("Medium feature");

        // Call confidence() multiple times
        let conf1 = entry.confidence();
        let conf2 = entry.confidence();
        let conf3 = entry.confidence();

        assert_eq!(conf1, conf2);
        assert_eq!(conf2, conf3);
        assert_eq!(conf1, Confidence::Medium);
    }

    #[test]
    fn test_occurrence_count_none_vs_zero_serialization() {
        // None = counting failed
        let km_none = KeywordMatch {
            keyword: "feature".to_string(),
            files_found: vec!["a.rs".to_string()],
            occurrence_count: None,
            sample_lines: Some(vec![]),
            appears_complete: false,
        };

        // Some(0) = counted zero occurrences
        let km_zero = KeywordMatch {
            keyword: "feature".to_string(),
            files_found: vec!["a.rs".to_string()],
            occurrence_count: Some(0),
            sample_lines: Some(vec![]),
            appears_complete: false,
        };

        let json_none = serde_json::to_string(&km_none).expect("serialization should succeed");
        let json_zero = serde_json::to_string(&km_zero).expect("serialization should succeed");

        // JSON should distinguish the two cases
        assert!(
            json_none.contains(r#""occurrence_count":null"#),
            "None should serialize as null: {}",
            json_none
        );
        assert!(
            json_zero.contains(r#""occurrence_count":0"#),
            "Some(0) should serialize as 0: {}",
            json_zero
        );
    }

    #[test]
    fn test_confidence_none_occurrence_count_no_boost() {
        // Entry with None occurrence_count (counting failed) should NOT get the +10 boost
        let entry_with_none = EntryEvidence::new(
            "Feature with failed count".to_string(),
            ChangelogCategory::Added,
            vec![
                KeywordMatch {
                    keyword: "test".to_string(),
                    files_found: vec!["a.rs".to_string(), "b.rs".to_string(), "c.rs".to_string()],
                    occurrence_count: None, // Counting failed
                    sample_lines: Some(vec![]),
                    appears_complete: false,
                },
            ],
            vec![],
            vec![],
            ScanSummary::default(),
        );

        // Entry with Some(5) should get the +10 boost
        let entry_with_count = EntryEvidence::new(
            "Feature with count".to_string(),
            ChangelogCategory::Added,
            vec![
                KeywordMatch {
                    keyword: "test".to_string(),
                    files_found: vec!["a.rs".to_string(), "b.rs".to_string(), "c.rs".to_string()],
                    occurrence_count: Some(5), // Counted 5 occurrences
                    sample_lines: Some(vec![]),
                    appears_complete: false,
                },
            ],
            vec![],
            vec![],
            ScanSummary::default(),
        );

        // Both start at 50, both get +5 for >2 files
        // entry_with_none: 50 + 5 = 55 (Medium)
        // entry_with_count: 50 + 10 + 5 = 65 (Medium, but higher)
        // The difference is the +10 boost for occurrence_count > 0

        let conf_none = entry_with_none.confidence();
        let conf_count = entry_with_count.confidence();

        // Both should be Medium in this case, but entry_with_count has higher score
        assert_eq!(conf_none, Confidence::Medium, "None count should be Medium (55)");
        assert_eq!(conf_count, Confidence::Medium, "Some(5) count should be Medium (65)");
    }

    #[test]
    fn test_confidence_some_zero_no_boost() {
        // Entry with Some(0) (explicitly counted zero) should NOT get the +10 boost
        let entry = EntryEvidence::new(
            "Feature with zero count".to_string(),
            ChangelogCategory::Added,
            vec![
                KeywordMatch {
                    keyword: "test".to_string(),
                    files_found: vec!["a.rs".to_string()],
                    occurrence_count: Some(0), // Counted zero occurrences
                    sample_lines: Some(vec![]),
                    appears_complete: true,
                },
            ],
            vec![],
            vec![],
            ScanSummary::default(),
        );

        // Score: 50 (base) + 0 (no boost for count=0) = 50
        assert_eq!(entry.confidence(), Confidence::Medium);
    }

    // Tests for ScanSummary (KRX-085)

    #[test]
    fn test_scan_summary_default() {
        let summary = ScanSummary::default();
        assert_eq!(summary.total_keywords, 0);
        assert_eq!(summary.successful_searches, 0);
        assert_eq!(summary.failed_searches, 0);
        assert!(!summary.has_failures());
        assert_eq!(summary.failure_rate(), 0.0);
    }

    #[test]
    fn test_scan_summary_tracking() {
        let mut summary = ScanSummary::new();
        summary.add_keyword();
        summary.add_keyword();
        summary.add_keyword();
        summary.add_success();
        summary.add_success();
        summary.add_failure();

        assert_eq!(summary.total_keywords, 3);
        assert_eq!(summary.successful_searches, 2);
        assert_eq!(summary.failed_searches, 1);
        assert!(summary.has_failures());
        // 1 failure out of 3 searches = ~0.333
        assert!((summary.failure_rate() - 0.333).abs() < 0.01);
    }

    #[test]
    fn test_scan_summary_failure_rate_no_searches() {
        let summary = ScanSummary::new();
        // No searches = 0.0 failure rate (not NaN)
        assert_eq!(summary.failure_rate(), 0.0);
    }

    #[test]
    fn test_scan_summary_failure_rate_all_success() {
        let mut summary = ScanSummary::new();
        summary.add_success();
        summary.add_success();
        summary.add_success();

        assert_eq!(summary.failure_rate(), 0.0);
        assert!(!summary.has_failures());
    }

    #[test]
    fn test_scan_summary_failure_rate_all_failures() {
        let mut summary = ScanSummary::new();
        summary.add_failure();
        summary.add_failure();

        assert_eq!(summary.failure_rate(), 1.0);
        assert!(summary.has_failures());
    }

    #[test]
    fn test_confidence_penalty_for_search_failures() {
        // Entry with no failures
        let entry_no_failures = EntryEvidence::new(
            "Test feature".to_string(),
            ChangelogCategory::Added,
            vec![
                KeywordMatch {
                    keyword: "test".to_string(),
                    files_found: vec!["a.rs".to_string(), "b.rs".to_string(), "c.rs".to_string()],
                    occurrence_count: Some(10),
                    sample_lines: Some(vec![]),
                    appears_complete: true,
                },
            ],
            vec![],
            vec![],
            ScanSummary::default(),
        );

        // Same entry but with 3 search failures
        let mut summary_with_failures = ScanSummary::new();
        summary_with_failures.add_keyword();
        summary_with_failures.add_keyword();
        summary_with_failures.add_keyword();
        summary_with_failures.add_keyword();
        summary_with_failures.add_success(); // 1 success (the match above)
        summary_with_failures.add_failure();
        summary_with_failures.add_failure();
        summary_with_failures.add_failure();

        let entry_with_failures = EntryEvidence::new(
            "Test feature".to_string(),
            ChangelogCategory::Added,
            vec![
                KeywordMatch {
                    keyword: "test".to_string(),
                    files_found: vec!["a.rs".to_string(), "b.rs".to_string(), "c.rs".to_string()],
                    occurrence_count: Some(10),
                    sample_lines: Some(vec![]),
                    appears_complete: true,
                },
            ],
            vec![],
            vec![],
            summary_with_failures,
        );

        // entry_no_failures: 50 + 10 + 10 + 5 = 75 (High)
        // entry_with_failures: 50 + 10 + 10 + 5 - 30 = 45 (Medium, due to -10 * 3 failures)
        assert_eq!(entry_no_failures.confidence(), Confidence::High);
        assert_eq!(entry_with_failures.confidence(), Confidence::Medium);
    }

    #[test]
    fn test_confidence_penalty_many_failures_drops_to_low() {
        // Entry with many search failures should drop to low confidence
        let mut summary = ScanSummary::new();
        for _ in 0..5 {
            summary.add_keyword();
            summary.add_failure();
        }

        let entry = EntryEvidence::new(
            "Test feature".to_string(),
            ChangelogCategory::Added,
            vec![],  // No keyword matches (all failed)
            vec![],
            vec![],
            summary,
        );

        // Score: 50 - 30 (no matches) - 50 (5 failures * -10) = -30 (Low)
        assert_eq!(entry.confidence(), Confidence::Low);
    }

    #[test]
    fn test_scan_summary_serialization() {
        let mut summary = ScanSummary::new();
        summary.add_keyword();
        summary.add_success();

        let json = serde_json::to_string(&summary).expect("serialization should succeed");
        assert!(json.contains("\"total_keywords\":1"));
        assert!(json.contains("\"successful_searches\":1"));
        assert!(json.contains("\"failed_searches\":0"));
    }

    #[test]
    fn test_entry_evidence_serialization_includes_scan_summary() {
        let mut summary = ScanSummary::new();
        summary.add_keyword();
        summary.add_failure();

        let entry = EntryEvidence::new(
            "Test feature".to_string(),
            ChangelogCategory::Added,
            vec![],
            vec![],
            vec![],
            summary,
        );

        let json = serde_json::to_string(&entry).expect("serialization should succeed");
        assert!(
            json.contains("\"scan_summary\""),
            "JSON should include scan_summary field: {}",
            json
        );
        assert!(
            json.contains("\"failed_searches\":1"),
            "scan_summary should include failed_searches: {}",
            json
        );
    }

    // Tests for StubType enum (KRX-087)

    #[test]
    fn test_stub_type_serialization() {
        assert_eq!(
            serde_json::to_string(&StubType::Todo).unwrap(),
            "\"todo\""
        );
        assert_eq!(
            serde_json::to_string(&StubType::Fixme).unwrap(),
            "\"fixme\""
        );
        assert_eq!(
            serde_json::to_string(&StubType::Unimplemented).unwrap(),
            "\"unimplemented\""
        );
        assert_eq!(
            serde_json::to_string(&StubType::TodoMacro).unwrap(),
            "\"todomacro\""
        );
        assert_eq!(
            serde_json::to_string(&StubType::Unknown).unwrap(),
            "\"unknown\""
        );
    }

    #[test]
    fn test_stub_type_display() {
        assert_eq!(format!("{}", StubType::Todo), "TODO");
        assert_eq!(format!("{}", StubType::Unimplemented), "unimplemented!");
        assert_eq!(format!("{}", StubType::Unknown), "stub");
    }

    #[test]
    fn test_stub_indicator_serialization_uses_stub_type() {
        let indicator = StubIndicator {
            file: "test.rs".to_string(),
            line: 42,
            indicator: StubType::Todo,
            context: "// TODO: implement this".to_string(),
        };

        let json = serde_json::to_string(&indicator).expect("serialization should succeed");
        assert!(
            json.contains("\"indicator\":\"todo\""),
            "StubIndicator should serialize indicator as lowercase: {}",
            json
        );
    }
}
