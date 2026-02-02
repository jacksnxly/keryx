//! Keep a Changelog formatting types and utilities.

use serde::{Deserialize, Deserializer, Serialize};

/// Changelog categories per Keep a Changelog spec.
///
/// Serializes to lowercase (e.g., `"added"`). Deserializes case-insensitively
/// so both `"Added"` (from changelog LLM) and `"added"` (from commit LLM) work.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(rename_all = "lowercase")]
pub enum ChangelogCategory {
    Added,
    Changed,
    Deprecated,
    Removed,
    Fixed,
    Security,
}

impl ChangelogCategory {
    /// Get the display name for the category.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Added => "Added",
            Self::Changed => "Changed",
            Self::Deprecated => "Deprecated",
            Self::Removed => "Removed",
            Self::Fixed => "Fixed",
            Self::Security => "Security",
        }
    }

    /// Get the order for sorting categories per Keep a Changelog convention.
    pub fn order(&self) -> u8 {
        match self {
            Self::Added => 0,
            Self::Changed => 1,
            Self::Deprecated => 2,
            Self::Removed => 3,
            Self::Fixed => 4,
            Self::Security => 5,
        }
    }
}

impl<'de> Deserialize<'de> for ChangelogCategory {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let s = String::deserialize(deserializer)?;
        s.parse::<ChangelogCategory>().map_err(serde::de::Error::custom)
    }
}

impl std::str::FromStr for ChangelogCategory {
    type Err = String;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s.to_lowercase().as_str() {
            "added" => Ok(Self::Added),
            "changed" => Ok(Self::Changed),
            "deprecated" => Ok(Self::Deprecated),
            "removed" => Ok(Self::Removed),
            "fixed" => Ok(Self::Fixed),
            "security" => Ok(Self::Security),
            _ => Err(format!("Unknown category: {}", s)),
        }
    }
}

/// A single changelog entry.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChangelogEntry {
    pub category: ChangelogCategory,
    pub description: String,
}

/// Output from Claude containing changelog entries.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ChangelogOutput {
    pub entries: Vec<ChangelogEntry>,
}

impl ChangelogOutput {
    /// Group entries by category, sorted in standard order.
    pub fn entries_by_category(&self) -> Vec<(ChangelogCategory, Vec<&ChangelogEntry>)> {
        let mut grouped: std::collections::BTreeMap<u8, (ChangelogCategory, Vec<&ChangelogEntry>)> =
            std::collections::BTreeMap::new();

        for entry in &self.entries {
            let order = entry.category.order();
            grouped
                .entry(order)
                .or_insert_with(|| (entry.category.clone(), Vec::new()))
                .1
                .push(entry);
        }

        grouped.into_values().collect()
    }

    /// Count entries by type for summary output.
    pub fn count_by_type(&self) -> Vec<(String, usize)> {
        let grouped = self.entries_by_category();
        grouped
            .into_iter()
            .map(|(cat, entries)| (cat.as_str().to_lowercase(), entries.len()))
            .filter(|(_, count)| *count > 0)
            .collect()
    }
}

/// Keep a Changelog header for new files.
pub const CHANGELOG_HEADER: &str = r#"# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

"#;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_category_order() {
        assert!(ChangelogCategory::Added.order() < ChangelogCategory::Fixed.order());
        assert!(ChangelogCategory::Security.order() > ChangelogCategory::Removed.order());
    }

    #[test]
    fn test_category_from_str() {
        assert_eq!(
            "Added".parse::<ChangelogCategory>().unwrap(),
            ChangelogCategory::Added
        );
        assert_eq!(
            "fixed".parse::<ChangelogCategory>().unwrap(),
            ChangelogCategory::Fixed
        );
    }

    #[test]
    fn test_entries_by_category() {
        let output = ChangelogOutput {
            entries: vec![
                ChangelogEntry {
                    category: ChangelogCategory::Fixed,
                    description: "Bug fix".to_string(),
                },
                ChangelogEntry {
                    category: ChangelogCategory::Added,
                    description: "New feature".to_string(),
                },
            ],
        };

        let grouped = output.entries_by_category();
        assert_eq!(grouped.len(), 2);
        assert_eq!(grouped[0].0, ChangelogCategory::Added); // Added comes first
        assert_eq!(grouped[1].0, ChangelogCategory::Fixed);
    }
}
