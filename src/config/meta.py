"""Application metadata and versioning.

Keep a single source of truth for the app version so it can be reused in
README/CHANGELOG and for installer metadata.
"""

APP_NAME = "PET"
# Pre-release identifiers follow semver: "2.0.0-beta1" < "2.0.0-beta2" < "2.0.0".
# The installer (PetcareEfficiencyToolkit.iss) parses this string with the same
# ordering, so an older build never blocks a newer one from installing.
VERSION = "2.0.0-beta1"
ORG_NAME = "Mohamed Thabet"
