# 📦 Version Sync Script

## What it does

Automatically updates project version in multiple files at once:
- `README.md` - project header
- `src/pyproject.toml` - Poetry package version  
- `src/main.py` - FastAPI app version

## Usage

```bash
# Set version to 1.6.0
python scripts/sync_version.py 1.6.0

# Or via Makefile
make sync-version VERSION=1.6.0

# Show current version
python scripts/sync_version.py
```

## Version Format

Uses **Semantic Versioning** (X.Y.Z):

- **MAJOR** (X) - Breaking changes (1.5.0 → 2.0.0)
- **MINOR** (Y) - New features (1.5.0 → 1.6.0)
- **PATCH** (Z) - Bug fixes (1.5.0 → 1.5.1)

**Valid:** `1.0.0`, `1.5.2`, `2.0.0`  
**Invalid:** `1.0`, `v1.0.0`, `1.0.0-beta`

## Examples

### Release new feature
```bash
make sync-version VERSION=1.6.0
git add .
git commit -m "Release v1.6.0: Add real-time alerts"
git tag v1.6.0
git push --tags
```

### Bug fix
```bash
make sync-version VERSION=1.5.1
git add .
git commit -m "Fix timeout handling"
```

### Breaking change
```bash
make sync-version VERSION=2.0.0
git add .
git commit -m "New API structure"
```

## How it works

1. Validates version format (X.Y.Z)
2. Updates README.md header
3. Updates pyproject.toml version
4. Updates main.py FastAPI version
5. Reports what changed

## Adding more files

Edit `scripts/sync_version.py` and add a new method:

```python
def sync_dockerfile(self, version: str) -> bool:
    dockerfile_path = self.project_root / "Dockerfile"
    if not dockerfile_path.exists():
        return False
    
    content = dockerfile_path.read_text()
    new_content = re.sub(
        r'(LABEL version=")[^"]+(")' ,
        rf'\g<1>{version}\g<2>',
        content
    )
    
    if content != new_content:
        dockerfile_path.write_text(new_content)
        print(f"  ✓ Updated Dockerfile to {version}")
        return True
    return False

# Add to set_version():
changed |= self.sync_dockerfile(version)
```
