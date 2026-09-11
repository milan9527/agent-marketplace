import * as path from 'node:path'
import {
  App, CfnOutput, CfnParameter, Duration, RemovalPolicy, Stack, Tags,
  aws_bedrockagentcore as agentcore, aws_cloudfront as cloudfront,
  aws_cloudfront_origins as origins, aws_cognito as cognito,
  aws_ec2 as ec2, aws_ecs as ecs, aws_ecr_assets as assets,
  aws_elasticloadbalancingv2 as elb, aws_iam as iam,
  aws_logs as logs, aws_rds as rds, aws_s3 as s3, aws_s3_deployment as deployment,
} from 'aws-cdk-lib'

const app = new App()
const stack = new Stack(app, 'AgentMarketplace', {
  description: 'Agent Marketplace: separate web/API, RDS PostgreSQL, and two AgentCore runtimes',
  env: { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION || 'us-east-1' },
})
Tags.of(stack).add('Project', 'agent-marketplace')
const root = path.resolve(__dirname, '..')
const paymentManager = new CfnParameter(stack, 'PaymentManagerArn', {
  type: 'String', description: 'An existing AgentCore PaymentManager with an active wallet connector',
})
const paymentConnector = new CfnParameter(stack, 'PaymentConnectorId', {
  type: 'String', default: '', description: 'Existing Stripe/Privy connector ID; discovered from the instrument when omitted',
})
const paymentInstrument = new CfnParameter(stack, 'PaymentInstrumentId', {
  type: 'String', default: '', description: 'Existing AgentCore Stripe/Privy instrument; empty keeps payments disabled',
})
const paymentUser = new CfnParameter(stack, 'PaymentUserId', {
  type: 'String', default: '', description: 'Existing AgentCore payment userId associated with this instrument',
})
const paymentOwner = new CfnParameter(stack, 'PaymentOwnerSub', {
  type: 'String', default: '', description: 'Cognito subject allowed to use the existing wallet; empty disables binding',
})
const paymentDelegate = new CfnParameter(stack, 'PaymentDelegateSub', {
  type: 'String', default: '', description: 'Optional Cognito subject explicitly allowed to pay from the shared test wallet',
})
const paymentDelegateLimit = new CfnParameter(stack, 'PaymentDelegateLimitMicros', {
  type: 'Number', default: 1000000, minValue: 0,
  description: 'Total delegated spending cap in USDC micro-units (1000000 = 1 test USDC), including reservations',
})
const showcaseUser = new CfnParameter(stack, 'ShowcaseUserSub', {
  type: 'String', default: '', description: 'Cognito subject allowed to read the selected shared test records',
})
const showcaseTasks = new CfnParameter(stack, 'ShowcaseTaskIds', {
  type: 'String', default: '', description: 'Comma-separated task IDs shared read-only with the demo account',
})
const showcaseAgents = new CfnParameter(stack, 'ShowcaseAgentIds', {
  type: 'String', default: '', description: 'Comma-separated agent IDs shown as shared demo profiles in My agents',
})
const privyWalletUrl = new CfnParameter(stack, 'PrivyWalletUrl', {
  type: 'String', default: '', description: 'Optional HTTPS URL of your existing Privy wallet management frontend',
})
const facilitator = new CfnParameter(stack, 'FacilitatorUrl', {
  type: 'String', default: 'https://x402.org/facilitator',
  allowedPattern: 'https://.+', description: 'An x402 v2 facilitator supporting Base Sepolia',
})
const modelId = new CfnParameter(stack, 'BedrockModelId', {
  type: 'String', default: 'us.amazon.nova-pro-v1:0',
})

const vpc = new ec2.Vpc(stack, 'Vpc', {
  maxAzs: 2, natGateways: 1,
  subnetConfiguration: [
    { name: 'Public', subnetType: ec2.SubnetType.PUBLIC, cidrMask: 24 },
    { name: 'Application', subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS, cidrMask: 24 },
    { name: 'Database', subnetType: ec2.SubnetType.PRIVATE_ISOLATED, cidrMask: 24 },
  ],
})
const appSg = new ec2.SecurityGroup(stack, 'ApplicationSecurityGroup', { vpc, allowAllOutbound: true })
const runtimeSg = new ec2.SecurityGroup(stack, 'RuntimeSecurityGroup', { vpc, allowAllOutbound: true })
const database = new rds.DatabaseInstance(stack, 'Database', {
  vpc, vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
  engine: rds.DatabaseInstanceEngine.postgres({ version: rds.PostgresEngineVersion.of('16.15', '16') }),
  instanceType: ec2.InstanceType.of(ec2.InstanceClass.T4G, ec2.InstanceSize.MICRO),
  databaseName: 'marketplace', credentials: rds.Credentials.fromGeneratedSecret('marketplace'),
  allocatedStorage: 20, maxAllocatedStorage: 100, storageEncrypted: true,
  backupRetention: Duration.days(7), deletionProtection: true,
  publiclyAccessible: false, removalPolicy: RemovalPolicy.SNAPSHOT,
})
database.connections.allowDefaultPortFrom(appSg, 'API access')
database.connections.allowDefaultPortFrom(runtimeSg, 'Orchestrator access')

const runtimeImage = new assets.DockerImageAsset(stack, 'RuntimeImage', {
  directory: path.join(root, 'backend'), file: 'Dockerfile.runtime', platform: assets.Platform.LINUX_ARM64,
})
function runtimeRole(name: string) {
  const role = new iam.Role(stack, name, {
    assumedBy: new iam.ServicePrincipal('bedrock-agentcore.amazonaws.com', {
      conditions: { StringEquals: { 'aws:SourceAccount': stack.account } },
    }),
  })
  runtimeImage.repository.grantPull(role)
  role.addToPolicy(new iam.PolicyStatement({
    actions: ['logs:CreateLogGroup', 'logs:CreateLogStream', 'logs:PutLogEvents', 'logs:DescribeLogStreams'],
    resources: [stack.formatArn({ service: 'logs', resource: 'log-group', resourceName: '/aws/bedrock-agentcore/*' })],
  }))
  role.addToPolicy(new iam.PolicyStatement({
    actions: ['logs:DescribeLogGroups', 'xray:PutTraceSegments', 'xray:PutTelemetryRecords'], resources: ['*'],
  }))
  return role
}
const bidderRole = runtimeRole('BidderExecutionRole')
bidderRole.addToPolicy(new iam.PolicyStatement({
  actions: ['bedrock:InvokeModel'],
  resources: [
    stack.formatArn({ service: 'bedrock', resource: 'inference-profile', resourceName: '*' }),
    `arn:${stack.partition}:bedrock:*::foundation-model/*`,
  ],
}))
const bidders = new agentcore.CfnRuntime(stack, 'BidderRuntime', {
  agentRuntimeName: 'marketplace_bidders',
  description: 'Shared specialist profiles: self-evaluation and Bedrock-powered delivery',
  agentRuntimeArtifact: { containerConfiguration: { containerUri: runtimeImage.imageUri } },
  roleArn: bidderRole.roleArn, networkConfiguration: { networkMode: 'PUBLIC' }, protocolConfiguration: 'HTTP',
  environmentVariables: {
    APP_MODE: 'aws', RUNTIME_ROLE: 'bidders', AWS_REGION: stack.region, BEDROCK_MODEL_ID: modelId.valueAsString,
  },
})
bidders.node.addDependency(bidderRole)
const orchestratorRole = runtimeRole('OrchestratorExecutionRole')
database.secret!.grantRead(orchestratorRole)
orchestratorRole.addToPolicy(new iam.PolicyStatement({
  actions: ['bedrock-agentcore:InvokeAgentRuntime'], resources: [bidders.attrAgentRuntimeArn, `${bidders.attrAgentRuntimeArn}/*`],
}))
orchestratorRole.addToPolicy(new iam.PolicyStatement({
  actions: ['bedrock-agentcore:CreatePaymentSession', 'bedrock-agentcore:ProcessPayment'],
  resources: [paymentManager.valueAsString],
}))
orchestratorRole.addToPolicy(new iam.PolicyStatement({
  actions: [
    'ec2:CreateNetworkInterface', 'ec2:DeleteNetworkInterface', 'ec2:DescribeNetworkInterfaces',
    'ec2:DescribeSubnets', 'ec2:DescribeSecurityGroups', 'ec2:DescribeVpcs',
    'ec2:CreateNetworkInterfacePermission', 'ec2:DeleteNetworkInterfacePermission',
  ], resources: ['*'],
}))
const orchestrator = new agentcore.CfnRuntime(stack, 'OrchestratorRuntime', {
  agentRuntimeName: 'marketplace_orchestrator',
  description: 'Task orchestration, budget-controlled payments, delivery, and verified reputation',
  agentRuntimeArtifact: { containerConfiguration: { containerUri: runtimeImage.imageUri } },
  roleArn: orchestratorRole.roleArn, protocolConfiguration: 'HTTP',
  networkConfiguration: {
    networkMode: 'VPC', networkModeConfig: {
      subnets: vpc.privateSubnets.map(s => s.subnetId), securityGroups: [runtimeSg.securityGroupId],
    },
  },
  environmentVariables: {
    APP_MODE: 'aws', RUNTIME_ROLE: 'orchestrator', AWS_REGION: stack.region,
    DATABASE_SECRET_ARN: database.secret!.secretArn,
    BIDDER_RUNTIME_ARN: bidders.attrAgentRuntimeArn,
    PAYMENT_MANAGER_ARN: paymentManager.valueAsString,
    PAYMENT_CONNECTOR_ID: paymentConnector.valueAsString,
    PAYMENT_INSTRUMENT_ID: paymentInstrument.valueAsString,
    PAYMENT_USER_ID: paymentUser.valueAsString,
    PAYMENT_OWNER_SUB: paymentOwner.valueAsString,
    PAYMENT_DELEGATE_SUB: paymentDelegate.valueAsString,
    PAYMENT_DELEGATE_LIMIT_MICROS: paymentDelegateLimit.valueAsString,
    FACILITATOR_URL: facilitator.valueAsString,
  },
})
orchestrator.node.addDependency(orchestratorRole)

const bucket = new s3.Bucket(stack, 'WebAssets', {
  blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL, enforceSSL: true,
  encryption: s3.BucketEncryption.S3_MANAGED, versioned: true, removalPolicy: RemovalPolicy.RETAIN,
})
const albSg = new ec2.SecurityGroup(stack, 'LoadBalancerSecurityGroup', { vpc })
// CloudFront VPC origins reach this internal ALB through private VPC ENIs.
const cloudfrontPrefixList = ec2.PrefixList.fromLookup(stack, 'CloudFrontOriginPrefixList', {
  prefixListName: 'com.amazonaws.global.cloudfront.origin-facing',
})
albSg.addIngressRule(ec2.Peer.prefixList(cloudfrontPrefixList.prefixListId), ec2.Port.tcp(80), 'CloudFront VPC origin')
const alb = new elb.ApplicationLoadBalancer(stack, 'ApiLoadBalancer', {
  vpc, internetFacing: false, securityGroup: albSg,
  vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS },
})
alb.setAttribute('idle_timeout.timeout_seconds', '240')
const listener = alb.addListener('Http', { port: 80, open: false })
// Associated VPC origins cannot be updated in place; keep endpoint configuration explicit.
const apiVpcOrigin = new cloudfront.VpcOrigin(stack, 'ApiHttpOrigin', {
  endpoint: cloudfront.VpcOriginEndpoint.applicationLoadBalancer(alb),
  protocolPolicy: cloudfront.OriginProtocolPolicy.HTTP_ONLY,
  httpPort: 80,
})
apiVpcOrigin.node.addDependency(listener)
const apiOrigin = origins.VpcOrigin.withVpcOrigin(apiVpcOrigin, {
  readTimeout: Duration.seconds(120),
})
const spaRouting = new cloudfront.Function(stack, 'FrontendRouting', {
  runtime: cloudfront.FunctionRuntime.JS_2_0,
  code: cloudfront.FunctionCode.fromInline(
    "function handler(event) { var request = event.request; if (request.uri === '/login' || request.uri === '/login/') { request.uri = '/index.html'; } return request; }",
  ),
})
const distribution = new cloudfront.Distribution(stack, 'WebDistribution', {
  defaultRootObject: 'index.html',
  defaultBehavior: {
    origin: origins.S3BucketOrigin.withOriginAccessControl(bucket),
    viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
    responseHeadersPolicy: cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
    functionAssociations: [{ eventType: cloudfront.FunctionEventType.VIEWER_REQUEST, function: spaRouting }],
  },
  additionalBehaviors: {
    'api/*': {
      origin: apiOrigin, allowedMethods: cloudfront.AllowedMethods.ALLOW_ALL,
      cachePolicy: cloudfront.CachePolicy.CACHING_DISABLED,
      originRequestPolicy: cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
      viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.HTTPS_ONLY,
      responseHeadersPolicy: cloudfront.ResponseHeadersPolicy.SECURITY_HEADERS,
    },
  },
  priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
})
distribution.node.addDependency(listener)
const siteUrl = `https://${distribution.distributionDomainName}`
const userPool = new cognito.UserPool(stack, 'Users', {
  selfSignUpEnabled: false, signInAliases: { email: true },
  autoVerify: { email: true },
  standardAttributes: { email: { required: true, mutable: false } },
  passwordPolicy: { minLength: 12, requireDigits: true, requireSymbols: true, requireUppercase: true, requireLowercase: true },
  removalPolicy: RemovalPolicy.RETAIN,
})
const domain = userPool.addDomain('HostedLogin', {
  cognitoDomain: { domainPrefix: `agent-market-${stack.account}-${stack.region}` },
})
const userClient = userPool.addClient('WebClient', {
  generateSecret: false, preventUserExistenceErrors: true,
  authFlows: { userPassword: true, userSrp: true },
  accessTokenValidity: Duration.hours(1),
  oAuth: {
    flows: { authorizationCodeGrant: true }, scopes: [cognito.OAuthScope.OPENID, cognito.OAuthScope.EMAIL, cognito.OAuthScope.PROFILE],
    callbackUrls: [`${siteUrl}/`], logoutUrls: [`${siteUrl}/`],
  },
})
const cluster = new ecs.Cluster(stack, 'ApiCluster', { vpc })
const task = new ecs.FargateTaskDefinition(stack, 'ApiTask', {
  cpu: 512, memoryLimitMiB: 1024,
  runtimePlatform: { cpuArchitecture: ecs.CpuArchitecture.ARM64, operatingSystemFamily: ecs.OperatingSystemFamily.LINUX },
})
database.secret!.grantRead(task.taskRole)
task.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
  actions: ['bedrock-agentcore:InvokeAgentRuntime'],
  resources: [orchestrator.attrAgentRuntimeArn, `${orchestrator.attrAgentRuntimeArn}/*`],
}))
task.taskRole.addToPrincipalPolicy(new iam.PolicyStatement({
  actions: [
    'bedrock-agentcore:GetPaymentInstrument', 'bedrock-agentcore:GetPaymentInstrumentBalance',
    'bedrock-agentcore:GetPaymentConnector',
  ], resources: [paymentManager.valueAsString, `${paymentManager.valueAsString}/*`],
}))
const container = task.addContainer('api', {
  image: ecs.ContainerImage.fromAsset(path.join(root, 'backend'), { platform: assets.Platform.LINUX_ARM64 }),
  logging: ecs.LogDrivers.awsLogs({ streamPrefix: 'marketplace-api', logRetention: logs.RetentionDays.ONE_MONTH }),
  environment: {
    APP_MODE: 'aws', AWS_REGION: stack.region, DATABASE_SECRET_ARN: database.secret!.secretArn,
    ORCHESTRATOR_RUNTIME_ARN: orchestrator.attrAgentRuntimeArn,
    COGNITO_ISSUER: `https://cognito-idp.${stack.region}.amazonaws.com/${userPool.userPoolId}`,
    COGNITO_CLIENT_ID: userClient.userPoolClientId, COGNITO_DOMAIN: domain.baseUrl(),
    CORS_ORIGINS: siteUrl, PAYMENT_MANAGER_ARN: paymentManager.valueAsString,
    PAYMENT_CONNECTOR_ID: paymentConnector.valueAsString,
    PAYMENT_INSTRUMENT_ID: paymentInstrument.valueAsString,
    PAYMENT_USER_ID: paymentUser.valueAsString,
    PAYMENT_OWNER_SUB: paymentOwner.valueAsString,
    PAYMENT_DELEGATE_SUB: paymentDelegate.valueAsString,
    PAYMENT_DELEGATE_LIMIT_MICROS: paymentDelegateLimit.valueAsString,
    PRIVY_WALLET_URL: privyWalletUrl.valueAsString,
    SHOWCASE_USER_SUB: showcaseUser.valueAsString,
    SHOWCASE_TASK_IDS: showcaseTasks.valueAsString,
    SHOWCASE_AGENT_IDS: showcaseAgents.valueAsString,
  },
})
container.addPortMappings({ containerPort: 8000 })
const service = new ecs.FargateService(stack, 'ApiService', {
  cluster, taskDefinition: task, desiredCount: 1, securityGroups: [appSg],
  vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_WITH_EGRESS }, assignPublicIp: false,
  circuitBreaker: { rollback: true }, healthCheckGracePeriod: Duration.seconds(90),
  minHealthyPercent: 100,
})
service.node.addDependency(database)
listener.addTargets('ApiTargets', {
  port: 8000, protocol: elb.ApplicationProtocol.HTTP, targets: [service],
  healthCheck: { path: '/api/health', healthyHttpCodes: '200', interval: Duration.seconds(30) },
  deregistrationDelay: Duration.seconds(30),
})
new deployment.BucketDeployment(stack, 'DeployWeb', {
  sources: [deployment.Source.asset(path.join(root, 'frontend/dist'))],
  destinationBucket: bucket, distribution, distributionPaths: ['/*'],
})

for (const [name, value] of Object.entries({
  WebsiteUrl: siteUrl, OrchestratorRuntimeArn: orchestrator.attrAgentRuntimeArn,
  BidderRuntimeArn: bidders.attrAgentRuntimeArn, DatabaseSecretArn: database.secret!.secretArn,
  MigrationCluster: cluster.clusterArn, MigrationTaskDefinition: task.taskDefinitionArn,
  MigrationSubnet: vpc.privateSubnets[0].subnetId, MigrationSecurityGroup: appSg.securityGroupId,
  FrontendBucket: bucket.bucketName, CloudFrontDistributionId: distribution.distributionId,
  UserPoolId: userPool.userPoolId, UserPoolClientId: userClient.userPoolClientId,
  ApiServiceName: service.serviceName, LoginUrl: `${siteUrl}/login`,
})) new CfnOutput(stack, name, { value })
