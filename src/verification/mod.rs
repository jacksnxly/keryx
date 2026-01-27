//! Verification module for agentic changelog validation.
//!
//! This module provides functionality to verify AI-generated changelog entries
//! against the actual codebase, catching hallucinations and inaccuracies.

use std::process::Command;

use crate::error::VerificationError;

pub mod evidence;
pub mod scanner;

pub use evidence::{Confidence, CountCheck, EntryEvidence, KeywordMatch, StubIndicator, VerificationEvidence};
pub use scanner::gather_verification_evidence;

/// Check if ripgrep (rg) is installed and accessible.
///
/// This is required for the verification module to scan the codebase for evidence.
/// If ripgrep is not installed, verification cannot function properly.
pub fn check_ripgrep_installed() -> Result<(), VerificationError> {
    let output = Command::new("rg")
        .arg("--version")
        .output();

    match output {
        Ok(out) if out.status.success() => Ok(()),
        _ => Err(VerificationError::RipgrepNotInstalled),
    }
}
