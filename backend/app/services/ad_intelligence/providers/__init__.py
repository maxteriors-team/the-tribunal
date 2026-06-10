"""Ad-library intelligence providers.

Concrete adapters that turn a public ad library into normalized advertisers +
ads behind one interface (:class:`AdIntelligenceProvider`):

    * ``meta_ad_library``      — Meta Ad Library official Graph API (default).
    * ``meta_thirdparty``      — config-gated third-party Meta fallback.
    * ``google_ads_transparency`` — Google Ads Transparency Center (SerpApi).
"""
