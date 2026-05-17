"""Find Leads AI schemas for AI-enhanced lead generation."""

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.scraping import BusinessResult


class AIImportLeadsRequest(BaseModel):
    """Request schema for importing leads with AI enrichment."""

    leads: list[BusinessResult] = Field(..., min_length=1, description="Leads to import")
    default_status: str = Field(default="new", description="Default contact status")
    add_tags: list[str] | None = Field(default=None, description="Tags to add to imported contacts")
    enable_enrichment: bool = Field(default=True, description="Enable website enrichment")
    min_lead_score: int = Field(
        default=80, ge=0, le=200, description="Minimum lead score threshold for import"
    )


class LeadImportDetail(BaseModel):
    """Per-lead detail in import response."""

    name: str
    status: str = Field(
        description="imported | rejected_low_score | enrichment_failed"
        " | skipped_duplicate | skipped_no_phone"
    )
    lead_score: int | None = None
    revenue_tier: str | None = None
    decision_maker_name: str | None = None
    decision_maker_title: str | None = None


class AIImportLeadsResponse(BaseModel):
    """Response schema for AI-enhanced lead import."""

    total: int = Field(..., description="Total leads submitted")
    imported: int = Field(default=0, description="Successfully imported count (score >= 80)")
    rejected_low_score: int = Field(default=0, description="Leads rejected with score < 80")
    enrichment_failed: int = Field(default=0, description="Leads where enrichment failed")
    skipped_duplicates: int = Field(default=0, description="Skipped due to duplicate phone")
    skipped_no_phone: int = Field(default=0, description="Skipped due to missing phone")
    queued_for_enrichment: int = Field(
        default=0, description="Always 0 (enrichment is now synchronous)"
    )
    errors: list[str] = Field(default_factory=list, description="Error messages")
    lead_details: list[LeadImportDetail] = Field(
        default_factory=list, description="Per-lead enrichment details"
    )


class SocialLinks(BaseModel):
    """Schema for social media links."""

    linkedin: str | None = None
    facebook: str | None = None
    twitter: str | None = None
    instagram: str | None = None
    youtube: str | None = None
    tiktok: str | None = None


class WebsiteMeta(BaseModel):
    """Schema for website metadata."""

    title: str | None = None
    description: str | None = None


class WebsiteSummary(BaseModel):
    """AI-generated website summary for lead personalization."""

    business_description: str | None = None
    services: list[str] = Field(default_factory=list)
    target_market: str | None = None
    unique_selling_points: list[str] = Field(default_factory=list)
    industry: str | None = None
    team_size_estimate: str = "unknown"
    years_in_business: int | None = None
    service_areas: list[str] = Field(default_factory=list)
    revenue_signals: list[str] = Field(default_factory=list)
    has_financing: bool = False
    certifications: list[str] = Field(default_factory=list)
    decision_maker_name: str | None = None
    decision_maker_title: str | None = None


class GooglePlacesData(BaseModel):
    """Schema for Google Places data stored in business_intel."""

    place_id: str
    rating: float | None = None
    review_count: int = 0
    types: list[str] = Field(default_factory=list)
    business_status: str = "OPERATIONAL"


class AdPixels(BaseModel):
    """Schema for detected advertising pixels."""

    meta_pixel: bool = False
    google_ads: bool = False
    google_analytics: bool = False
    gtm: bool = False
    linkedin_pixel: bool = False
    tiktok_pixel: bool = False


class BusinessIntel(BaseModel):
    """Schema for business intelligence data."""

    social_links: SocialLinks | None = None
    google_places: GooglePlacesData | None = None
    website_meta: WebsiteMeta | None = None
    website_summary: WebsiteSummary | None = None
    ad_pixels: AdPixels | None = None
    enrichment_error: str | None = None
    enrichment_failed_at: str | None = None

    model_config = {"extra": "allow"}


class EnrichedContactResponse(BaseModel):
    """Schema for an enriched contact in Find Leads AI."""

    id: int
    first_name: str
    last_name: str | None
    company_name: str | None
    phone_number: str
    email: str | None
    website_url: str | None
    linkedin_url: str | None
    enrichment_status: str | None
    enriched_at: str | None
    business_intel: dict[str, Any] | None
    lead_score: int | None = None

    model_config = {"from_attributes": True}
