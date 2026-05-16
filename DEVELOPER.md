# Developer Guide - Pet Clinic Manager Legacy

This document contains technical instructions for setting up the development environment and building the application from source.

## 1. Environment Setup

1. **Python Version**: Ensure Python 3.9 or higher is installed.
2. **Virtual Environment**:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Linux/macOS
   .venv\Scripts\activate     # Windows
   ```
3. **Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Run Application**:
   ```bash
   python main.py
   ```

## 2. Build & Packaging

The project uses a two-step packaging process:

### Step 1: PyInstaller
To generate the standalone executable folder in `dist/`, run the spec file:
`.venv\Scripts\pyinstaller --clean --noconfirm "Pet Clinic Manager Legacy.spec"`

### Step 2: Inno Setup
To generate the Windows Installer (.exe), ensure Inno Setup 6 is installed, then run the automation script:
`python package_app.py`

*Note: The installer is configured to preserve user data in `%LocalAppData%\PetClinic` during upgrades.*