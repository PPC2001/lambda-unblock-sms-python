# OTD Loyalty Lambda — Auth0 SMS Unblocker (Python)

## Overview

This is an AWS Lambda function written in Python that **automatically unblocks users in Auth0** when their blocked record expires via DynamoDB TTL (Time-To-Live).

### How It Works

1. **Another service** (the Auth0 webhook) writes a record to the DynamoDB table `otd-loyalty-provider-auth0-webhook` when a user is blocked in Auth0.
2. The record has an `unBlockedAt` field set to a **Unix timestamp** in the future (when the block should expire).
3. **AWS DynamoDB TTL** automatically deletes the record when that timestamp is reached.
4. Deleting the record emits a `REMOVE` event on the **DynamoDB Stream**.
5. **This Lambda** is triggered by that stream event and calls the **Auth0 Management API** to unblock the user.
6. If the Auth0 call fails, the Lambda **re-inserts the record** with a new TTL using exponential backoff (5 retries max).

```
DynamoDB TTL expires record
        │
        ▼
DynamoDB Stream (REMOVE event)
        │
        ▼
This Lambda Function
        │
        ▼
Auth0 Management API → Unblock user
```

---

## Project Structure

```
otd-loyalty-lambda-python/
├── unblock_auth0_sms/          # Lambda function package
│   ├── app.py                  # Lambda handler (entry point)
│   ├── auth0.py                # Auth0 API client + configuration
│   ├── dynamodb.py             # DynamoDB retry logic (exponential backoff)
│   ├── requirements.txt        # Python dependencies
│   └── __init__.py
├── events/
│   └── event.json              # Sample DynamoDB REMOVE event for local testing
├── template.yaml               # AWS SAM infrastructure definition
├── samconfig.toml              # SAM deploy configuration (auto-generated)
├── env.json                    # Local test environment variables (DO NOT COMMIT)
├── .env                        # Local environment variables (DO NOT COMMIT)
└── .gitignore
```

---

## Prerequisites

Before you begin, make sure you have the following installed:

| Tool | Purpose | Install |
|---|---|---|
| **Python 3.11** | Runtime environment for the Lambda | `sudo apt install python3.11` (WSL/Ubuntu) |
| **Pip** | Python package installer | `sudo apt install python3-pip` (WSL/Ubuntu) |
| **AWS CLI** | Interact with AWS from terminal | [Install guide](https://aws.amazon.com/cli/) |
| **AWS SAM CLI** | Build and deploy Lambda functions | `pipx install aws-sam-cli` |
| **Docker Desktop** | Required by SAM to build in a container | [Install guide](https://www.docker.com/products/docker-desktop/) |
| **WSL (Ubuntu)** | Linux terminal on Windows | `wsl --install` in PowerShell |

---

## AWS Setup (One-Time)

### Step 1: Configure AWS Credentials

You need an AWS IAM user with the right permissions. Ask your AWS administrator for:
- `AWS Access Key ID`
- `AWS Secret Access Key`

Then configure the AWS CLI in your WSL terminal:

```bash
aws configure
```

Enter the following when prompted:
```
AWS Access Key ID:     <your-access-key-id>
AWS Secret Access Key: <your-secret-access-key>
Default region name:   ap-south-1
Default output format: json
```

Verify it works:
```bash
aws sts get-caller-identity
```
You should see your AWS account ID, user ID, and ARN.

---

### Step 2: Enable DynamoDB Streams on the Existing Table

> ⚠️ This step is only needed if you're using a pre-existing DynamoDB table. Skip if the table was created fresh by SAM.

The Lambda needs DynamoDB Streams enabled with `NEW_AND_OLD_IMAGES` so it receives the deleted item's data when TTL removes it.

```bash
aws dynamodb update-table \
  --table-name otd-loyalty-provider-auth0-webhook \
  --stream-specification StreamEnabled=true,StreamViewType=NEW_AND_OLD_IMAGES \
  --region ap-south-1
```

Get the Stream ARN (you will need this for `template.yaml`):
```bash
aws dynamodb describe-table \
  --table-name otd-loyalty-provider-auth0-webhook \
  --region ap-south-1 \
  --query "Table.LatestStreamArn" \
  --output text
```

---

### Step 3: Enable DynamoDB TTL on the Table

TTL is the trigger for this entire flow. Make sure it is enabled on the `unBlockedAt` attribute:

```bash
aws dynamodb update-time-to-live \
  --table-name otd-loyalty-provider-auth0-webhook \
  --time-to-live-specification "Enabled=true,AttributeName=unBlockedAt" \
  --region ap-south-1
```

Verify TTL is enabled:
```bash
aws dynamodb describe-time-to-live \
  --table-name otd-loyalty-provider-auth0-webhook \
  --region ap-south-1
```

Expected output:
```json
{
    "TimeToLiveDescription": {
        "TimeToLiveStatus": "ENABLED",
        "AttributeName": "unBlockedAt"
    }
}
```

---

## Secrets Management — AWS SSM Parameter Store

This project stores Auth0 credentials in **AWS SSM Parameter Store** instead of hardcoding them in `template.yaml` or committing them to Git.

### Why SSM?
- ✅ Secrets are **never in your source code or Git history**
- ✅ Values are managed centrally in AWS — easy to rotate without redeploying code
- ✅ Access is controlled via **IAM policies**
- ✅ Free for Standard tier parameters

### Create the SSM Parameters (One-Time Setup)

Run these commands in your WSL terminal to store your Auth0 credentials in SSM:

```bash
aws ssm put-parameter \
  --name "/otd-loyalty/AUTH0_DOMAIN" \
  --value "your-auth0-tenant.us.auth0.com" \
  --type "String" \
  --region ap-south-1

aws ssm put-parameter \
  --name "/otd-loyalty/AUTH0_CLIENT_ID" \
  --value "your-auth0-client-id" \
  --type "String" \
  --region ap-south-1

aws ssm put-parameter \
  --name "/otd-loyalty/AUTH0_CLIENT_SECRET" \
  --value "your-auth0-client-secret" \
  --type "String" \
  --region ap-south-1
```

Each command should return:
```json
{ "Version": 1, "Tier": "Standard" }
```

Verify the parameters were created:
```bash
aws ssm get-parameters-by-path --path "/otd-loyalty" --region ap-south-1
```

### Updating a Secret

If you need to rotate or update a credential, use the `--overwrite` flag:
```bash
aws ssm put-parameter \
  --name "/otd-loyalty/AUTH0_CLIENT_SECRET" \
  --value "your-new-secret" \
  --type "String" \
  --overwrite \
  --region ap-south-1
```
Then redeploy (`sam build --use-container && sam deploy`) for the Lambda to pick up the new value.

> 🔒 **Never commit `.env` or `env.json` to Git!** They are for local testing only.

---

## Local Testing with SAM CLI

### Step 1: Build the Lambda

SAM builds your function inside an official AWS Lambda Docker container to ensure dependency compatibility.

```bash
sam build --use-container
```

> **First run takes a few minutes** — it downloads the Python 3.11 Lambda Docker image (~1GB). Subsequent builds are cached and much faster.

### Step 2: Create `env.json` for Local Invocation

SAM `local invoke` does not read `.env` files. Create `env.json` in the project root:

```json
{
    "StreamProcessorFunction": {
        "AUTH0_DOMAIN": "your-tenant.us.auth0.com",
        "AUTH0_CLIENT_ID": "your-auth0-client-id",
        "AUTH0_CLIENT_SECRET": "your-auth0-client-secret",
        "TABLE_NAME": "otd-loyalty-provider-auth0-webhook"
    }
}
```

### Step 3: Invoke the Lambda Locally

```bash
sam local invoke StreamProcessorFunction -e events/event.json --env-vars env.json
```

**Expected output:**
```
START RequestId: ...
[INFO] Received 1 stream records
[INFO] Processing TTL unblock for phone: +15551234567, attempt: 0
[INFO] Successfully unblocked +15551234567
END RequestId: ...
REPORT Duration: ... ms  Memory Size: 256 MB
```

> ℹ️ The `LAMBDA_RUNTIME Failed to get next invocation` message at the end is **normal** — it just means the one-shot local container shut down after processing.

---

## Deploying to AWS

### Step 1: Ensure SSM Parameters Exist

Before deploying, confirm all 3 SSM parameters are in place (see **Secrets Management** section above). The `template.yaml` references them via:

```yaml
AUTH0_DOMAIN: '{{resolve:ssm:/otd-loyalty/AUTH0_DOMAIN}}'
AUTH0_CLIENT_ID: '{{resolve:ssm:/otd-loyalty/AUTH0_CLIENT_ID}}'
AUTH0_CLIENT_SECRET: '{{resolve:ssm:/otd-loyalty/AUTH0_CLIENT_SECRET}}'
```

If these parameters don't exist in SSM, CloudFormation **will fail** during deployment.

### Step 2: Update the Stream ARN in `template.yaml`

Open `template.yaml` and make sure the `Stream:` property under `Events.DynamoDBStream.Properties` has the real ARN from **Step 2 of AWS Setup**. It should look like:

```yaml
Stream: "arn:aws:dynamodb:ap-south-1:XXXXXXXXXXXX:table/otd-loyalty-provider-auth0-webhook/stream/YYYY-MM-DDTHH:MM:SS.000"
```

### Step 3: Build and Deploy

```bash
sam build --use-container && sam deploy --guided
```

Answer the guided prompts:

| Prompt | Answer |
|---|---|
| `Stack Name` | `otd-loyalty-lambda-python` |
| `AWS Region` | `ap-south-1` |
| `Confirm changes before deploy` | `y` |
| `Allow SAM CLI IAM role creation` | press Enter |
| `Disable rollback` | `y` |
| `Save arguments to configuration file` | press Enter |
| `SAM configuration file [samconfig.toml]` | ⚠️ **press Enter** (don't type Y!) |
| `SAM configuration environment [default]` | press Enter |

After the changeset preview, type `y` to confirm and deploy.

### Step 3: Verify Deployment

After a successful deploy, verify the Lambda is live:

```bash
aws lambda get-function --function-name otd-loyalty-lambda-python-StreamProcessorFunction --region ap-south-1
```

View live logs in CloudWatch:
```bash
aws logs tail /aws/lambda/otd-loyalty-lambda-python-StreamProcessorFunction --follow --region ap-south-1
```

---

## Re-deploying After Code Changes

For subsequent deployments after the first setup, simply run:

```bash
sam build --use-container && sam deploy
```

No need for `--guided` again — `samconfig.toml` remembers your settings.

---

## Retry Logic

If the Auth0 API call fails (network error, rate limit, etc.), the Lambda automatically re-queues the phone number back into DynamoDB with a new TTL using **exponential backoff**:

| Attempt | Delay before retry |
|---|---|
| 1st retry | 5 minutes (60 × 5¹) |
| 2nd retry | 25 minutes (60 × 5²) |
| 3rd retry | ~2 hours (60 × 5³) |
| 4th retry | ~10 hours (60 × 5⁴) |
| 5th retry | Abandoned — logs a warning |

After 5 failed attempts, the record is dropped and a warning is logged in CloudWatch. Consider setting up a CloudWatch alarm on error logs to get notified via SNS/Slack.

---

## Troubleshooting

| Error | Cause | Fix |
|---|---|---|
| `Parameters: [ssm:AUTH0_...] cannot be found` | SSM parameters not created yet | Run the `aws ssm put-parameter` commands from the **Secrets Management** section |
| `Non-secure ssm prefix was used for secure parameter` | SSM param was created as `SecureString` but template uses `ssm:` prefix | Recreate the parameter with `--type String --overwrite` |
| `SSM Secure reference is not supported` | Template uses `ssm-secure:` prefix for Lambda env vars | Change to `ssm:` prefix in `template.yaml` — Lambda env vars don't support `ssm-secure` |
| `EarlyValidation::ResourceExistenceCheck` | DynamoDB stream ARN in template is wrong or streams not enabled | Run `aws dynamodb update-table` to enable streams, then get the new ARN |
| `Binary validation failed for python` | Python 3.11 not installed locally | Use `sam build --use-container` instead |
| `FileNotFoundError` in SAM CLI | WSL path issue with `os.getcwd()` | Run `cd /your/project/path && sam build` |
| `Build Succeeded` but deploy uses old template | SAM cached the old `.aws-sam/build/` | Always run `sam build` before `sam deploy` |
