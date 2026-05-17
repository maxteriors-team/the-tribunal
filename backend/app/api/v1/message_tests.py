"""Message test management endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import DB, CurrentUser, get_workspace
from app.models.message_test import MessageTest, TestVariant
from app.models.workspace import Workspace
from app.schemas.message_test import (
    ConvertToCampaignRequest,
    MessageTestAnalytics,
    MessageTestCreate,
    MessageTestResponse,
    MessageTestUpdate,
    MessageTestWithVariantsResponse,
    PaginatedMessageTests,
    SelectWinnerRequest,
    TestContactAdd,
    TestContactResponse,
    TestVariantCreate,
    TestVariantResponse,
    TestVariantUpdate,
)
from app.services.exceptions import NotFoundError, ValidationError
from app.services.message_tests import MessageTestService

router = APIRouter()


# === Message Test CRUD ===


@router.get("", response_model=PaginatedMessageTests)
async def list_message_tests(
    workspace_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    status_filter: str | None = None,
) -> PaginatedMessageTests:
    """List message tests in a workspace."""
    return await MessageTestService(db).list_tests(
        workspace_id, page=page, page_size=page_size, status_filter=status_filter
    )


@router.post(
    "", response_model=MessageTestWithVariantsResponse, status_code=status.HTTP_201_CREATED
)
async def create_message_test(
    workspace_id: uuid.UUID,
    test_in: MessageTestCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> MessageTest:
    """Create a new message test."""
    try:
        return await MessageTestService(db).create_test(workspace_id, test_in)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.get("/{test_id}", response_model=MessageTestWithVariantsResponse)
async def get_message_test(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> MessageTest:
    """Get a message test by ID with variants."""
    try:
        return await MessageTestService(db).get_test(test_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.put("/{test_id}", response_model=MessageTestResponse)
async def update_message_test(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    test_in: MessageTestUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> MessageTest:
    """Update a message test."""
    try:
        return await MessageTestService(db).update_test(test_id, workspace_id, test_in)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/{test_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message_test(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete a message test."""
    try:
        await MessageTestService(db).delete_test(test_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


# === Variant Management ===


@router.get("/{test_id}/variants", response_model=list[TestVariantResponse])
async def list_variants(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> list[TestVariantResponse]:
    """List variants for a message test."""
    try:
        return await MessageTestService(db).list_variants(test_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post(
    "/{test_id}/variants",
    response_model=TestVariantResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_variant(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    variant_in: TestVariantCreate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> TestVariant:
    """Create a new variant for a message test."""
    try:
        return await MessageTestService(db).create_variant(test_id, workspace_id, variant_in)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.put("/{test_id}/variants/{variant_id}", response_model=TestVariantResponse)
async def update_variant(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    variant_id: uuid.UUID,
    variant_in: TestVariantUpdate,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> TestVariant:
    """Update a variant."""
    try:
        return await MessageTestService(db).update_variant(
            test_id, variant_id, workspace_id, variant_in
        )
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.delete("/{test_id}/variants/{variant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_variant(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    variant_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> None:
    """Delete a variant."""
    try:
        await MessageTestService(db).delete_variant(test_id, variant_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


# === Contact Management ===


@router.post("/{test_id}/contacts", response_model=dict[str, int])
async def add_contacts(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    contacts_in: TestContactAdd,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, int]:
    """Add contacts to a message test."""
    try:
        return await MessageTestService(db).add_contacts(test_id, workspace_id, contacts_in)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.get("/{test_id}/contacts", response_model=list[TestContactResponse])
async def list_test_contacts(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
    status_filter: str | None = None,
    limit: int = Query(100, ge=1, le=500),
) -> list[TestContactResponse]:
    """List contacts in a message test."""
    return await MessageTestService(db).list_contacts(
        test_id, workspace_id, status_filter=status_filter, limit=limit
    )


# === Test Actions ===


@router.post("/{test_id}/start")
async def start_test(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, str]:
    """Start a message test."""
    try:
        return await MessageTestService(db).start_test(test_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{test_id}/pause")
async def pause_test(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, str]:
    """Pause a message test."""
    try:
        return await MessageTestService(db).pause_test(test_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


@router.post("/{test_id}/complete")
async def complete_test(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, str]:
    """Mark a message test as completed."""
    try:
        return await MessageTestService(db).complete_test(test_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e


# === Analytics ===


@router.get("/{test_id}/analytics", response_model=MessageTestAnalytics)
async def get_analytics(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> MessageTestAnalytics:
    """Get message test analytics."""
    try:
        return await MessageTestService(db).get_analytics(test_id, workspace_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


# === Winner Selection & Campaign Conversion ===


@router.post("/{test_id}/select-winner", response_model=MessageTestResponse)
async def select_winner(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    request: SelectWinnerRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> MessageTest:
    """Select a winning variant for the test."""
    try:
        return await MessageTestService(db).select_winner(test_id, workspace_id, request.variant_id)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e


@router.post("/{test_id}/convert-to-campaign", response_model=dict[str, str])
async def convert_to_campaign(
    workspace_id: uuid.UUID,
    test_id: uuid.UUID,
    request: ConvertToCampaignRequest,
    current_user: CurrentUser,
    db: DB,
    workspace: Annotated[Workspace, Depends(get_workspace)],
) -> dict[str, str]:
    """Convert a message test to a full campaign."""
    try:
        return await MessageTestService(db).convert_to_campaign(test_id, workspace_id, request)
    except NotFoundError as e:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(e)) from e
    except ValidationError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e
