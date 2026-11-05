"""
Parts Inventory Tracker - Version info

To publish a new release:
  1. Bump APP_VERSION below (e.g. 1.0.0 -> 1.0.1)
  2. Push to GitHub
GitHub Actions builds the .exe and publishes it as a release automatically,
and every installed copy will offer the update on its next launch.
"""

APP_VERSION = "1.0.0"

# GitHub "owner/repo" that releases are published to.
# Change this if your repository has a different name.
GITHUB_REPO = "tylersword12/parts-inventory-tracker"
