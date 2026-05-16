"""Application metadata and versioning.

Keep a single source of truth for the app version so it can be reused in
README/CHANGELOG and for installer metadata.
"""

APP_NAME = "PET"
# Use a plain SemVer value here (no display prefix); package_app.py passes it
# to the installer, whose comparison orders releases and pre-releases.
VERSION = "1.1.0"
ORG_NAME = "Mohamed Thabet"
