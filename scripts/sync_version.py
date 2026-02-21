import re
import sys
from pathlib import Path


class VersionManager:
    """Manages version synchronization across project files."""

    def __init__(self, project_root: Path = None):
        if project_root is None:
            project_root = Path(__file__).parent.parent
        self.project_root = project_root

        # Files to sync
        self.readme_path = project_root / "README.md"
        self.pyproject_path = project_root / "src" / "pyproject.toml"
        self.main_path = project_root / "src" / "main.py"

    def validate_version(self, version: str) -> bool:
        pattern = r"^\d+\.\d+\.\d+$"
        return bool(re.match(pattern, version))

    def get_current_version(self) -> str | None:
        if not self.pyproject_path.exists():
            return None

        content = self.pyproject_path.read_text()
        match = re.search(r'^version\s*=\s*"([^"]+)"', content, re.MULTILINE)
        return match.group(1) if match else None

    def sync_readme(self, version: str) -> bool:
        if not self.readme_path.exists():
            print(f"⚠️  README.md not found, skipping")
            return False

        content = self.readme_path.read_text()
        # Update shields.io badge version like:
        # ![Version](https://img.shields.io/badge/version-1.9.7-blue?style=for-the-badge)
        # replace the numeric part after "badge/version-"
        new_content = re.sub(
            r"(badge/version-)(\d+\.\d+\.\d+)",
            rf"\g<1>{version}",
            content
        )

        if content != new_content:
            self.readme_path.write_text(new_content)
            print(f"  ✓ Updated README.md to {version}")
            return True
        return False

    def sync_pyproject(self, version: str) -> bool:
        if not self.pyproject_path.exists():
            print(f"⚠️  pyproject.toml not found, skipping")
            return False

        content = self.pyproject_path.read_text()
        new_content = re.sub(
            r'^(version\s*=\s*")[^"]+(")' ,
            rf'\g<1>{version}\g<2>',
            content,
            flags=re.MULTILINE
        )

        if content != new_content:
            self.pyproject_path.write_text(new_content)
            print(f"  ✓ Updated pyproject.toml to {version}")
            return True
        return False

    def sync_main(self, version: str) -> bool:
        if not self.main_path.exists():
            print(f"⚠️  main.py not found, skipping")
            return False

        content = self.main_path.read_text()
        new_content = re.sub(
            r'(version\s*=\s*")[^"]+(")' ,
            rf'\g<1>{version}\g<2>',
            content
        )

        if content != new_content:
            self.main_path.write_text(new_content)
            print(f"  ✓ Updated main.py to {version}")
            return True
        return False

    def set_version(self, version: str) -> bool:
        if not self.validate_version(version):
            print(f"❌ Invalid version format: {version}")
            print("   Expected format: X.Y.Z (e.g., 1.6.0)")
            return False

        print(f"\n🔄 Setting version to: {version}")

        changed = False
        changed |= self.sync_readme(version)
        changed |= self.sync_pyproject(version)
        changed |= self.sync_main(version)

        return changed


def main():
    if len(sys.argv) != 2:
        print("Usage: python scripts/sync_version.py <version>")
        print("Example: python scripts/sync_version.py 1.6.0")
        print()

        # Show current version if available
        manager = VersionManager()
        current = manager.get_current_version()
        if current:
            print(f"Current version: {current}")

        sys.exit(1)

    version = sys.argv[1]
    manager = VersionManager()

    try:
        if manager.set_version(version):
            print(f"\n✅ Version {version} set successfully!")
        else:
            print(f"\n✓ All files already at version {version}")

        sys.exit(0)

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
