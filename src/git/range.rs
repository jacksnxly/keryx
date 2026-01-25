//! Commit range resolution.

use git2::{Oid, Repository};
use tracing::warn;

use crate::error::GitError;

use super::tags::get_latest_tag;

/// Resolved commit range with start and end OIDs.
#[derive(Debug, Clone)]
pub struct CommitRange {
    pub from: Oid,
    pub to: Oid,
    pub from_ref: String,
    pub to_ref: String,
}

/// Resolve a commit range from user-provided references.
///
/// If `from` is None, uses the latest tag or root commit.
/// If `to` is None, uses HEAD.
pub fn resolve_range(
    repo: &Repository,
    from: Option<&str>,
    to: Option<&str>,
) -> Result<CommitRange, GitError> {
    let to_ref = to.unwrap_or("HEAD");
    let to_oid = resolve_reference(repo, to_ref)?;

    let (from_oid, from_ref) = if let Some(from_str) = from {
        (resolve_reference(repo, from_str)?, from_str.to_string())
    } else {
        // Try to find the latest tag
        if let Some(tag_info) = get_latest_tag(repo)? {
            (tag_info.oid, tag_info.name)
        } else {
            // No tags, use root commit
            let root = find_root_commit(repo)?;
            (root, "root".to_string())
        }
    };

    Ok(CommitRange {
        from: from_oid,
        to: to_oid,
        from_ref,
        to_ref: to_ref.to_string(),
    })
}

/// Resolve a reference (tag, branch, commit hash) to an OID.
fn resolve_reference(repo: &Repository, reference: &str) -> Result<Oid, GitError> {
    // Try as a direct OID first
    if let Ok(oid) = Oid::from_str(reference) {
        if repo.find_commit(oid).is_ok() {
            return Ok(oid);
        }
    }

    // Try as a reference (branch or tag)
    if let Ok(obj) = repo.revparse_single(reference) {
        return Ok(obj.peel_to_commit().map_err(GitError::ParseCommit)?.id());
    }

    Err(GitError::ReferenceNotFound(
        reference.to_string(),
        git2::Error::from_str("Reference not found"),
    ))
}

/// Find the root commit of the repository.
fn find_root_commit(repo: &Repository) -> Result<Oid, GitError> {
    let head = repo
        .head()
        .map_err(|e| GitError::ReferenceNotFound("HEAD".to_string(), e))?;

    let head_commit = head
        .peel_to_commit()
        .map_err(GitError::ParseCommit)?;

    let mut revwalk = repo.revwalk().map_err(GitError::RevwalkError)?;
    revwalk.push(head_commit.id()).map_err(GitError::RevwalkError)?;

    let mut root_oid = head_commit.id();

    for oid_result in revwalk {
        match oid_result {
            Ok(oid) => root_oid = oid,
            Err(e) => {
                warn!(
                    "Error during revwalk traversal: {}. Continuing with last valid commit.",
                    e
                );
            }
        }
    }

    Ok(root_oid)
}
