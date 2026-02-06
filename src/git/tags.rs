//! Tag enumeration and version detection.

use std::collections::HashMap;

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

fn is_stable_release_tag(name: &str) -> bool {
    let raw = name.strip_prefix('v').unwrap_or(name);
    let mut parts = raw.split('.');
    let major = parts.next();
    let minor = parts.next();
    let patch = parts.next();
    let extra = parts.next();

    extra.is_none()
        && major.is_some_and(|p| !p.is_empty() && p.chars().all(|c| c.is_ascii_digit()))
        && minor.is_some_and(|p| !p.is_empty() && p.chars().all(|c| c.is_ascii_digit()))
        && patch.is_some_and(|p| !p.is_empty() && p.chars().all(|c| c.is_ascii_digit()))
}

/// Get the latest semver tag reachable from HEAD.
///
/// Walks commits reachable from `HEAD` and returns the first commit that has
/// a strict stable release tag (`vX.Y.Z` or `X.Y.Z`) attached.
/// This avoids glob-based false positives from non-semver tags while still
/// respecting branch reachability.
pub fn get_latest_reachable_tag(repo: &Repository) -> Result<Option<TagInfo>, GitError> {
    let head_oid = match repo.head().ok().and_then(|head| head.target()) {
        Some(oid) => oid,
        None => return Ok(None),
    };

    let mut tags_by_commit: HashMap<git2::Oid, Vec<TagInfo>> = HashMap::new();
    for tag in get_all_tags(repo)?
        .into_iter()
        .filter(|tag| tag.version.is_some() && is_stable_release_tag(&tag.name))
    {
        tags_by_commit.entry(tag.oid).or_default().push(tag);
    }

    if tags_by_commit.is_empty() {
        debug!("No stable semver tags found in repository");
        return Ok(None);
    }

    let mut revwalk = repo.revwalk().map_err(GitError::RevwalkError)?;
    revwalk.push(head_oid).map_err(GitError::RevwalkError)?;
    revwalk
        .set_sorting(git2::Sort::TOPOLOGICAL | git2::Sort::TIME)
        .map_err(GitError::RevwalkError)?;

    for oid in revwalk {
        let oid = oid.map_err(GitError::RevwalkError)?;
        if let Some(candidates) = tags_by_commit.get(&oid) {
            let latest = candidates
                .iter()
                .max_by(|a, b| a.version.cmp(&b.version))
                .cloned();
            if let Some(tag) = latest {
                debug!(tag = %tag.name, "Found latest reachable stable semver tag");
                return Ok(Some(tag));
            }
        }
    }

    Ok(None)
}

/// Get the latest semver tag from the repository (highest version globally).
///
/// **Warning**: This finds the highest semver tag across ALL branches, not just
/// tags reachable from HEAD. For release automation, use [`get_latest_reachable_tag`]
/// instead to correctly handle multi-branch workflows.
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
            warn!("Skipping tag with OID {} - name is not valid UTF-8", oid);
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
    use std::path::{Path, PathBuf};

    use git2::{Oid, Signature};
    use serial_test::serial;

    use super::*;

    struct CwdGuard {
        original: PathBuf,
    }

    impl CwdGuard {
        fn set(path: &Path) -> Self {
            let original = std::env::current_dir().expect("failed to get current directory");
            std::env::set_current_dir(path).expect("failed to set current directory");
            Self { original }
        }
    }

    impl Drop for CwdGuard {
        fn drop(&mut self) {
            let _ = std::env::set_current_dir(&self.original);
        }
    }

    fn commit(repo: &Repository, repo_dir: &Path, message: &str) -> Oid {
        let file_path = repo_dir.join("test.txt");
        std::fs::write(&file_path, format!("{}\n{}", message, std::process::id()))
            .expect("failed to write test file");

        let mut index = repo.index().expect("failed to open index");
        index
            .add_path(Path::new("test.txt"))
            .expect("failed to add file");
        index.write().expect("failed to write index");

        let tree_id = index.write_tree().expect("failed to write tree");
        let tree = repo.find_tree(tree_id).expect("failed to find tree");
        let sig = Signature::now("Test User", "test@example.com").expect("failed to create sig");
        let parent = repo.head().ok().and_then(|h| h.peel_to_commit().ok());
        let parents: Vec<&git2::Commit> = parent.iter().collect();

        repo.commit(Some("HEAD"), &sig, &sig, message, &tree, &parents)
            .expect("failed to create commit")
    }

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

    #[test]
    #[serial]
    fn test_get_latest_reachable_tag_ignores_non_semver_tags() {
        let dir = tempfile::tempdir().expect("failed to create tempdir");
        let repo = Repository::init(dir.path()).expect("failed to init repo");
        let _cwd = CwdGuard::set(dir.path());

        let first = commit(&repo, dir.path(), "feat: first");
        repo.tag_lightweight(
            "v1.2.3",
            &repo.find_object(first, None).expect("failed to find first"),
            false,
        )
        .expect("failed to tag semver");

        let second = commit(&repo, dir.path(), "chore: second");
        repo.tag_lightweight(
            "v1foo.0.0",
            &repo
                .find_object(second, None)
                .expect("failed to find second"),
            false,
        )
        .expect("failed to tag invalid semver");

        let latest = get_latest_reachable_tag(&repo)
            .expect("failed to resolve latest reachable tag")
            .expect("expected a semver tag");

        assert_eq!(latest.name, "v1.2.3");
        assert_eq!(latest.version, Some(Version::new(1, 2, 3)));
    }

    #[test]
    #[serial]
    fn test_get_latest_reachable_tag_returns_none_when_only_non_semver_tags_exist() {
        let dir = tempfile::tempdir().expect("failed to create tempdir");
        let repo = Repository::init(dir.path()).expect("failed to init repo");
        let _cwd = CwdGuard::set(dir.path());

        let first = commit(&repo, dir.path(), "feat: first");
        repo.tag_lightweight(
            "nightly-2026-02-05",
            &repo.find_object(first, None).expect("failed to find first"),
            false,
        )
        .expect("failed to tag nightly");

        let latest = get_latest_reachable_tag(&repo).expect("failed to resolve latest tag");
        assert!(latest.is_none());
    }
}
