---
description: "Update VCTK to the latest version"
allowed-tools: ["Bash"]
---

# Update VCTK

## Step 1: Check Current Version

```bash
LOCAL_VER=$(cat .claude/skills/vibe-coding-toolkit/.version 2>/dev/null | tr -d '[:space:]' || echo "not installed")
echo "Current version: $LOCAL_VER"
```

## Step 2: Check Remote Version

```bash
REMOTE_VER=$(curl -fsSL --connect-timeout 5 https://raw.githubusercontent.com/jacksnxly/claude-vibe-coding-toolkit/main/VERSION 2>/dev/null | tr -d '[:space:]' || echo "unknown")
echo "Latest version: $REMOTE_VER"
```

## Step 3: Determine Action

Compare versions:

- If `LOCAL_VER` equals `REMOTE_VER`: Report "Already up to date" and stop
- If `REMOTE_VER` is "unknown": Report "Could not check remote version" and stop
- Otherwise: Proceed to Step 4

## Step 4: Run Update

Execute the install script:

```bash
curl -fsSL https://raw.githubusercontent.com/jacksnxly/claude-vibe-coding-toolkit/main/install.sh | bash
```

## Step 5: Confirm Update

```bash
NEW_VER=$(cat .claude/skills/vibe-coding-toolkit/.version 2>/dev/null | tr -d '[:space:]')
echo "Updated to version: $NEW_VER"
```

Report completion:

```
✓ VCTK updated: {LOCAL_VER} → {NEW_VER}

Changelog: https://github.com/jacksnxly/claude-vibe-coding-toolkit/releases
```

---

## Rules

1. **DO** show version comparison before updating
2. **DO** report if already up to date
3. **DO NOT** update if versions match
4. **DO** provide link to changelog after update
