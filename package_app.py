"""Packaging entrypoint for building the app executable and installer.

This script is intended for developer/release usage.

It runs:
- PyInstaller to produce the application executable
- Inno Setup's ISCC to produce the installer

All paths are local and may need to be adjusted for each developer machine.
"""

###############################################################################
# RELEASE PRE-REQUISITES:
# 1. Ensure VERSION in src/config.py is updated.
# 2. Ensure assets/translations.json is complete.
###############################################################################

from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from src.config import VERSION, APP_NAME

INNO_SETUP_SCRIPT = Path(__file__).parent / "PetcareEfficiencyToolkit.iss"

def find_iscc() -> str:
    """Try to find the Inno Setup compiler executable in common locations."""
    standard_paths = [
        os.environ.get("ISCC_PATH"),  # Check environment variable first
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    
    for path in standard_paths:
        if path and os.path.exists(path):
            return path
            
    return "ISCC.exe"  # Fallback to PATH

def package_application() -> None:
    """Build the PyInstaller executable and compile the Inno Setup installer.

    Notes:
        - Assets are included via the explicit --add-data flag.
        - PyInstaller must be installed in the active environment.
        - Inno Setup's ISCC.exe must exist at ISCC_EXECUTABLE_PATH.
    """

    # 1. Define absolute project paths
    base_dir = Path(__file__).parent.absolute()
    entry_point = base_dir / "main.py"
    assets_dir = base_dir / "assets"
    icon_path = assets_dir / "icons" / "app-ico.ico"

    if not icon_path.exists():
        print(f"Warning: Icon not found at {icon_path}. Falling back to no icon.")
        icon_path = None

    # 2. Construct the PyInstaller command
    print(f"Step 1: Running PyInstaller for {APP_NAME} v{VERSION}...")
    command = [
        sys.executable, "-m", "PyInstaller",
        "--noconsole",  # GUI app (no console window)
        "--onedir",  # Create a distribution folder
        "--clean",  # Clear cache before building
        f"--name={APP_NAME}",
        f"--icon={icon_path}" if icon_path else "",
        f"--add-data={str(assets_dir)}{os.pathsep}assets",
        # Optimization/exclusions: avoid heavy Qt modules
        "--exclude-module=PyQt5.QtWebEngine",
        "--exclude-module=PyQt5.QtWebEngineWidgets",
        "--exclude-module=PyQt5.QtWebKit",
        str(entry_point),
    ]

    # Remove empty strings from command list (in case icon was missing)
    command = [arg for arg in command if arg]

    try:
        subprocess.run(command, check=True)
        print("PyInstaller build successful.")
    except FileNotFoundError as e:
        raise FileNotFoundError(
            "PyInstaller not found in the current environment. Run: pip install pyinstaller"
        ) from e
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"PyInstaller packaging failed with exit code: {e.returncode}") from e

    # 3. Compile Inno Setup installer
    print("\nStep 2: Compiling Inno Setup Installer...")
    iscc_path = find_iscc()
    try:
        # Pass the version from config.py directly to Inno Setup as a definition
        iscc_command = [
            iscc_path,
            f"/dMyAppVersion={VERSION}",
            str(INNO_SETUP_SCRIPT)
        ]
        subprocess.run(iscc_command, check=True)
        print(f"Installer generated successfully using {INNO_SETUP_SCRIPT}")
    except FileNotFoundError as e:
        raise FileNotFoundError(
            f"Inno Setup ISCC.exe not found at {iscc_path}. Check your installation or ISCC_PATH environment variable."
        ) from e
    except subprocess.CalledProcessError as e:
        print("\nTip: Ensure the Source paths in your .iss file match the 'dist' folder name produced by PyInstaller.")
        raise RuntimeError(f"Inno Setup compilation failed with exit code: {e.returncode}") from e


if __name__ == "__main__":
    package_application()
