"""CompanyCam contact-photos schemas."""

from pydantic import BaseModel


class CompanyCamPhoto(BaseModel):
    """One photo, reduced to what the sidebar gallery renders."""

    id: str
    thumbnail_url: str
    web_url: str
    captured_at: int | None = None
    creator_name: str | None = None


class CompanyCamProjectPhotos(BaseModel):
    """A matched CompanyCam project and its recent photos."""

    project_id: str
    project_name: str
    project_url: str
    photo_count: int
    address: str | None = None
    photos: list[CompanyCamPhoto]


class ContactCompanyCamPhotosResponse(BaseModel):
    """All CompanyCam projects matched to one CRM contact."""

    connected: bool
    projects: list[CompanyCamProjectPhotos]
