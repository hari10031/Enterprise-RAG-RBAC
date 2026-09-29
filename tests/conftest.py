import os

# Point the app at the throwaway database before any eka module reads settings.
if os.environ.get("TEST_DATABASE_URL"):
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["COOKIE_SECURE"] = "false"
