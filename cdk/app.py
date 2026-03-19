import os
import aws_cdk as cdk
from dotenv import load_dotenv
from stacks.ingestion_stack import IngestionStack
from stacks.api_stack import ApiStack

# Load API keys from .env file
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), "..", ".env"))

app = cdk.App()

env = cdk.Environment(
    account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
    region=os.environ.get("CDK_DEFAULT_REGION", "us-east-1"),
)

# Instantiate both stacks
# Stack 1: EventBridge + Ingestion Lambda + DynamoDB
ingestion = IngestionStack(app, "IngestionStack", env=env)

# Stack 2: API Gateway + API Lambda + S3 + CloudFront
# Receives the DynamoDB table as a cross-stack reference
ApiStack(app, "ApiStack", dynamo_table=ingestion.table, env=env)

app.synth()