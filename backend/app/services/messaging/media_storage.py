"""Private S3-compatible object storage for inbound MMS media."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import TYPE_CHECKING

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings, settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class MMSStorageError(RuntimeError):
    """An MMS object-storage operation failed."""


class MMSStorageNotConfiguredError(MMSStorageError):
    """Private MMS object storage has not been fully configured."""


@dataclass(frozen=True, slots=True)
class StoredMedia:
    """Verified metadata for an object successfully written to storage."""

    object_key: str
    size_bytes: int
    sha256: str


class MMSMediaStorage:
    """Small synchronous wrapper around a private S3-compatible bucket.

    Worker callers must run these network-bound methods through
    ``asyncio.to_thread`` so boto3 never blocks the application's event loop.
    """

    def __init__(
        self,
        *,
        client: S3Client,
        bucket: str,
        max_bytes: int,
        presign_ttl_seconds: int,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._max_bytes = max_bytes
        self._presign_ttl_seconds = presign_ttl_seconds

    @classmethod
    def from_settings(cls, config: Settings = settings) -> MMSMediaStorage:
        """Build storage from validated application settings without ambient AWS auth."""
        if not config.mms_storage_enabled:
            raise MMSStorageNotConfiguredError("Private MMS storage is not configured")

        client = boto3.client(
            "s3",
            endpoint_url=config.mms_storage_endpoint_url,
            aws_access_key_id=config.mms_storage_access_key_id,
            aws_secret_access_key=config.mms_storage_secret_access_key.get_secret_value(),
            region_name=config.mms_storage_region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": config.mms_storage_addressing_style},
            ),
        )
        return cls(
            client=client,
            bucket=config.mms_storage_bucket,
            max_bytes=config.mms_storage_max_download_bytes,
            presign_ttl_seconds=config.mms_storage_presign_ttl_seconds,
        )

    def upload_bytes(self, *, object_key: str, data: bytes, content_type: str) -> StoredMedia:
        """Write one bounded private object and return its verified metadata."""
        self._validate_object_key(object_key)
        if not data:
            raise ValueError("MMS media cannot be empty")
        if len(data) > self._max_bytes:
            raise ValueError(f"MMS media exceeds the {self._max_bytes}-byte storage limit")
        if not content_type.strip():
            raise ValueError("MMS media content type cannot be blank")

        digest = sha256(data).hexdigest()
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=object_key,
                Body=data,
                ContentLength=len(data),
                ContentType=content_type,
                Metadata={"sha256": digest},
            )
        except (BotoCoreError, ClientError) as exc:
            raise MMSStorageError("MMS media upload failed") from exc

        return StoredMedia(
            object_key=object_key,
            size_bytes=len(data),
            sha256=digest,
        )

    def create_download_url(self, *, object_key: str, expires_in: int | None = None) -> str:
        """Create a short-lived GET URL for one private object.

        ``expires_in`` overrides the configured TTL for callers whose URL has to
        outlive a single request — a lighting design stays open in the browser
        far longer than an MMS thumbnail is fetched for.
        """
        self._validate_object_key(object_key)
        ttl = self._presign_ttl_seconds if expires_in is None else expires_in
        if ttl <= 0:
            raise ValueError("Presigned URL lifetime must be positive")
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self._bucket, "Key": object_key},
                ExpiresIn=ttl,
            )
        except (BotoCoreError, ClientError) as exc:
            raise MMSStorageError("MMS media URL generation failed") from exc
        if not url:
            raise MMSStorageError("MMS media URL generation returned an empty URL")
        return url

    def delete(self, *, object_key: str) -> None:
        """Delete one private object; S3 delete semantics are idempotent."""
        self._validate_object_key(object_key)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=object_key)
        except (BotoCoreError, ClientError) as exc:
            raise MMSStorageError("MMS media deletion failed") from exc

    def get_cors_rules(self) -> list[dict[str, object]]:
        """Return the bucket's browser CORS rules, or an empty list when unset."""
        try:
            response = self._client.get_bucket_cors(Bucket=self._bucket)
        except ClientError as exc:
            # A bucket with no rule configured answers NoSuchCORSConfiguration;
            # authentication and provider failures must remain visible.
            if exc.response.get("Error", {}).get("Code") == "NoSuchCORSConfiguration":
                return []
            raise MMSStorageError("Bucket CORS read failed") from exc
        except BotoCoreError as exc:
            raise MMSStorageError("Bucket CORS read failed") from exc
        return [dict(rule) for rule in response.get("CORSRules", [])]

    def put_cors_rules(self, *, allowed_origins: list[str]) -> None:
        """Allow exactly these browser origins to read objects via GET.

        Presigned URLs remain the authorization; CORS only decides whether a
        browser hands the bytes to page script — and therefore whether a canvas
        that drew the image stays untainted. Never allow ``*`` here.
        """
        if not allowed_origins or "*" in allowed_origins:
            raise ValueError("Bucket CORS requires an explicit, non-wildcard origin list")
        try:
            self._client.put_bucket_cors(
                Bucket=self._bucket,
                CORSConfiguration={
                    "CORSRules": [
                        {
                            "AllowedOrigins": allowed_origins,
                            "AllowedMethods": ["GET"],
                            "AllowedHeaders": ["*"],
                            "MaxAgeSeconds": 3000,
                        }
                    ]
                },
            )
        except (BotoCoreError, ClientError) as exc:
            raise MMSStorageError("Bucket CORS write failed") from exc

    @staticmethod
    def _validate_object_key(object_key: str) -> None:
        segments = object_key.split("/")
        if (
            not object_key
            or object_key.startswith("/")
            or "\\" in object_key
            or any(segment in {"", ".", ".."} for segment in segments)
        ):
            raise ValueError("MMS media object key must be a normalized relative path")
