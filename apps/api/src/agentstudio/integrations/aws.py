"""boto3 clients configured the same way for AWS and for the local emulator.

`AWS_ENDPOINT_URL` (set only for the emulator) switches S3 to path-style addressing;
everything else is identical, which is the point of running against an emulator.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import boto3
from botocore.config import Config

from agentstudio.core.config import Settings

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client
    from mypy_boto3_secretsmanager import SecretsManagerClient
    from mypy_boto3_sqs import SQSClient


def _config(settings: Settings) -> Config:
    return Config(
        region_name=settings.aws_region,
        retries={"max_attempts": 5, "mode": "standard"},
        connect_timeout=5,
        read_timeout=30,
        s3={"addressing_style": "path" if settings.aws_endpoint_url else "auto"},
    )


def s3_client(settings: Settings) -> S3Client:
    return boto3.client(
        "s3", endpoint_url=settings.aws_endpoint_url or None, config=_config(settings)
    )


def sqs_client(settings: Settings) -> SQSClient:
    return boto3.client(
        "sqs", endpoint_url=settings.aws_endpoint_url or None, config=_config(settings)
    )


def secrets_client(settings: Settings) -> SecretsManagerClient:
    return boto3.client(
        "secretsmanager", endpoint_url=settings.aws_endpoint_url or None, config=_config(settings)
    )
