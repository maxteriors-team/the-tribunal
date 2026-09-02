"""Lighting-project persistence and the private image storage behind it.

Deliberately re-exports nothing. ``job_service`` imports ``images`` from this
package, and ``project_service`` reaches ``app.services.jobs`` transitively via
workspace provisioning — so a convenience re-export here would close an import
cycle. Import the module you need directly.
"""
