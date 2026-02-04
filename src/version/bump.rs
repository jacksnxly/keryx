//! Semver calculation from commits.

use semver::Version;

use crate::git::{CommitType, ParsedCommit};

/// Type of version bump.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum BumpType {
    Patch,
    Minor,
    Major,
}

/// Apply a bump type to a base version to produce the next version.
///
/// If `base` is `None`, starts from `0.0.0`.
pub fn apply_bump_to_version(base: Option<&Version>, bump: BumpType) -> Version {
    let base = base.cloned().unwrap_or_else(|| Version::new(0, 0, 0));

    match bump {
        BumpType::Major => Version::new(base.major + 1, 0, 0),
        BumpType::Minor => Version::new(base.major, base.minor + 1, 0),
        BumpType::Patch => Version::new(base.major, base.minor, base.patch + 1),
    }
}

/// Calculate the next version based on commits.
///
/// Per spec:
/// - Breaking changes = major bump
/// - feat: commits = minor bump
/// - fix: commits = patch bump
pub fn calculate_next_version(base_version: Option<&Version>, commits: &[ParsedCommit]) -> Version {
    let bump_type = determine_bump_type(commits);
    apply_bump_to_version(base_version, bump_type)
}

/// Determine the bump type from a list of commits.
pub fn determine_bump_type(commits: &[ParsedCommit]) -> BumpType {
    let mut highest_bump = BumpType::Patch;

    for commit in commits {
        // Breaking changes always trigger major bump
        if commit.breaking {
            return BumpType::Major;
        }

        // Determine bump from commit type
        if let Some(ref commit_type) = commit.commit_type {
            let bump = match commit_type {
                CommitType::Feat => BumpType::Minor,
                CommitType::Fix => BumpType::Patch,
                CommitType::Perf => BumpType::Patch,
                // All other types don't trigger bumps by themselves
                _ => BumpType::Patch,
            };

            if bump > highest_bump {
                highest_bump = bump;
            }
        }
    }

    highest_bump
}

#[cfg(test)]
mod tests {
    use super::*;
    use chrono::Utc;

    fn make_commit(commit_type: Option<CommitType>, breaking: bool) -> ParsedCommit {
        ParsedCommit {
            hash: "abc123".to_string(),
            message: "test commit".to_string(),
            commit_type,
            scope: None,
            breaking,
            timestamp: Utc::now(),
        }
    }

    #[test]
    fn test_patch_bump_from_fix() {
        let commits = vec![make_commit(Some(CommitType::Fix), false)];
        let base = Version::new(1, 2, 3);
        let next = calculate_next_version(Some(&base), &commits);
        assert_eq!(next, Version::new(1, 2, 4));
    }

    #[test]
    fn test_minor_bump_from_feat() {
        let commits = vec![make_commit(Some(CommitType::Feat), false)];
        let base = Version::new(1, 2, 3);
        let next = calculate_next_version(Some(&base), &commits);
        assert_eq!(next, Version::new(1, 3, 0));
    }

    #[test]
    fn test_major_bump_from_breaking() {
        let commits = vec![make_commit(Some(CommitType::Feat), true)];
        let base = Version::new(1, 2, 3);
        let next = calculate_next_version(Some(&base), &commits);
        assert_eq!(next, Version::new(2, 0, 0));
    }

    #[test]
    fn test_highest_bump_wins() {
        let commits = vec![
            make_commit(Some(CommitType::Fix), false),
            make_commit(Some(CommitType::Feat), false),
            make_commit(Some(CommitType::Fix), false),
        ];
        let base = Version::new(1, 2, 3);
        let next = calculate_next_version(Some(&base), &commits);
        assert_eq!(next, Version::new(1, 3, 0)); // feat wins over fix
    }

    #[test]
    fn test_no_base_version() {
        let commits = vec![make_commit(Some(CommitType::Feat), false)];
        let next = calculate_next_version(None, &commits);
        assert_eq!(next, Version::new(0, 1, 0));
    }

    #[test]
    fn test_empty_commits() {
        let commits: Vec<ParsedCommit> = vec![];
        let base = Version::new(1, 2, 3);
        let next = calculate_next_version(Some(&base), &commits);
        assert_eq!(next, Version::new(1, 2, 4)); // Default to patch
    }

    #[test]
    fn test_apply_bump_major() {
        let base = Version::new(1, 2, 3);
        assert_eq!(
            apply_bump_to_version(Some(&base), BumpType::Major),
            Version::new(2, 0, 0)
        );
    }

    #[test]
    fn test_apply_bump_minor() {
        let base = Version::new(1, 2, 3);
        assert_eq!(
            apply_bump_to_version(Some(&base), BumpType::Minor),
            Version::new(1, 3, 0)
        );
    }

    #[test]
    fn test_apply_bump_patch() {
        let base = Version::new(1, 2, 3);
        assert_eq!(
            apply_bump_to_version(Some(&base), BumpType::Patch),
            Version::new(1, 2, 4)
        );
    }

    #[test]
    fn test_apply_bump_no_base() {
        assert_eq!(
            apply_bump_to_version(None, BumpType::Minor),
            Version::new(0, 1, 0)
        );
    }
}
