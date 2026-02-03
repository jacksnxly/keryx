//! Version file detection and update across ecosystems.
//!
//! Supports Cargo.toml, package.json, and pyproject.toml (PEP 621 + Poetry).

use std::path::{Path, PathBuf};

use semver::Version;

use crate::error::ShipError;

/// The kind of version file detected.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum VersionFileKind {
    CargoToml,
    PackageJson,
    PyprojectToml,
}

impl std::fmt::Display for VersionFileKind {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            VersionFileKind::CargoToml => write!(f, "Cargo.toml"),
            VersionFileKind::PackageJson => write!(f, "package.json"),
            VersionFileKind::PyprojectToml => write!(f, "pyproject.toml"),
        }
    }
}

/// A detected version file with its current version.
#[derive(Debug, Clone)]
pub struct VersionFile {
    pub path: PathBuf,
    pub kind: VersionFileKind,
    pub current_version: Version,
}

/// Detect version files in the project root.
///
/// Checks for Cargo.toml, package.json, and pyproject.toml in order.
/// Returns all found files. Returns `ShipError::NoVersionFiles` if none found.
pub fn detect_version_files(root: &Path) -> Result<Vec<VersionFile>, ShipError> {
    let mut files = Vec::new();

    // Cargo.toml
    let cargo_path = root.join("Cargo.toml");
    if cargo_path.exists() {
        if let Some(version) = read_cargo_version(&cargo_path)? {
            files.push(VersionFile {
                path: cargo_path,
                kind: VersionFileKind::CargoToml,
                current_version: version,
            });
        }
    }

    // package.json
    let package_path = root.join("package.json");
    if package_path.exists() {
        if let Some(version) = read_package_json_version(&package_path)? {
            files.push(VersionFile {
                path: package_path,
                kind: VersionFileKind::PackageJson,
                current_version: version,
            });
        }
    }

    // pyproject.toml
    let pyproject_path = root.join("pyproject.toml");
    if pyproject_path.exists() {
        if let Some(version) = read_pyproject_version(&pyproject_path)? {
            files.push(VersionFile {
                path: pyproject_path,
                kind: VersionFileKind::PyprojectToml,
                current_version: version,
            });
        }
    }

    if files.is_empty() {
        return Err(ShipError::NoVersionFiles);
    }

    Ok(files)
}

/// Update a version file to the new version.
pub fn update_version_file(file: &VersionFile, new_version: &Version) -> Result<(), ShipError> {
    match file.kind {
        VersionFileKind::CargoToml => update_toml_version(&file.path, new_version, &["package", "version"]),
        VersionFileKind::PackageJson => update_package_json(&file.path, new_version),
        VersionFileKind::PyprojectToml => update_pyproject_toml(&file.path, new_version),
    }
}

// --- Cargo.toml ---

fn read_cargo_version(path: &Path) -> Result<Option<Version>, ShipError> {
    let content = read_file(path)?;
    let doc = parse_toml(path, &content)?;

    let version_str = doc
        .get("package")
        .and_then(|p| p.get("version"))
        .and_then(|v| v.as_str());

    match version_str {
        Some(s) => match Version::parse(s) {
            Ok(v) => Ok(Some(v)),
            Err(_) => Ok(None),
        },
        None => Ok(None),
    }
}

// --- package.json ---

fn read_package_json_version(path: &Path) -> Result<Option<Version>, ShipError> {
    let content = read_file(path)?;
    let json: serde_json::Value = serde_json::from_str(&content).map_err(|e| {
        ShipError::VersionFileUpdateFailed {
            path: path.to_path_buf(),
            reason: format!("Invalid JSON: {}", e),
        }
    })?;

    let version_str = json.get("version").and_then(|v| v.as_str());

    match version_str {
        Some(s) => match Version::parse(s) {
            Ok(v) => Ok(Some(v)),
            Err(_) => Ok(None),
        },
        None => Ok(None),
    }
}

fn update_package_json(path: &Path, new_version: &Version) -> Result<(), ShipError> {
    let content = read_file(path)?;
    let mut json: serde_json::Value = serde_json::from_str(&content).map_err(|e| {
        ShipError::VersionFileUpdateFailed {
            path: path.to_path_buf(),
            reason: format!("Invalid JSON: {}", e),
        }
    })?;

    json["version"] = serde_json::Value::String(new_version.to_string());

    let output = serde_json::to_string_pretty(&json).map_err(|e| {
        ShipError::VersionFileUpdateFailed {
            path: path.to_path_buf(),
            reason: format!("Failed to serialize JSON: {}", e),
        }
    })?;

    // npm uses trailing newline
    write_file(path, &format!("{}\n", output))
}

// --- pyproject.toml ---

fn read_pyproject_version(path: &Path) -> Result<Option<Version>, ShipError> {
    let content = read_file(path)?;
    let doc = parse_toml(path, &content)?;

    // PEP 621: [project].version
    let version_str = doc
        .get("project")
        .and_then(|p| p.get("version"))
        .and_then(|v| v.as_str())
        // Poetry fallback: [tool.poetry].version
        .or_else(|| {
            doc.get("tool")
                .and_then(|t| t.get("poetry"))
                .and_then(|p| p.get("version"))
                .and_then(|v| v.as_str())
        });

    match version_str {
        Some(s) => match Version::parse(s) {
            Ok(v) => Ok(Some(v)),
            Err(_) => Ok(None),
        },
        None => Ok(None),
    }
}

fn update_pyproject_toml(path: &Path, new_version: &Version) -> Result<(), ShipError> {
    let content = read_file(path)?;
    let mut doc = parse_toml(path, &content)?;

    // Try PEP 621 first
    if doc
        .get("project")
        .and_then(|p| p.get("version"))
        .is_some()
    {
        doc["project"]["version"] = toml_edit::value(new_version.to_string());
    }
    // Fall back to Poetry
    else if doc
        .get("tool")
        .and_then(|t| t.get("poetry"))
        .and_then(|p| p.get("version"))
        .is_some()
    {
        doc["tool"]["poetry"]["version"] = toml_edit::value(new_version.to_string());
    } else {
        return Err(ShipError::VersionFileUpdateFailed {
            path: path.to_path_buf(),
            reason: "No version field found in [project] or [tool.poetry]".into(),
        });
    }

    write_file(path, &doc.to_string())
}

// --- Shared helpers ---

fn update_toml_version(path: &Path, new_version: &Version, keys: &[&str]) -> Result<(), ShipError> {
    let content = read_file(path)?;
    let mut doc = parse_toml(path, &content)?;

    // Navigate to the nested key and update
    match keys {
        [table, key] => {
            doc[*table][*key] = toml_edit::value(new_version.to_string());
        }
        _ => {
            return Err(ShipError::VersionFileUpdateFailed {
                path: path.to_path_buf(),
                reason: "Unsupported key path".into(),
            });
        }
    }

    write_file(path, &doc.to_string())
}

fn parse_toml(path: &Path, content: &str) -> Result<toml_edit::DocumentMut, ShipError> {
    content.parse::<toml_edit::DocumentMut>().map_err(|e| {
        ShipError::VersionFileUpdateFailed {
            path: path.to_path_buf(),
            reason: format!("Invalid TOML: {}", e),
        }
    })
}

fn read_file(path: &Path) -> Result<String, ShipError> {
    std::fs::read_to_string(path).map_err(|e| ShipError::VersionFileUpdateFailed {
        path: path.to_path_buf(),
        reason: format!("Failed to read: {}", e),
    })
}

fn write_file(path: &Path, content: &str) -> Result<(), ShipError> {
    std::fs::write(path, content).map_err(|e| ShipError::VersionFileUpdateFailed {
        path: path.to_path_buf(),
        reason: format!("Failed to write: {}", e),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;

    #[test]
    fn test_detect_cargo_toml() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(
            dir.path().join("Cargo.toml"),
            "[package]\nname = \"test\"\nversion = \"1.2.3\"\n",
        )
        .unwrap();

        let files = detect_version_files(dir.path()).unwrap();
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].kind, VersionFileKind::CargoToml);
        assert_eq!(files[0].current_version, Version::new(1, 2, 3));
    }

    #[test]
    fn test_detect_package_json() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(
            dir.path().join("package.json"),
            r#"{"name": "test", "version": "2.0.0"}"#,
        )
        .unwrap();

        let files = detect_version_files(dir.path()).unwrap();
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].kind, VersionFileKind::PackageJson);
        assert_eq!(files[0].current_version, Version::new(2, 0, 0));
    }

    #[test]
    fn test_detect_pyproject_pep621() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(
            dir.path().join("pyproject.toml"),
            "[project]\nname = \"test\"\nversion = \"3.1.0\"\n",
        )
        .unwrap();

        let files = detect_version_files(dir.path()).unwrap();
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].kind, VersionFileKind::PyprojectToml);
        assert_eq!(files[0].current_version, Version::new(3, 1, 0));
    }

    #[test]
    fn test_detect_pyproject_poetry_fallback() {
        let dir = tempfile::tempdir().unwrap();
        fs::write(
            dir.path().join("pyproject.toml"),
            "[tool.poetry]\nname = \"test\"\nversion = \"0.1.0\"\n",
        )
        .unwrap();

        let files = detect_version_files(dir.path()).unwrap();
        assert_eq!(files.len(), 1);
        assert_eq!(files[0].current_version, Version::new(0, 1, 0));
    }

    #[test]
    fn test_detect_no_version_files() {
        let dir = tempfile::tempdir().unwrap();
        let result = detect_version_files(dir.path());
        assert!(matches!(result, Err(ShipError::NoVersionFiles)));
    }

    #[test]
    fn test_update_cargo_toml_preserves_formatting() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("Cargo.toml");
        fs::write(
            &path,
            "[package]\nname = \"test\"\n# version comment\nversion = \"1.0.0\"\nedition = \"2024\"\n",
        )
        .unwrap();

        let file = VersionFile {
            path: path.clone(),
            kind: VersionFileKind::CargoToml,
            current_version: Version::new(1, 0, 0),
        };
        update_version_file(&file, &Version::new(2, 0, 0)).unwrap();

        let content = fs::read_to_string(&path).unwrap();
        assert!(content.contains("version = \"2.0.0\""));
        assert!(content.contains("# version comment"));
        assert!(content.contains("edition = \"2024\""));
    }

    #[test]
    fn test_update_package_json() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("package.json");
        fs::write(&path, r#"{"name": "test", "version": "1.0.0"}"#).unwrap();

        let file = VersionFile {
            path: path.clone(),
            kind: VersionFileKind::PackageJson,
            current_version: Version::new(1, 0, 0),
        };
        update_version_file(&file, &Version::new(1, 1, 0)).unwrap();

        let content = fs::read_to_string(&path).unwrap();
        assert!(content.contains("\"version\": \"1.1.0\""));
    }

    #[test]
    fn test_update_pyproject_pep621() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("pyproject.toml");
        fs::write(
            &path,
            "[project]\nname = \"test\"\nversion = \"1.0.0\"\n",
        )
        .unwrap();

        let file = VersionFile {
            path: path.clone(),
            kind: VersionFileKind::PyprojectToml,
            current_version: Version::new(1, 0, 0),
        };
        update_version_file(&file, &Version::new(1, 2, 0)).unwrap();

        let content = fs::read_to_string(&path).unwrap();
        assert!(content.contains("version = \"1.2.0\""));
    }

    #[test]
    fn test_update_pyproject_poetry() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("pyproject.toml");
        fs::write(
            &path,
            "[tool.poetry]\nname = \"test\"\nversion = \"0.1.0\"\n",
        )
        .unwrap();

        let file = VersionFile {
            path: path.clone(),
            kind: VersionFileKind::PyprojectToml,
            current_version: Version::new(0, 1, 0),
        };
        update_version_file(&file, &Version::new(0, 2, 0)).unwrap();

        let content = fs::read_to_string(&path).unwrap();
        assert!(content.contains("version = \"0.2.0\""));
    }
}
