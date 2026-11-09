"""Hermes plugin entry point for Snitchboard."""


def register(ctx):
    # Snitchboard is dashboard-only. Its tab and read-only routes come from
    # dashboard/manifest.json, so it registers no tools, hooks or middleware.
    # The function exists because the loader may require an entry point
    # beside plugin.yaml even for a dashboard-only plugin (PRD risk R1).
    pass
