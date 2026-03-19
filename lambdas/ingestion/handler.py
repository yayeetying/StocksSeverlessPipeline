import json
import logging
import os
import time
from datetime import date, timedelta, datetime, timezone

import boto3
from botocore.exceptions import ClientError
from massive import RESTClient
from massive.rest.models import ApiError

logger = logging.getLogger()
logger.setLevel(logging.INFO)

WATCHLIST = ["AAPL", "MSFT", "GOOGL", "AMZN", "TSLA", "NVDA"]
TABLE_NAME = os.environ["DYNAMO_TABLE_NAME"]
API_KEY    = os.environ["MASSIVE_API_KEY"]

dynamo = boto3.resource("dynamodb")
table  = dynamo.Table(TABLE_NAME)


def last_trading_date() -> str:
    """
    Return the most recent completed trading day as YYYY-MM-DD.
    If today is Monday, returns Friday. Weekends skip back to Friday.
    This is a simple calendar check — does not account for US holidays.
    """
    today = datetime.now(timezone.utc).date()
    # EventBridge fires after market close on weekdays, but handle edge cases
    offset = 1
    candidate = today - timedelta(days=offset)
    while candidate.weekday() >= 5:  # 5=Saturday, 6=Sunday
        offset += 1
        candidate = today - timedelta(days=offset)
    return candidate.strftime("%Y-%m-%d")


def fetch_quote(client: RESTClient, ticker: str, trade_date: str, retries: int = 3) -> dict | None:
    """
    Fetch daily open/close for one ticker using the Massive SDK.
    Uses get_daily_open_close which maps to:
      GET /v1/open-close/{ticker}/{date}
    Returns a dict with open_price, close_price, pct_change — or None on failure.
    """
    for attempt in range(1, retries + 1):
        try:
            result = client.get_daily_open_close(ticker, trade_date, adjusted=True)
            open_price  = float(result.open)
            close_price = float(result.close)

            if open_price == 0:
                logger.warning(f"[{ticker}] Open price is zero — skipping to avoid division error")
                return None

            pct_change = ((close_price - open_price) / open_price) * 100

            logger.info(f"[{ticker}] open={open_price} close={close_price} pct={pct_change:+.4f}%")

            return {
                "ticker":      ticker,
                "open_price":  open_price,
                "close_price": close_price,
                "pct_change":  round(pct_change, 4),
            }

        except ApiError as e:
            # 429 = rate limited, 403 = auth error, others = data issue
            logger.warning(f"[{ticker}] ApiError on attempt {attempt}/{retries}: status={e.status} message={e.message}")
            if e.status == 403:
                logger.error(f"[{ticker}] Auth failure — check MASSIVE_API_KEY")
                return None  # No point retrying auth errors
            if attempt < retries:
                wait = 2 ** attempt  # 2s, 4s back-off
                logger.info(f"[{ticker}] Retrying in {wait}s...")
                time.sleep(wait)

        except Exception as e:
            logger.error(f"[{ticker}] Unexpected error on attempt {attempt}/{retries}: {e}")
            if attempt < retries:
                time.sleep(2 ** attempt)

    logger.error(f"[{ticker}] All {retries} attempts exhausted — skipping")
    return None


def handler(event, context):
    trade_date = last_trading_date()
    logger.info(f"Starting ingestion for trading date: {trade_date}")

    client = RESTClient(api_key=API_KEY)

    results = []
    for ticker in WATCHLIST:
        quote = fetch_quote(client, ticker, trade_date)
        if quote:
            results.append(quote)

    if not results:
        msg = "No stock data retrieved from Massive API — aborting DynamoDB write"
        logger.error(msg)
        raise RuntimeError(msg)

    # Pick the stock with the largest absolute percentage move
    winner = max(results, key=lambda x: abs(x["pct_change"]))
    logger.info(
        f"Top mover: {winner['ticker']} ({winner['pct_change']:+.2f}%) "
        f"close=${winner['close_price']:.2f}"
    )

    try:
        table.put_item(
            Item={
                "date":        trade_date,
                "ticker":      winner["ticker"],
                # Store as string to avoid DynamoDB Decimal precision issues
                "pct_change":  str(winner["pct_change"]),
                "close_price": str(winner["close_price"]),
            }
        )
        logger.info(f"Successfully written to DynamoDB: {trade_date} → {winner['ticker']}")
    except ClientError as e:
        logger.error(f"DynamoDB write failed: {e.response['Error']['Message']}")
        raise

    return {
        "statusCode": 200,
        "body": json.dumps({"date": trade_date, "winner": winner}),
    }