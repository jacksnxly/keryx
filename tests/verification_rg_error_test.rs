#![cfg(unix)]

use std::env;
use std::fs;
use std::os::unix::fs::PermissionsExt;

use keryx::changelog::{ChangelogCategory, ChangelogEntry};
use keryx::verification::gather_verification_evidence;
use serial_test::serial;

#[test]
#[serial]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_stub_scan_error_marks_incomplete() {
    let dir = tempfile::tempdir().expect("Failed to create temp dir");

    let src = dir.path().join("src");
    fs::create_dir(&src).unwrap();

    let widget_rs = src.join("widget.rs");
    fs::write(&widget_rs, "pub fn widget() -> bool { true }\n").unwrap();

    let bin = dir.path().join("bin");
    fs::create_dir(&bin).unwrap();

    let rg_path = bin.join("rg");
    fs::write(
        &rg_path,
        r#"#!/bin/sh
if printf '%s\n' "$@" | grep -q -- "--json"; then
  echo "rg: simulated failure" >&2
  exit 2
fi

if printf '%s\n' "$@" | grep -q -- "--files-with-matches"; then
  echo "src/widget.rs"
  exit 0
fi

if printf '%s\n' "$@" | grep -q -- "--count-matches"; then
  echo "src/widget.rs:2"
  exit 0
fi

if printf '%s\n' "$@" | grep -q -- "--max-count"; then
  echo "1:widget"
  exit 0
fi

exit 1
"#,
    )
    .unwrap();

    let mut perms = fs::metadata(&rg_path).unwrap().permissions();
    perms.set_mode(0o755);
    fs::set_permissions(&rg_path, perms).unwrap();

    let old_path = env::var("PATH").unwrap_or_default();
    unsafe {
        env::set_var("PATH", format!("{}:{}", bin.display(), old_path));
    }

    let entries = vec![ChangelogEntry {
        category: ChangelogCategory::Added,
        description: "Added Widget support".to_string(),
    }];

    let evidence = gather_verification_evidence(&entries, dir.path());

    unsafe {
        env::set_var("PATH", old_path);
    }

    assert_eq!(evidence.entries.len(), 1);
    let entry_ev = &evidence.entries[0];

    let widget_match = entry_ev
        .keyword_matches
        .iter()
        .find(|k| k.keyword == "widget")
        .expect("Expected 'widget' keyword match");

    assert!(
        widget_match.occurrence_count.is_some(),
        "Expected count to be present for keyword"
    );
    assert!(
        !widget_match.appears_complete,
        "Stub scan failure should mark keyword as incomplete"
    );
}
