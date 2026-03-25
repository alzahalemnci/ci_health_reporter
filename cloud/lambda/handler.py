"""
handler.py — CI Health Reporter Lambda function
================================================

What this does:
  1. Receives a POST /health request from a Home Assistant instance
  2. Saves the JSON payload to S3 as {timestamp}-{uuid}.json
  3. Returns {"status": "ok"} with HTTP 200

boto3 (the AWS Python SDK) is pre-installed in the Lambda runtime —
no requirements.txt needed.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3

s3 = boto3.client('s3')
BUCKET = os.environ['BUCKET_NAME']


def lambda_handler(event, context):
    # Parse the incoming JSON body
    try:
        body = event.get('body') or '{}'
        data = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        data = {}

    # Build a unique S3 key: 2026-03-24T21-05-00-a3f9c1b2.json
    timestamp = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H-%M-%S')
    key = f"{timestamp}-{uuid.uuid4().hex[:8]}.json"

    # Write the payload to S3
    s3.put_object(
        Bucket=BUCKET,
        Key=key,
        Body=json.dumps(data, indent=2),
        ContentType='application/json',
    )

    return {
        'statusCode': 200,
        'headers': {'Content-Type': 'application/json'},
        'body': json.dumps({'status': 'ok'}),
    }
