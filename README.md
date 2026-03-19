# StocksSeverlessPipeline
TRE Coding Challenge: Watchlist of Tech Stocks

https://dh69kx9fclwzt.cloudfront.net

## Architecture
```
EventBridge Scheduler (Mon–Fri 21:00 UTC)
        │ triggers
        ▼
  Ingestion Lambda  ──→  Massive API (stock data)
        │ writes
        ▼
    DynamoDB  ←──  API Lambda  ←──  API Gateway (GET /movers)
                                           ▲
                               Browser ←── CloudFront ←── S3 (SPA)
```

**Stacks**
- `IngestionStack` — data collection (EventBridge, Lambda, DynamoDB)
- `ApiStack`       — data retrieval and display (API Gateway, Lambda, S3, CloudFront)

## To Run the Code
```
cd cdk
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cdk bootstrap
cdk deploy --all
```
