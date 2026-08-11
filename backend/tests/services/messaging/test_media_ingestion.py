"""Tests for bounded inbound provider-media downloads."""

from hashlib import sha256

import httpx
import pytest

from app.services.messaging.media_ingestion import (
    MediaDownloadError,
    download_provider_media,
)


def _client(handler: httpx.AsyncBaseTransport) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=handler, follow_redirects=True, max_redirects=3)


async def test_download_provider_media_verifies_bytes_and_metadata() -> None:
    body = b"verified-photo"

    async def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "media.telnyx.com"
        return httpx.Response(
            200,
            headers={"Content-Type": "Image/JPEG; charset=binary"},
            content=body,
        )

    async with _client(httpx.MockTransport(handle)) as client:
        downloaded = await download_provider_media(
            client=client,
            source_url="https://media.telnyx.com/inbound/photo?token=opaque",
            declared_content_type="application/octet-stream",
            max_bytes=1024,
            expected_size_bytes=len(body),
            expected_sha256=sha256(body).hexdigest().upper(),
        )

    assert downloaded.data == body
    assert downloaded.content_type == "image/jpeg"
    assert downloaded.size_bytes == len(body)
    assert downloaded.sha256 == sha256(body).hexdigest()


async def test_download_provider_media_uses_declared_type_when_header_is_missing() -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"video")

    async with _client(httpx.MockTransport(handle)) as client:
        downloaded = await download_provider_media(
            client=client,
            source_url="https://media.telnyx.com/inbound/video",
            declared_content_type="video/mp4",
            max_bytes=1024,
        )

    assert downloaded.content_type == "video/mp4"


async def test_download_provider_media_follows_valid_https_redirect() -> None:
    requests: list[str] = []

    async def handle(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(
                307,
                headers={"Location": "https://cdn.telnyx.com/final"},
            )
        return httpx.Response(200, content=b"photo")

    async with _client(httpx.MockTransport(handle)) as client:
        downloaded = await download_provider_media(
            client=client,
            source_url="https://media.telnyx.com/start",
            declared_content_type="image/jpeg",
            max_bytes=1024,
        )

    assert downloaded.data == b"photo"
    assert requests == [
        "https://media.telnyx.com/start",
        "https://cdn.telnyx.com/final",
    ]


async def test_download_provider_media_rejects_insecure_redirect() -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"Location": "http://localhost/private"},
        )

    async with _client(httpx.MockTransport(handle)) as client:
        with pytest.raises(MediaDownloadError, match="invalid_provider_url") as exc_info:
            await download_provider_media(
                client=client,
                source_url="https://media.telnyx.com/start",
                declared_content_type="image/jpeg",
                max_bytes=1024,
            )

    assert exc_info.value.retryable is False


async def test_download_provider_media_rejects_large_content_length() -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"Content-Length": "5000"}, content=b"small")

    async with _client(httpx.MockTransport(handle)) as client:
        with pytest.raises(MediaDownloadError, match="media_too_large") as exc_info:
            await download_provider_media(
                client=client,
                source_url="https://media.telnyx.com/inbound/photo",
                declared_content_type="image/jpeg",
                max_bytes=100,
            )

    assert exc_info.value.retryable is False


async def test_download_provider_media_rejects_large_stream() -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 101)

    async with _client(httpx.MockTransport(handle)) as client:
        with pytest.raises(MediaDownloadError, match="media_too_large"):
            await download_provider_media(
                client=client,
                source_url="https://media.telnyx.com/inbound/photo",
                declared_content_type="image/jpeg",
                max_bytes=100,
            )


@pytest.mark.parametrize(
    ("expected_size", "expected_digest", "code"),
    [
        (999, None, "provider_size_mismatch"),
        (4, "0" * 64, "provider_sha256_mismatch"),
    ],
)
async def test_download_provider_media_rejects_metadata_mismatch(
    expected_size: int,
    expected_digest: str | None,
    code: str,
) -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"data")

    async with _client(httpx.MockTransport(handle)) as client:
        with pytest.raises(MediaDownloadError, match=code) as exc_info:
            await download_provider_media(
                client=client,
                source_url="https://media.telnyx.com/inbound/photo",
                declared_content_type="image/jpeg",
                max_bytes=100,
                expected_size_bytes=expected_size,
                expected_sha256=expected_digest,
            )

    assert exc_info.value.retryable is False


@pytest.mark.parametrize(
    ("status_code", "retryable"),
    [(404, False), (408, True), (429, True), (503, True)],
)
async def test_download_provider_media_classifies_http_failure(
    status_code: int,
    retryable: bool,
) -> None:
    async def handle(_: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code)

    async with _client(httpx.MockTransport(handle)) as client:
        with pytest.raises(MediaDownloadError, match="provider_http_error") as exc_info:
            await download_provider_media(
                client=client,
                source_url="https://media.telnyx.com/inbound/photo",
                declared_content_type="image/jpeg",
                max_bytes=100,
            )

    assert exc_info.value.retryable is retryable


@pytest.mark.parametrize(
    "source_url",
    [
        "http://media.telnyx.com/photo",
        "https://user:password@media.telnyx.com/photo",
        "https://media.telnyx.com/photo#fragment",
        "not-a-url",
    ],
)
async def test_download_provider_media_rejects_unsafe_url(source_url: str) -> None:
    transport = httpx.MockTransport(lambda _: httpx.Response(200, content=b"data"))
    async with _client(transport) as client:
        with pytest.raises(MediaDownloadError, match="invalid_provider_url") as exc_info:
            await download_provider_media(
                client=client,
                source_url=source_url,
                declared_content_type="image/jpeg",
                max_bytes=100,
            )

    assert exc_info.value.retryable is False
