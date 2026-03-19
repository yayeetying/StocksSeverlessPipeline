import os
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_dynamodb as dynamodb,
    aws_lambda as _lambda,
    aws_iam as iam,
    aws_scheduler as scheduler,
    Duration,
    RemovalPolicy,
)
from constructs import Construct


class IngestionStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # DynamoDB Table
        # Partition key: "date" (YYYY-MM-DD string).
        # because only 1 item (date) per trading day
        self.table = dynamodb.Table(
            self,
            "TopMoversTable",
            table_name="stocks-top-movers",
            partition_key=dynamodb.Attribute(
                name="date", type=dynamodb.AttributeType.STRING
            ),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,  # Free tier safe
            removal_policy=RemovalPolicy.RETAIN,  # Don't drop data on stack delete
        )

        # Ingestion Lambda
        # Reads MASSIVE_API_KEY from the environment
        massive_api_key = os.environ.get("MASSIVE_API_KEY", "")
        if not massive_api_key:
            raise ValueError(
                "MASSIVE_API_KEY is not set. Add it to your .env file."
            )

        ingestion_fn = _lambda.Function(
            self,
            "IngestionFunction",
            function_name="stocks-ingestion",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset(
                "../lambdas/ingestion",
                bundling=cdk.BundlingOptions(
                    image=_lambda.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash",
                        "-c",
                        "pip install -r requirements.txt -t /asset-output && cp -r . /asset-output",
                    ],
                ),
            ),
            timeout=Duration.seconds(120),  # Massive calls per ticker need buffer
            memory_size=128,
            environment={
                "MASSIVE_API_KEY": massive_api_key,
                "DYNAMO_TABLE_NAME": self.table.table_name,
            },
        )

        # Ingestion Lambda may only write to this table
        self.table.grant_write_data(ingestion_fn)

        # EventBridge Scheduler
        # Scheduler needs its own IAM role to invoke the Lambda
        scheduler_role = iam.Role(
            self,
            "SchedulerRole",
            assumed_by=iam.ServicePrincipal("scheduler.amazonaws.com"),
            inline_policies={
                "InvokeLambda": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            actions=["lambda:InvokeFunction"],
                            resources=[ingestion_fn.function_arn],
                        )
                    ]
                )
            },
        )

        # Runs Mon–Fri at 21:00 UTC (5 PM ET — after market close + data settle)
        scheduler.CfnSchedule(
            self,
            "DailyIngestionSchedule",
            schedule_expression="cron(0 21 ? * MON-FRI *)",
            flexible_time_window=scheduler.CfnSchedule.FlexibleTimeWindowProperty(
                mode="OFF"
            ),
            target=scheduler.CfnSchedule.TargetProperty(
                arn=ingestion_fn.function_arn,
                role_arn=scheduler_role.role_arn,
                retry_policy=scheduler.CfnSchedule.RetryPolicyProperty(
                    maximum_retry_attempts=2,
                    maximum_event_age_in_seconds=300,
                ),
            ),
        )

        # Outputs
        cdk.CfnOutput(self, "TableName", value=self.table.table_name)
        cdk.CfnOutput(self, "IngestionFunctionName", value=ingestion_fn.function_name)