"""Ad-library intelligence package.

Pulls advertisers + their ads from public ad libraries (Meta Ad Library,
Google Ads Transparency), detects the ICP — advertisers running consistently
but **not** iterating creatives — and feeds qualified advertisers into the
existing outbound CRM rails (prospects -> contacts -> outreach).

Submodules:
    * ``types`` / ``protocol``  — normalized provider contract.
    * ``providers``             — Meta + Google + third-party adapters.
    * ``ad_store``              — idempotent advertiser/creative persistence.
    * ``signals``               — the "consistent but not testing" signal engine.
    * ``icp``                   — workspace-configurable ICP thresholds.
    * ``prospecting``           — advertiser -> LeadProspect generation.
    * ``contact_tracing``       — landing-domain / page-about contact lookup.
"""
