//! Unit tests for the `check_ripgrep_installed()` function.
//!
//! These tests verify that ripgrep availability detection works correctly
//! across different scenarios: success, not installed, and failure cases.
//!
//! Note: These tests modify the PATH environment variable and must run serially
//! to avoid race conditions.

#![cfg(unix)]

use std::env;
use std::fs;
use std::os::unix::fs::PermissionsExt;

use keryx::error::VerificationError;
use keryx::verification::check_ripgrep_installed;
use serial_test::serial;

/// Test that check_ripgrep_installed returns Ok when rg is available and works.
#[test]
#[serial]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_check_ripgrep_installed_success() {
    let dir = tempfile::tempdir().expect("Failed to create temp dir");

    let bin = dir.path().join("bin");
    fs::create_dir(&bin).unwrap();

    let rg_path = bin.join("rg");
    fs::write(
        &rg_path,
        r#"#!/bin/sh
echo "ripgrep 14.0.0"
exit 0
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

    let result = check_ripgrep_installed();

    unsafe {
        env::set_var("PATH", old_path);
    }

    assert!(result.is_ok(), "Expected Ok(()), got {:?}", result);
}

/// Test that check_ripgrep_installed returns RipgrepNotInstalled when rg is not in PATH.
#[test]
#[serial]
fn test_check_ripgrep_not_installed() {
    let dir = tempfile::tempdir().expect("Failed to create temp dir");

    let bin = dir.path().join("bin");
    fs::create_dir(&bin).unwrap();

    let old_path = env::var("PATH").unwrap_or_default();
    unsafe {
        env::set_var("PATH", bin.display().to_string());
    }

    let result = check_ripgrep_installed();

    unsafe {
        env::set_var("PATH", old_path);
    }

    match result {
        Err(VerificationError::RipgrepNotInstalled) => {}
        other => panic!(
            "Expected VerificationError::RipgrepNotInstalled, got {:?}",
            other
        ),
    }
}

/// Test that check_ripgrep_installed returns RipgrepFailed when rg exits with non-zero code.
#[test]
#[serial]
#[cfg_attr(not(feature = "rg-tests"), ignore = "requires ripgrep")]
fn test_check_ripgrep_failed() {
    let dir = tempfile::tempdir().expect("Failed to create temp dir");

    let bin = dir.path().join("bin");
    fs::create_dir(&bin).unwrap();

    let rg_path = bin.join("rg");
    fs::write(
        &rg_path,
        r#"#!/bin/sh
echo "rg: corrupted binary or missing dependency" >&2
exit 2
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

    let result = check_ripgrep_installed();

    unsafe {
        env::set_var("PATH", old_path);
    }

    match result {
        Err(VerificationError::RipgrepFailed { exit_code, stderr }) => {
            assert_eq!(exit_code, Some(2), "Expected exit code 2");
            assert!(
                stderr.contains("corrupted binary"),
                "Expected stderr to contain error message, got: {}",
                stderr
            );
        }
        other => panic!(
            "Expected VerificationError::RipgrepFailed, got {:?}",
            other
        ),
    }
}
