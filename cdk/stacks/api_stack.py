import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_lambda as _lambda,
    aws_apigateway as apigw,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_dynamodb as dynamodb,
    aws_iam as iam,
    Duration,
    RemovalPolicy,
)
from constructs import Construct


class ApiStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        dynamo_table: dynamodb.Table,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # API Lambda
        # No bundling needed — only uses boto3 which is built into the runtime
        api_fn = _lambda.Function(
            self,
            "ApiFunction",
            function_name="stocks-api",
            runtime=_lambda.Runtime.PYTHON_3_12,
            handler="handler.handler",
            code=_lambda.Code.from_asset("../lambdas/api"),
            timeout=Duration.seconds(15),
            memory_size=128,
            environment={
                "DYNAMO_TABLE_NAME": dynamo_table.table_name,
            },
        )

        # API Lambda may only read from the table
        dynamo_table.grant_read_data(api_fn)

        # API Gateway
        api = apigw.RestApi(
            self,
            "StocksApi",
            rest_api_name="stocks-top-movers-api",
            description="Returns the last 7 days of top movers",
            default_cors_preflight_options=apigw.CorsOptions(
                allow_origins=apigw.Cors.ALL_ORIGINS,
                allow_methods=["GET", "OPTIONS"],
            ),
            deploy_options=apigw.StageOptions(stage_name="prod"),
        )

        movers_resource = api.root.add_resource("movers")
        movers_resource.add_method(
            "GET",
            apigw.LambdaIntegration(api_fn, proxy=True),
        )

        # S3 Bucket (private — CloudFront OAC only) 
        frontend_bucket = s3.Bucket(
            self,
            "FrontendBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # CloudFront Distribution
        oac = cloudfront.S3OriginAccessControl(
            self,
            "OAC",
            description="OAC for stocks frontend bucket",
        )

        distribution = cloudfront.Distribution(
            self,
            "FrontendDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_control(
                    frontend_bucket, origin_access_control=oac
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                cache_policy=cloudfront.CachePolicy.CACHING_OPTIMIZED,
            ),
            default_root_object="index.html",
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,  # US/EU only
        )

        # Deploy frontend files to S3
        # CDK reads the API Gateway URL at synthesis time 
        # and injects it as a file substitution 
        # so index.html gets the actual file + contents
        s3deploy.BucketDeployment(
            self,
            "FrontendDeployment",
            sources=[
                s3deploy.Source.asset("../frontend"),
                s3deploy.Source.json_data(
                    "config.json",
                    {"apiUrl": f"{api.url}movers"},
                ),
            ],
            destination_bucket=frontend_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
        )

        # Outputs
        cdk.CfnOutput(self, "ApiUrl",       value=f"{api.url}movers")
        cdk.CfnOutput(self, "CloudFrontUrl", value=f"https://{distribution.distribution_domain_name}")
        cdk.CfnOutput(self, "BucketName",   value=frontend_bucket.bucket_name)