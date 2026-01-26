//! Verification module for agentic changelog validation.
//!
//! This module provides functionality to verify AI-generated changelog entries
//! against the actual codebase, catching hallucinations and inaccuracies.

pub mod evidence;
pub mod scanner;

pub use evidence::{Confidence, EntryEvidence, VerificationEvidence, KeywordMatch, CountCheck};
pub use scanner::gather_verification_evidence;
