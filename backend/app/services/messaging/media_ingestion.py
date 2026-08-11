"""Bounded download and verification for signed inbound media URLs."""

from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urljoin, urlsplit

import httpx


class MediaDownloadError(RuntimeError):
    """A safe, classified provider-media download failure."""

    def __init__(self, code: str, *, retryable: bool) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class DownloadedMedia:
    """Verified bytes ready for private object storage."""

    data: bytes
    content_type: str
    size_bytes: int
    sha256: str


async def download_provider_media(
    *,
    client: httpx.AsyncClient,
    source_url: str,
    declared_content_type: str,
    max_bytes: int,
    expected_size_bytes: int | None = None,
    expected_sha256: str | None = None,
) -> DownloadedMedia:
    """Download one signed HTTPS object with strict size and digest checks."""
    _validate_source_url(source_url)
    try:
        data, response_content_type = await _download_bounded_bytes(
            client=client,
            source_url=source_url,
            max_bytes=max_bytes,
        )
    except MediaDownloadError:
        raise
    except httpx.HTTPError as exc:
        raise MediaDownloadError("provider_unavailable", retryable=True) from exc

    if not data:
        raise MediaDownloadError("media_empty", retryable=False)
    if expected_size_bytes is not None and len(data) != expected_size_bytes:
        raise MediaDownloadError("provider_size_mismatch", retryable=False)

    digest = sha256(data).hexdigest()
    if expected_sha256 is not None and digest != expected_sha256.lower():
        raise MediaDownloadError("provider_sha256_mismatch", retryable=False)

    fallback_content_type = _normalize_content_type(declared_content_type)
    content_type = response_content_type or fallback_content_type or "application/octet-stream"

    return DownloadedMedia(
        data=data,
        content_type=content_type,
        size_bytes=len(data),
        sha256=digest,
    )


async def _download_bounded_bytes(
    *,
    client: httpx.AsyncClient,
    source_url: str,
    max_bytes: int,
) -> tuple[bytes, str]:
    current_url = source_url
    for redirect_count in range(4):
        async with client.stream(
            "GET",
            current_url,
            follow_redirects=False,
        ) as response:
            if response.is_redirect:
                location = response.headers.get("location")
                if not location or redirect_count == 3:
                    raise MediaDownloadError(
                        "provider_redirect_invalid",
                        retryable=False,
                    )
                current_url = urljoin(current_url, location)
                _validate_source_url(current_url)
                continue
            return await _read_bounded_response(response, max_bytes=max_bytes)

    raise MediaDownloadError("provider_redirect_invalid", retryable=False)


async def _read_bounded_response(
    response: httpx.Response,
    *,
    max_bytes: int,
) -> tuple[bytes, str]:
    if response.status_code >= 400:
        raise MediaDownloadError(
            "provider_http_error",
            retryable=_is_retryable_status(response.status_code),
        )
    if response.status_code >= 300:
        raise MediaDownloadError("provider_redirect_invalid", retryable=False)

    declared_length = _parse_content_length(response.headers.get("content-length"))
    if declared_length is not None and declared_length > max_bytes:
        raise MediaDownloadError("media_too_large", retryable=False)

    chunks: list[bytes] = []
    downloaded_size = 0
    async for chunk in response.aiter_bytes():
        downloaded_size += len(chunk)
        if downloaded_size > max_bytes:
            raise MediaDownloadError("media_too_large", retryable=False)
        chunks.append(chunk)

    data = b"".join(chunks)
    content_type = _normalize_content_type(response.headers.get("content-type"))
    return data, content_type


def _validate_source_url(source_url: str) -> None:
    parsed = urlsplit(source_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise MediaDownloadError("invalid_provider_url", retryable=False)


def _parse_content_length(value: str | None) -> int | None:
    if not value:
        return None
    try:
        parsed = int(value)
    except ValueError:
        return None
    return parsed if parsed >= 0 else None


def _normalize_content_type(value: str | None) -> str:
    if not value:
        return ""
    normalized = value.split(";", maxsplit=1)[0].strip().lower()
    return normalized if len(normalized) <= 127 else ""


def _is_retryable_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429} or status_code >= 500
