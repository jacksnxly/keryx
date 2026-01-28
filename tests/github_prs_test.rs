//! Integration tests for GitHub PR fetching with mocked octocrab.

mod common;

use chrono::{TimeZone, Utc};
use keryx::error::GitHubError;
use keryx::github::fetch_merged_prs_with_client;
use octocrab::Octocrab;
use serde_json::{json, Map, Value};
use wiremock::matchers::{method, path, query_param};
use wiremock::{Mock, MockServer, ResponseTemplate};

/// Maximum PR body length (matches production code).
const MAX_BODY_LENGTH: usize = 10 * 1024;

/// Helper to create an octocrab client pointing to a mock server.
async fn mock_client(server: &MockServer) -> Octocrab {
    Octocrab::builder()
        .base_uri(server.uri())
        .expect("Failed to set base URI")
        .build()
        .expect("Failed to build octocrab")
}

/// Create a mock user object with all fields GitHub API returns.
fn mock_user(login: &str, id: u64) -> Value {
    let mut user = Map::new();
    user.insert("login".into(), json!(login));
    user.insert("id".into(), json!(id));
    user.insert("node_id".into(), json!(format!("MDQ6VXNlcnt{}", id)));
    user.insert("avatar_url".into(), json!(format!("https://avatars.githubusercontent.com/u/{}?v=4", id)));
    user.insert("gravatar_id".into(), json!(""));
    user.insert("url".into(), json!(format!("https://api.github.com/users/{}", login)));
    user.insert("html_url".into(), json!(format!("https://github.com/{}", login)));
    user.insert("followers_url".into(), json!(format!("https://api.github.com/users/{}/followers", login)));
    user.insert("following_url".into(), json!(format!("https://api.github.com/users/{}/following{{/other_user}}", login)));
    user.insert("gists_url".into(), json!(format!("https://api.github.com/users/{}/gists{{/gist_id}}", login)));
    user.insert("starred_url".into(), json!(format!("https://api.github.com/users/{}/starred{{/owner}}{{/repo}}", login)));
    user.insert("subscriptions_url".into(), json!(format!("https://api.github.com/users/{}/subscriptions", login)));
    user.insert("organizations_url".into(), json!(format!("https://api.github.com/users/{}/orgs", login)));
    user.insert("repos_url".into(), json!(format!("https://api.github.com/users/{}/repos", login)));
    user.insert("events_url".into(), json!(format!("https://api.github.com/users/{}/events{{/privacy}}", login)));
    user.insert("received_events_url".into(), json!(format!("https://api.github.com/users/{}/received_events", login)));
    user.insert("type".into(), json!("User"));
    user.insert("site_admin".into(), json!(false));
    Value::Object(user)
}

/// Create a mock repository object with all required fields.
fn mock_repo() -> Value {
    let mut repo = Map::new();
    repo.insert("id".into(), json!(1));
    repo.insert("node_id".into(), json!("MDEwOlJlcG9zaXRvcnkx"));
    repo.insert("name".into(), json!("repo"));
    repo.insert("full_name".into(), json!("owner/repo"));
    repo.insert("owner".into(), mock_user("owner", 1));
    repo.insert("private".into(), json!(false));
    repo.insert("html_url".into(), json!("https://github.com/owner/repo"));
    repo.insert("description".into(), json!("Test repository"));
    repo.insert("fork".into(), json!(false));
    repo.insert("url".into(), json!("https://api.github.com/repos/owner/repo"));
    repo.insert("forks_url".into(), json!("https://api.github.com/repos/owner/repo/forks"));
    repo.insert("keys_url".into(), json!("https://api.github.com/repos/owner/repo/keys{/key_id}"));
    repo.insert("collaborators_url".into(), json!("https://api.github.com/repos/owner/repo/collaborators{/collaborator}"));
    repo.insert("teams_url".into(), json!("https://api.github.com/repos/owner/repo/teams"));
    repo.insert("hooks_url".into(), json!("https://api.github.com/repos/owner/repo/hooks"));
    repo.insert("issue_events_url".into(), json!("https://api.github.com/repos/owner/repo/issues/events{/number}"));
    repo.insert("events_url".into(), json!("https://api.github.com/repos/owner/repo/events"));
    repo.insert("assignees_url".into(), json!("https://api.github.com/repos/owner/repo/assignees{/user}"));
    repo.insert("branches_url".into(), json!("https://api.github.com/repos/owner/repo/branches{/branch}"));
    repo.insert("tags_url".into(), json!("https://api.github.com/repos/owner/repo/tags"));
    repo.insert("blobs_url".into(), json!("https://api.github.com/repos/owner/repo/git/blobs{/sha}"));
    repo.insert("git_tags_url".into(), json!("https://api.github.com/repos/owner/repo/git/tags{/sha}"));
    repo.insert("git_refs_url".into(), json!("https://api.github.com/repos/owner/repo/git/refs{/sha}"));
    repo.insert("trees_url".into(), json!("https://api.github.com/repos/owner/repo/git/trees{/sha}"));
    repo.insert("statuses_url".into(), json!("https://api.github.com/repos/owner/repo/statuses/{sha}"));
    repo.insert("languages_url".into(), json!("https://api.github.com/repos/owner/repo/languages"));
    repo.insert("stargazers_url".into(), json!("https://api.github.com/repos/owner/repo/stargazers"));
    repo.insert("contributors_url".into(), json!("https://api.github.com/repos/owner/repo/contributors"));
    repo.insert("subscribers_url".into(), json!("https://api.github.com/repos/owner/repo/subscribers"));
    repo.insert("subscription_url".into(), json!("https://api.github.com/repos/owner/repo/subscription"));
    repo.insert("commits_url".into(), json!("https://api.github.com/repos/owner/repo/commits{/sha}"));
    repo.insert("git_commits_url".into(), json!("https://api.github.com/repos/owner/repo/git/commits{/sha}"));
    repo.insert("comments_url".into(), json!("https://api.github.com/repos/owner/repo/comments{/number}"));
    repo.insert("issue_comment_url".into(), json!("https://api.github.com/repos/owner/repo/issues/comments{/number}"));
    repo.insert("contents_url".into(), json!("https://api.github.com/repos/owner/repo/contents/{+path}"));
    repo.insert("compare_url".into(), json!("https://api.github.com/repos/owner/repo/compare/{base}...{head}"));
    repo.insert("merges_url".into(), json!("https://api.github.com/repos/owner/repo/merges"));
    repo.insert("archive_url".into(), json!("https://api.github.com/repos/owner/repo/{archive_format}{/ref}"));
    repo.insert("downloads_url".into(), json!("https://api.github.com/repos/owner/repo/downloads"));
    repo.insert("issues_url".into(), json!("https://api.github.com/repos/owner/repo/issues{/number}"));
    repo.insert("pulls_url".into(), json!("https://api.github.com/repos/owner/repo/pulls{/number}"));
    repo.insert("milestones_url".into(), json!("https://api.github.com/repos/owner/repo/milestones{/number}"));
    repo.insert("notifications_url".into(), json!("https://api.github.com/repos/owner/repo/notifications{?since,all,participating}"));
    repo.insert("labels_url".into(), json!("https://api.github.com/repos/owner/repo/labels{/name}"));
    repo.insert("releases_url".into(), json!("https://api.github.com/repos/owner/repo/releases{/id}"));
    repo.insert("deployments_url".into(), json!("https://api.github.com/repos/owner/repo/deployments"));
    Value::Object(repo)
}

/// Create a complete mock PR JSON that matches GitHub's API and octocrab's expectations.
fn mock_pr(
    number: u64,
    title: &str,
    merged_at: Option<chrono::DateTime<Utc>>,
    body: Option<&str>,
    labels: Vec<&str>,
) -> Value {
    let repo = mock_repo();
    let user = mock_user("testuser", 100);

    let label_objects: Vec<Value> = labels
        .iter()
        .enumerate()
        .map(|(i, l)| {
            json!({
                "id": i + 1,
                "node_id": format!("L_{}", i + 1),
                "url": "https://api.github.com/repos/owner/repo/labels/label",
                "name": *l,
                "color": "fc2929",
                "default": false
            })
        })
        .collect();

    let head = json!({
        "label": "owner:feature",
        "ref": "feature",
        "sha": "abc123def456789",
        "user": user.clone(),
        "repo": repo.clone()
    });

    let base = json!({
        "label": "owner:main",
        "ref": "main",
        "sha": "def456abc789",
        "user": mock_user("owner", 1),
        "repo": repo
    });

    let links = json!({
        "self": { "href": format!("https://api.github.com/repos/owner/repo/pulls/{}", number) },
        "html": { "href": format!("https://github.com/owner/repo/pull/{}", number) },
        "issue": { "href": format!("https://api.github.com/repos/owner/repo/issues/{}", number) },
        "comments": { "href": format!("https://api.github.com/repos/owner/repo/issues/{}/comments", number) },
        "review_comments": { "href": format!("https://api.github.com/repos/owner/repo/pulls/{}/comments", number) },
        "review_comment": { "href": "https://api.github.com/repos/owner/repo/pulls/comments{/number}" },
        "commits": { "href": format!("https://api.github.com/repos/owner/repo/pulls/{}/commits", number) },
        "statuses": { "href": "https://api.github.com/repos/owner/repo/statuses/abc123def456789" }
    });

    let merged_by = if merged_at.is_some() {
        Some(mock_user("merger", 200))
    } else {
        None
    };

    // Build the PR object using a Map to avoid macro recursion limits
    let mut pr = Map::new();
    pr.insert("url".into(), json!(format!("https://api.github.com/repos/owner/repo/pulls/{}", number)));
    pr.insert("id".into(), json!(number * 1000));
    pr.insert("node_id".into(), json!(format!("PR_{}", number)));
    pr.insert("html_url".into(), json!(format!("https://github.com/owner/repo/pull/{}", number)));
    pr.insert("diff_url".into(), json!(format!("https://github.com/owner/repo/pull/{}.diff", number)));
    pr.insert("patch_url".into(), json!(format!("https://github.com/owner/repo/pull/{}.patch", number)));
    pr.insert("issue_url".into(), json!(format!("https://api.github.com/repos/owner/repo/issues/{}", number)));
    pr.insert("commits_url".into(), json!(format!("https://api.github.com/repos/owner/repo/pulls/{}/commits", number)));
    pr.insert("review_comments_url".into(), json!(format!("https://api.github.com/repos/owner/repo/pulls/{}/comments", number)));
    pr.insert("review_comment_url".into(), json!("https://api.github.com/repos/owner/repo/pulls/comments{/number}"));
    pr.insert("comments_url".into(), json!(format!("https://api.github.com/repos/owner/repo/issues/{}/comments", number)));
    pr.insert("statuses_url".into(), json!("https://api.github.com/repos/owner/repo/statuses/abc123"));
    pr.insert("number".into(), json!(number));
    pr.insert("state".into(), json!("closed"));
    pr.insert("locked".into(), json!(false));
    pr.insert("title".into(), json!(title));
    pr.insert("body".into(), json!(body));
    pr.insert("user".into(), user);
    pr.insert("labels".into(), json!(label_objects));
    pr.insert("assignee".into(), Value::Null);
    pr.insert("assignees".into(), json!([]));
    pr.insert("requested_reviewers".into(), json!([]));
    pr.insert("requested_teams".into(), json!([]));
    pr.insert("milestone".into(), Value::Null);
    pr.insert("created_at".into(), json!("2024-01-01T00:00:00Z"));
    pr.insert("updated_at".into(), json!("2024-01-15T00:00:00Z"));
    pr.insert("closed_at".into(), json!(merged_at.map(|d| d.to_rfc3339())));
    pr.insert("merged_at".into(), json!(merged_at.map(|d| d.to_rfc3339())));
    pr.insert("merge_commit_sha".into(), json!("abc123def456"));
    pr.insert("head".into(), head);
    pr.insert("base".into(), base);
    pr.insert("draft".into(), json!(false));
    pr.insert("merged".into(), json!(merged_at.is_some()));
    pr.insert("mergeable".into(), json!(true));
    pr.insert("mergeable_state".into(), json!("clean"));
    pr.insert("merged_by".into(), json!(merged_by));
    pr.insert("comments".into(), json!(0));
    pr.insert("review_comments".into(), json!(0));
    pr.insert("maintainer_can_modify".into(), json!(true));
    pr.insert("commits".into(), json!(1));
    pr.insert("additions".into(), json!(10));
    pr.insert("deletions".into(), json!(2));
    pr.insert("changed_files".into(), json!(1));
    pr.insert("_links".into(), links);

    Value::Object(pr)
}

/// Create a simple merged PR for a given page number.
fn pr_for_page(page: u32) -> serde_json::Value {
    let merged_at = Utc.with_ymd_and_hms(2024, 1, (page % 28) + 1, 12, 0, 0).unwrap();
    mock_pr(
        page as u64,
        &format!("PR from page {}", page),
        Some(merged_at),
        Some(&format!("Body for PR {}", page)),
        vec![],
    )
}

// =============================================================================
// PAGINATION TESTS
// =============================================================================

#[tokio::test]
async fn test_pagination_single_page() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let pr1 = mock_pr(1, "First PR", Some(merged_at), Some("Body 1"), vec!["bug"]);
    let pr2 = mock_pr(2, "Second PR", Some(merged_at), Some("Body 2"), vec!["feature"]);

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .and(query_param("state", "closed"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![pr1, pr2]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    match &result {
        Ok(prs) => {
            assert_eq!(prs.len(), 2);
            assert_eq!(prs[0].title, "First PR");
            assert_eq!(prs[1].title, "Second PR");
        }
        Err(e) => panic!("Expected success, got error: {:?}", e),
    }
}

#[tokio::test]
async fn test_pagination_multiple_pages() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let pr1 = mock_pr(1, "PR 1", Some(merged_at), None, vec![]);
    let pr2 = mock_pr(2, "PR 2", Some(merged_at), None, vec![]);
    let pr3 = mock_pr(3, "PR 3", Some(merged_at), None, vec![]);

    // Page 1: Return 2 PRs with next page link
    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .and(query_param("page", "1"))
        .respond_with(
            ResponseTemplate::new(200)
                .set_body_json(vec![pr1, pr2])
                .insert_header(
                    "Link",
                    &format!(
                        "<{}/repos/owner/repo/pulls?page=2>; rel=\"next\"",
                        server.uri()
                    ),
                ),
        )
        .mount(&server)
        .await;

    // Page 2: Return 1 PR, no next link
    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .and(query_param("page", "2"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![pr3]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    assert_eq!(prs.len(), 3);
}

#[tokio::test]
async fn test_empty_repository() {
    let server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(Vec::<serde_json::Value>::new()))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    assert!(result.is_ok());
    assert!(result.unwrap().is_empty());
}

// =============================================================================
// DATE FILTERING TESTS
// =============================================================================

#[tokio::test]
async fn test_filter_since_date() {
    let server = MockServer::start().await;

    let old_date = Utc.with_ymd_and_hms(2024, 1, 15, 12, 0, 0).unwrap();
    let new_date = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();

    let old_pr = mock_pr(1, "Old PR", Some(old_date), None, vec![]);
    let new_pr = mock_pr(2, "New PR", Some(new_date), None, vec![]);

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![old_pr, new_pr]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let since = Utc.with_ymd_and_hms(2024, 6, 1, 0, 0, 0).unwrap();

    let result = fetch_merged_prs_with_client(&client, "owner", "repo", Some(since), None, None).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    assert_eq!(prs.len(), 1);
    assert_eq!(prs[0].title, "New PR");
}

#[tokio::test]
async fn test_filter_until_date() {
    let server = MockServer::start().await;

    let old_date = Utc.with_ymd_and_hms(2024, 1, 15, 12, 0, 0).unwrap();
    let new_date = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();

    let old_pr = mock_pr(1, "Old PR", Some(old_date), None, vec![]);
    let new_pr = mock_pr(2, "New PR", Some(new_date), None, vec![]);

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![old_pr, new_pr]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let until = Utc.with_ymd_and_hms(2024, 3, 1, 0, 0, 0).unwrap();

    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, Some(until), None).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    assert_eq!(prs.len(), 1);
    assert_eq!(prs[0].title, "Old PR");
}

#[tokio::test]
async fn test_filter_date_range() {
    let server = MockServer::start().await;

    let jan = Utc.with_ymd_and_hms(2024, 1, 15, 12, 0, 0).unwrap();
    let jun = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let dec = Utc.with_ymd_and_hms(2024, 12, 15, 12, 0, 0).unwrap();

    let pr1 = mock_pr(1, "January PR", Some(jan), None, vec![]);
    let pr2 = mock_pr(2, "June PR", Some(jun), None, vec![]);
    let pr3 = mock_pr(3, "December PR", Some(dec), None, vec![]);

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![pr1, pr2, pr3]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let since = Utc.with_ymd_and_hms(2024, 5, 1, 0, 0, 0).unwrap();
    let until = Utc.with_ymd_and_hms(2024, 9, 1, 0, 0, 0).unwrap();

    let result =
        fetch_merged_prs_with_client(&client, "owner", "repo", Some(since), Some(until), None).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    assert_eq!(prs.len(), 1);
    assert_eq!(prs[0].title, "June PR");
}

#[tokio::test]
async fn test_filter_excludes_all() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let pr = mock_pr(1, "PR", Some(merged_at), None, vec![]);

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![pr]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    // Date range that excludes all PRs
    let since = Utc.with_ymd_and_hms(2025, 1, 1, 0, 0, 0).unwrap();

    let result = fetch_merged_prs_with_client(&client, "owner", "repo", Some(since), None, None).await;

    assert!(result.is_ok());
    assert!(result.unwrap().is_empty());
}

// =============================================================================
// BODY TRUNCATION TESTS
// =============================================================================

#[tokio::test]
async fn test_body_at_limit_not_truncated() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let body_at_limit = "x".repeat(MAX_BODY_LENGTH);
    let pr = mock_pr(1, "PR", Some(merged_at), Some(&body_at_limit), vec![]);

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![pr]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    let body = prs[0].body.as_ref().unwrap();
    assert_eq!(body.len(), MAX_BODY_LENGTH);
    assert!(!body.ends_with("... [truncated]"));
}

#[tokio::test]
async fn test_body_over_limit_truncated() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let body_over_limit = "x".repeat(MAX_BODY_LENGTH + 100);
    let pr = mock_pr(1, "PR", Some(merged_at), Some(&body_over_limit), vec![]);

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![pr]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    let body = prs[0].body.as_ref().unwrap();
    assert!(body.ends_with("... [truncated]"));
    assert!(body.len() < body_over_limit.len());
}

#[tokio::test]
async fn test_pr_with_no_body() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let pr = mock_pr(1, "PR", Some(merged_at), None, vec![]);

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![pr]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    assert!(prs[0].body.is_none());
}

// =============================================================================
// ERROR HANDLING TESTS
// =============================================================================

#[tokio::test]
async fn test_rate_limit_error() {
    let server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(403).set_body_json(serde_json::json!({
            "message": "API rate limit exceeded for user",
            "documentation_url": "https://docs.github.com/rest/overview/resources-in-the-rest-api#rate-limiting"
        })))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    assert!(result.is_err());
    match result.unwrap_err() {
        GitHubError::RateLimited { .. } => {}
        other => panic!("Expected RateLimited error, got {:?}", other),
    }
}

#[tokio::test]
async fn test_repository_not_found() {
    let server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path("/repos/owner/nonexistent/pulls"))
        .respond_with(ResponseTemplate::new(404).set_body_json(serde_json::json!({
            "message": "Not Found",
            "documentation_url": "https://docs.github.com/rest"
        })))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "nonexistent", None, None, None).await;

    assert!(result.is_err());
    match result.unwrap_err() {
        GitHubError::RepositoryNotFound { owner, repo } => {
            assert_eq!(owner, "owner");
            assert_eq!(repo, "nonexistent");
        }
        other => panic!("Expected RepositoryNotFound error, got {:?}", other),
    }
}

// =============================================================================
// SAFETY LIMIT TESTS
// =============================================================================

#[tokio::test]
async fn test_safety_limit_50_pages() {
    let server = MockServer::start().await;

    // Mock all pages 1-51 to always have a next link
    for page in 1u32..=51 {
        let has_next = page < 51;
        let pr = pr_for_page(page);

        let mut response = ResponseTemplate::new(200).set_body_json(vec![pr]);
        if has_next {
            response = response.insert_header(
                "Link",
                &format!(
                    "<{}/repos/owner/repo/pulls?page={}>; rel=\"next\"",
                    server.uri(),
                    page + 1
                ),
            );
        }

        // Expect pages 1-50 to be called once each, page 51 should not be called
        let expected_calls = if page <= 50 { 1 } else { 0 };

        Mock::given(method("GET"))
            .and(path("/repos/owner/repo/pulls"))
            .and(query_param("page", page.to_string()))
            .respond_with(response)
            .expect(expected_calls)
            .mount(&server)
            .await;
    }

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    // Should have 50 PRs (one per page), not 51
    assert_eq!(prs.len(), 50);
}

// =============================================================================
// EDGE CASE TESTS
// =============================================================================

#[tokio::test]
async fn test_filters_unmerged_prs() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let merged_pr = mock_pr(1, "Merged PR", Some(merged_at), None, vec![]);
    let unmerged_pr = mock_pr(2, "Unmerged PR", None, None, vec![]); // No merged_at

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![merged_pr, unmerged_pr]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    // Only the merged PR should be returned
    assert_eq!(prs.len(), 1);
    assert_eq!(prs[0].title, "Merged PR");
}

#[tokio::test]
async fn test_pr_with_labels() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let pr = mock_pr(
        1,
        "PR with labels",
        Some(merged_at),
        None,
        vec!["bug", "priority:high", "needs-review"],
    );

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![pr]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    assert_eq!(prs[0].labels.len(), 3);
    assert!(prs[0].labels.contains(&"bug".to_string()));
    assert!(prs[0].labels.contains(&"priority:high".to_string()));
    assert!(prs[0].labels.contains(&"needs-review".to_string()));
}

#[tokio::test]
async fn test_pr_with_no_labels() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let pr = mock_pr(1, "PR", Some(merged_at), None, vec![]);

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![pr]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    assert!(prs[0].labels.is_empty());
}

// =============================================================================
// NONZERO PR NUMBER TESTS
// =============================================================================

#[tokio::test]
async fn test_skips_zero_pr_number() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let valid_pr = mock_pr(1, "Valid PR", Some(merged_at), None, vec![]);

    // Create a PR with number 0 (invalid, should be skipped)
    let mut zero_pr = mock_pr(0, "Zero PR", Some(merged_at), None, vec![]);
    // Ensure number is 0 in the JSON (mock_pr already sets it, but be explicit)
    if let Value::Object(ref mut map) = zero_pr {
        map.insert("number".into(), json!(0));
    }

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(vec![valid_pr, zero_pr]))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    // Only the valid PR should be returned (zero PR is skipped)
    assert_eq!(prs.len(), 1);
    assert_eq!(prs[0].title, "Valid PR");
}

// =============================================================================
// PR LIMIT TESTS
// =============================================================================

#[tokio::test]
async fn test_pr_limit_stops_fetching_early() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let prs: Vec<_> = (1..=10)
        .map(|i| mock_pr(i, &format!("PR {}", i), Some(merged_at), None, vec![]))
        .collect();

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(prs))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    // Set limit to 5
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, Some(5)).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    assert_eq!(prs.len(), 5);
}

#[tokio::test]
async fn test_pr_limit_none_uses_default() {
    // This test verifies that None triggers the default limit behavior
    // In unit tests, we can't easily test the env var behavior,
    // but we can verify the function accepts None without panicking
    let server = MockServer::start().await;

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(Vec::<Value>::new()))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, None).await;

    assert!(result.is_ok());
}

#[tokio::test]
async fn test_pr_limit_exact_at_boundary() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let prs: Vec<_> = (1..=5)
        .map(|i| mock_pr(i, &format!("PR {}", i), Some(merged_at), None, vec![]))
        .collect();

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(prs))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    // Limit equals exactly the number of available PRs
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, Some(5)).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    assert_eq!(prs.len(), 5);
}

#[tokio::test]
async fn test_pr_limit_greater_than_available() {
    let server = MockServer::start().await;

    let merged_at = Utc.with_ymd_and_hms(2024, 6, 15, 12, 0, 0).unwrap();
    let prs: Vec<_> = (1..=3)
        .map(|i| mock_pr(i, &format!("PR {}", i), Some(merged_at), None, vec![]))
        .collect();

    Mock::given(method("GET"))
        .and(path("/repos/owner/repo/pulls"))
        .respond_with(ResponseTemplate::new(200).set_body_json(prs))
        .mount(&server)
        .await;

    let client = mock_client(&server).await;
    // Limit is greater than available PRs
    let result = fetch_merged_prs_with_client(&client, "owner", "repo", None, None, Some(100)).await;

    assert!(result.is_ok());
    let prs = result.unwrap();
    // Should return all available PRs (3), not 100
    assert_eq!(prs.len(), 3);
}
