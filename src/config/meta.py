"""Application metadata and versioning.

Keep a single source of truth for the app version so it can be reused in
README/CHANGELOG and for installer metadata.
"""

APP_NAME = "PET"
# Pre-release identifiers sort below their matching final version.
# The installer (PetcareEfficiencyToolkit.iss) parses this string with the same
# ordering, so an older build never blocks a newer one from installing.
VERSION = "1.1.0"
ORG_NAME = "Mohamed Thabet"
