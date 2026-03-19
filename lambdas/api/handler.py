import json
import logging
import os
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

TABLE_NAME = os.environ["DYNAMO_TABLE_NAME"]
dynamo     = boto3.resource("dynamodb")
table      = dynamo.Table(TABLE_NAME)

CORS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type":                 "application/json",
}


def last_7_dates() -> list[str]:
    """Return the 7 most recent calendar dates as YYYY-MM-DD strings."""
    today = datetime.now(timezone.utc).date()
    return [(today - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(7)]


def handler(event, context):
    # Handle CORS preflight from the browser
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS, "body": ""}

    logger.info("GET /movers invoked")

    dates  = last_7_dates()
    movers = []

    for date_str in dates:
        try:
            resp = table.get_item(Key={"date": date_str})
            item = resp.get("Item")
            if item:
                movers.append({
                    "date":        item["date"],
                    "ticker":      item["ticker"],
                    "pct_change":  float(item["pct_change"]),
                    "close_price": float(item["close_price"]),
                })
            else:
                logger.info(f"No record for {date_str} (weekend or no data yet)")
        except ClientError as e:
            logger.error(f"DynamoDB read error for {date_str}: {e.response['Error']['Message']}")
            # Continue — return partial results rather than failing the whole request

    # Most recent first
    movers.sort(key=lambda x: x["date"], reverse=True)
    logger.info(f"Returning {len(movers)} records")

    return {
        "statusCode": 200,
        "headers": CORS,
        "body": json.dumps({"count": len(movers), "movers": movers}),
    }