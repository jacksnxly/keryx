//! Tag enumeration and version detection.

use git2::Repository;
use semver::Version;
use tracing::{debug, warn};

use crate::error::GitError;

/// A git tag with optional semver version.
#[derive(Debug, Clone)]
pub struct TagInfo {
    pub name: String,
    pub oid: git2::Oid,
    pub version: Option<Version>,
}

/// Get the latest semver tag from the repository.
pub fn get_latest_tag(repo: &Repository) -> Result<Option<TagInfo>, GitError> {
    let tags = get_all_tags(repo)?;

    // Filter to only semver tags and find the latest
    let latest = tags
        .into_iter()
        .filter(|t| t.version.is_some())
        .max_by(|a, b| a.version.cmp(&b.version));

    Ok(latest)
}

/// Get all tags from the repository.
pub fn get_all_tags(repo: &Repository) -> Result<Vec<TagInfo>, GitError> {
    let mut tags = Vec::new();

    repo.tag_foreach(|oid, name_bytes| {
        if let Ok(name_str) = std::str::from_utf8(name_bytes) {
            // Remove refs/tags/ prefix
            let name = name_str
                .strip_prefix("refs/tags/")
                .unwrap_or(name_str)
                .to_string();

            let version = get_version_from_tag(&name);

            // Resolve tag to commit (handle annotated tags)
            let resolved_oid = match repo.find_tag(oid) {
                Ok(tag_obj) => tag_obj.target_id(),
                Err(e) => {
                    debug!(
                        tag = %name,
                        error = %e,
                        "Could not resolve annotated tag, using raw OID. \
                         This is normal for lightweight tags."
                    );
                    oid
                }
            };

            tags.push(TagInfo {
                name,
                oid: resolved_oid,
                version,
            });
        } else {
            warn!(
                "Skipping tag with OID {} - name is not valid UTF-8",
                oid
            );
        }
        true // Continue iteration
    })
    .map_err(GitError::RevwalkError)?;

    Ok(tags)
}

/// Extract semver version from a tag name.
/// Handles both "v1.2.3" and "1.2.3" formats.
pub fn get_version_from_tag(tag_name: &str) -> Option<Version> {
    let version_str = tag_name.strip_prefix('v').unwrap_or(tag_name);
    Version::parse(version_str).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_version_from_tag_with_v() {
        let v = get_version_from_tag("v1.2.3");
        assert_eq!(v, Some(Version::new(1, 2, 3)));
    }

    #[test]
    fn test_version_from_tag_without_v() {
        let v = get_version_from_tag("1.2.3");
        assert_eq!(v, Some(Version::new(1, 2, 3)));
    }

    #[test]
    fn test_version_from_tag_prerelease() {
        let v = get_version_from_tag("v1.0.0-beta.1");
        assert!(v.is_some());
        assert_eq!(v.unwrap().pre.as_str(), "beta.1");
    }

    #[test]
    fn test_version_from_tag_invalid() {
        let v = get_version_from_tag("release-candidate");
        assert_eq!(v, None);
    }
}
