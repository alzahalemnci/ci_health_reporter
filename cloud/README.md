# CI Health Reporter — Cloud Backend

A minimal AWS serverless backend that receives health reports from one or more Home Assistant instances, stores them, and replies `{"status": "ok"}`.

## Architecture

```
Home Assistant  →  API Gateway  →  Lambda  →  S3
  (client)          (HTTPS URL)    (store)    (JSON files)
```

## Prerequisites

- AWS account with an IAM user configured for CLI access
- AWS CLI installed and configured (`aws configure`)
- SAM CLI installed (`uv tool install aws-sam-cli`)

## Deploy

```bash
cd cloud
sam build && sam deploy --guided
```

`--guided` walks you through the setup interactively. When prompted:

| Prompt | Value |
|---|---|
| Stack Name | anything you like, e.g. `ci-health-reporter` |
| AWS Region | your preferred region, e.g. `us-east-1` |
| Confirm changes before deploy | `y` |
| Allow SAM CLI IAM role creation | `y` |
| HealthFunction may not have auth defined... | `y` |
| Save arguments to config file | `y` |

At the end, copy the `HealthApiUrl` from the Outputs section — that is your `server_url`.

## Configure Home Assistant

In your HA `configuration.yaml`:

```yaml
ci_health_reporter:
  server_url: "https://<your-api-gateway-url>/Prod"
  interval: 60
```

No `server_port` needed — HTTPS uses the standard port 443.

## View stored reports

Open the AWS Console → S3 → your bucket. Each incoming report is saved as a separate JSON file named `{timestamp}-{uuid}.json`.

## Tear down

To stop the endpoint and pause all charges:

```bash
aws cloudformation delete-stack --stack-name ci-health-reporter
```

Your S3 bucket and data are preserved. Redeploy any time with `sam deploy`.

## Redeploy after changes

```bash
cd cloud
sam build && sam deploy
```

No `--guided` needed after the first deployment — settings are saved in `samconfig.toml`.
