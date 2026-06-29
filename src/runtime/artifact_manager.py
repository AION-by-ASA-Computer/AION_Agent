import os
from pathlib import Path
from typing import Optional, Tuple
from ..session_workspace import safe_resolve, ensure_session_dirs, session_root

ARTIFACT_TYPE_MAP = {
    "plan": ".md",
    "python": ".py",
    "javascript": ".js",
    "typescript": ".ts",
    "html": ".html",
    "css": ".css",
    "json": ".json",
    "yaml": ".yaml",
    "csv": ".csv",
    "markdown": ".md",
    "bash": ".sh",
    "sql": ".sql",
    "text": ".txt",
    "application/x-python": ".py",
    "application/javascript": ".js",
    "text/html": ".html",
    "text/csv": ".csv",
    "application/json": ".json",
}


class ArtifactManager:
    def __init__(self, session_id: str):
        self.session_id = session_id
        ensure_session_dirs(session_id)
        self._root = session_root(session_id)

    def save(
        self,
        identifier: str,
        content: str,
        artifact_type: str,
        filename: Optional[str] = None,
    ) -> Tuple[Path, int]:
        """
        Save artifact to workspace/.
        Returns (path, version_number).
        """
        ext = ARTIFACT_TYPE_MAP.get(artifact_type, ".txt")

        if filename:
            # Clean filename and ensure it has correct extension if missing
            base_name, fext = os.path.splitext(filename)
            ext = fext or ext
            target_name = f"{base_name}{ext}"
        else:
            target_name = f"{identifier}{ext}"

        # We save to workspace/ directly to be visible to sandbox tools
        version_num = self._get_next_version_num(target_name)

        # If version > 1, we might want to append version to filename to avoid overwriting
        # but the user might want the "latest" to have the clean name.
        # Strategy: the requested filename is ALWAYS the latest. We move old ones to .versions/
        final_rel_path = f"workspace/{target_name}"

        if version_num > 1:
            # Move existing file to versions archive if it exists
            old_file = self._root / final_rel_path
            if old_file.exists():
                archive_dir = self._root / "workspace" / ".versions" / target_name
                archive_dir.mkdir(parents=True, exist_ok=True)
                archive_path = archive_dir / f"v{version_num - 1}{ext}"
                old_file.replace(archive_path)

        path = safe_resolve(self.session_id, final_rel_path, must_exist=False)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

        return path, version_num

    def _get_next_version_num(self, target_name: str) -> int:
        """Find the next version number by checking both workspace and .versions/"""
        version = 1
        # Check current file
        if (self._root / "workspace" / target_name).exists():
            version += 1

        # Check archive
        archive_dir = self._root / "workspace" / ".versions" / target_name
        if archive_dir.exists():
            existing_versions = list(
                archive_dir.glob(f"v*{os.path.splitext(target_name)[1]}")
            )
            if existing_versions:
                # Extract max version from filenames like v1.py, v2.py
                import re

                v_nums = []
                for v_file in existing_versions:
                    m = re.search(r"v(\d+)", v_file.name)
                    if m:
                        v_nums.append(int(m.group(1)))
                if v_nums:
                    version = max(version, max(v_nums) + 1)

        return version

    def auto_execute_sandboxed(self, path: Path) -> Optional[str]:
        """Execute Python artifact via subprocess (sandbox_run_python_file path)."""
        if path.suffix != ".py":
            return None

        rel = path.relative_to(self._root / "workspace")
        relative_path = f"workspace/{rel.as_posix()}"

        from ..tools.session_code import SessionSandboxExecutor

        try:
            executor = SessionSandboxExecutor(self.session_id)
            return executor.run_file(relative_path)
        except Exception as e:
            return f"Error during auto-execution: {e}"
