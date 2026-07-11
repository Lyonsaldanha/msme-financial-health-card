#!/usr/bin/env bash
# Deploys the MSME Financial Health Card to AWS App Runner using SQLite instead
# of RDS -- no separate database service, mirroring deploy-cloud-run.sh's
# Cloud Run approach. Safe to re-run.
#
# Deviations / judgment calls, and why:
#
# 1. **App Runner, not ECS/Fargate/Elastic Beanstalk/EC2.** It's the closest
#    AWS analog to Cloud Run: point it at a container image, get a managed
#    HTTPS URL, no load balancer/VPC/task-definition wiring to hand-build.
# 2. **SQLite baked into the image, pre-built locally before push** -- same
#    reasoning as deploy-cloud-run.sh: App Runner's container filesystem is
#    ephemeral across deployments, so data written at runtime doesn't
#    persist across a redeploy. This script runs the ETL/Analytics/AI
#    engines locally against a SQLite file *before* the image is built, so
#    the image ships with all customers' scorecards/reports pre-generated.
# 3. **Image pushed to a private ECR repo, built with plain `docker build` +
#    `docker push`** (not a remote build service). Unlike the Cloud Shell
#    Docker-daemon-can't-reach-Artifact-Registry problem hit earlier on GCP,
#    ECR auth via `aws ecr get-login-password | docker login` is a standard,
#    well-supported path from most environments (local machine or AWS
#    CloudShell, which ships Docker preinstalled). If you hit the same class
#    of docker-push networking failure here, the fix is the GCP script's
#    fix too: use a remote build service (AWS CodeBuild) instead of a local
#    docker daemon -- not implemented here since ECR pushes are the common
#    case that works.
# 4. **GEMINI_API_KEY goes into AWS Secrets Manager**, not a plaintext
#    runtime environment variable -- an App Runner "instance role" is
#    granted read access to that one secret, analogous to Cloud Run's
#    service account + Secret Manager binding.
# 5. **Region defaults to ap-south-1 (Mumbai)**, matching this project's
#    earlier deliberate choice on GCP (judge/demo latency from India). I
#    could not confirm from here whether App Runner is enabled in your
#    specific AWS account/region combination -- if `aws apprunner
#    create-service` fails with a region/availability error, override via
#    `REGION=us-east-1 bash deploy-aws-apprunner.sh` (App Runner has been
#    available there the longest) and re-run.
# 6. **Instance size defaults to 1 vCPU / 2 GB**, not App Runner's smallest
#    tier (0.25 vCPU / 0.5 GB). This app loads pandas/numpy/matplotlib/
#    reportlab in-process per Streamlit session; 0.5 GB risks an OOM kill
#    under that stack. 2 GB is the smallest tier App Runner offers above
#    1 GB for a 1 vCPU task.
# 7. **App Runner does NOT scale to zero** (unlike Cloud Run) -- it bills
#    continuously while the service exists and is running, even fully idle.
#    This is a real cost difference from the GCP deployment, not just a
#    config detail: on a small fixed credit, pause or delete the service
#    promptly after demoing (see the cleanup commands printed at the end).
#
# None of this is exotic -- it's the same script, done without the parts
# that would silently produce a broken, insecure, or unexpectedly billed
# deployment.

set -euo pipefail

# ---- Configuration (override via env vars) ---------------------------------
REGION="${REGION:-ap-south-1}"                  # Mumbai -- see deviation #5 above; override if unavailable
APP_NAME="${APP_NAME:-msme-fhc}"
ECR_REPO="${APP_NAME}-repo"
ACCESS_ROLE_NAME="${APP_NAME}-apprunner-ecr-access"
INSTANCE_ROLE_NAME="${APP_NAME}-apprunner-instance"
SECRET_NAME="${APP_NAME}-gemini-key"
SQLITE_FILE="msme_fhc.db"                       # baked into the image at this path, relative to the Dockerfile's WORKDIR /app
GEMINI_API_KEY="${GEMINI_API_KEY:-demo-key}"    # falls back to the AI Engine's deterministic template narrative if unset/invalid
GEMINI_MODEL="${GEMINI_MODEL:-gemini-flash-lite-latest}"  # cheapest current model; export GEMINI_MODEL to override
CPU="${CPU:-1 vCPU}"                            # see deviation #6 above
MEMORY="${MEMORY:-2 GB}"
OUTPUT_FILE="apprunner-url.txt"

TOTAL_STEPS=6
step() { echo; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; echo "[$1/${TOTAL_STEPS}] $2"; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; }
ok()   { echo "✅ $1"; }
info() { echo "⏳ $1"; }
warn() { echo "⚠️  $1"; }
die()  { echo "❌ $1" >&2; exit 1; }

# ---- Dependency checks -------------------------------------------------------
command -v aws    >/dev/null 2>&1 || die "aws CLI not found. Install: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html"
command -v docker >/dev/null 2>&1 || die "docker not found (needed to build+push the image to ECR)."
command -v uv     >/dev/null 2>&1 || die "uv not found (needed for the local pre-build step). Install: https://docs.astral.sh/uv/"
aws sts get-caller-identity >/dev/null 2>&1 \
    || die "No valid AWS credentials found. Run: aws configure  (or set AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY)"
[ -f Dockerfile ] || die "Dockerfile not found in $(pwd). Run this script from the project root."

ACCOUNT_ID="$(aws sts get-caller-identity --query Account --output text)"
ECR_URI="${ACCOUNT_ID}.dkr.ecr.${REGION}.amazonaws.com"
IMAGE="${ECR_URI}/${ECR_REPO}:latest"

# ---- Step 1: ECR repository ---------------------------------------------------
step 1 "ECR repository setup"

if aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$REGION" >/dev/null 2>&1; then
    ok "ECR repo $ECR_REPO already exists"
else
    info "Creating ECR repo $ECR_REPO..."
    aws ecr create-repository --repository-name "$ECR_REPO" --region "$REGION" --image-scanning-configuration scanOnPush=true --quiet >/dev/null
    ok "ECR repo created"
fi

# ---- Step 2: Pre-build the SQLite database locally ---------------------------
step 2 "Pre-build local database (baked into the image -- see deviation #2 above)"

rm -f "$SQLITE_FILE"
info "Running ETL Engine..."
DB_ENGINE=sqlite SQLITE_PATH="$SQLITE_FILE" uv run python etl_engine.py
info "Running Analytics Engine..."
DB_ENGINE=sqlite SQLITE_PATH="$SQLITE_FILE" uv run python analytics_engine.py
info "Running AI Engine (model: $GEMINI_MODEL; uses GEMINI_API_KEY if set and valid, else the deterministic fallback narrative)..."
DB_ENGINE=sqlite SQLITE_PATH="$SQLITE_FILE" GEMINI_API_KEY="$GEMINI_API_KEY" GEMINI_MODEL="$GEMINI_MODEL" uv run python ai_engine.py
[ -f "$SQLITE_FILE" ] || die "Pre-build did not produce $SQLITE_FILE -- check the errors above."
ok "Local database populated ($SQLITE_FILE)"

# ---- Step 3: Build and push to ECR --------------------------------------------
step 3 "Build and push image to ECR (see deviation #3 above)"

info "Authenticating docker to $ECR_URI..."
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$ECR_URI" \
    || die "docker login to ECR failed -- check your AWS credentials/region."

info "Building image (includes $SQLITE_FILE via the Dockerfile's COPY . . step)..."
docker build -t "$IMAGE" . \
    || die "docker build failed -- see errors above."

info "Pushing $IMAGE..."
docker push "$IMAGE" \
    || die "docker push failed -- if this is a networking error from a cloud shell environment, see deviation #3 above (switch to a remote build service instead of a local docker daemon)."
ok "Image built and pushed"

# ---- Step 4: IAM roles + secret ------------------------------------------------
step 4 "IAM roles and secrets"

ACCESS_ROLE_TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"build.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
INSTANCE_ROLE_TRUST='{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"tasks.apprunner.amazonaws.com"},"Action":"sts:AssumeRole"}]}'

if aws iam get-role --role-name "$ACCESS_ROLE_NAME" >/dev/null 2>&1; then
    ok "Access role $ACCESS_ROLE_NAME already exists"
else
    info "Creating App Runner ECR access role..."
    aws iam create-role --role-name "$ACCESS_ROLE_NAME" --assume-role-policy-document "$ACCESS_ROLE_TRUST" --quiet >/dev/null
    aws iam attach-role-policy --role-name "$ACCESS_ROLE_NAME" \
        --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess
    ok "Access role created"
    info "Waiting for IAM propagation..."
    sleep 10
fi
ACCESS_ROLE_ARN="$(aws iam get-role --role-name "$ACCESS_ROLE_NAME" --query 'Role.Arn' --output text)"

if aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" >/dev/null 2>&1; then
    aws secretsmanager put-secret-value --secret-id "$SECRET_NAME" --secret-string "$GEMINI_API_KEY" --region "$REGION" --query 'ARN' --output text >/dev/null
else
    aws secretsmanager create-secret --name "$SECRET_NAME" --secret-string "$GEMINI_API_KEY" --region "$REGION" --query 'ARN' --output text >/dev/null
fi
SECRET_ARN="$(aws secretsmanager describe-secret --secret-id "$SECRET_NAME" --region "$REGION" --query 'ARN' --output text)"
ok "Gemini key stored in Secrets Manager"

if aws iam get-role --role-name "$INSTANCE_ROLE_NAME" >/dev/null 2>&1; then
    ok "Instance role $INSTANCE_ROLE_NAME already exists"
else
    info "Creating App Runner instance role (grants the running container read access to the Gemini secret only)..."
    aws iam create-role --role-name "$INSTANCE_ROLE_NAME" --assume-role-policy-document "$INSTANCE_ROLE_TRUST" --quiet >/dev/null
    SECRET_POLICY="{\"Version\":\"2012-10-17\",\"Statement\":[{\"Effect\":\"Allow\",\"Action\":\"secretsmanager:GetSecretValue\",\"Resource\":\"${SECRET_ARN}\"}]}"
    aws iam put-role-policy --role-name "$INSTANCE_ROLE_NAME" --policy-name "read-gemini-secret" --policy-document "$SECRET_POLICY"
    ok "Instance role created"
    info "Waiting for IAM propagation..."
    sleep 10
fi
INSTANCE_ROLE_ARN="$(aws iam get-role --role-name "$INSTANCE_ROLE_NAME" --query 'Role.Arn' --output text)"

# ---- Step 5: Create or update the App Runner service --------------------------
step 5 "Deploy to App Runner"

SERVICE_ARN="$(aws apprunner list-services --region "$REGION" \
    --query "ServiceSummaryList[?ServiceName=='${APP_NAME}'].ServiceArn" --output text)"

SOURCE_CONFIGURATION=$(cat <<JSON
{
    "ImageRepository": {
        "ImageIdentifier": "${IMAGE}",
        "ImageRepositoryType": "ECR",
        "ImageConfiguration": {
            "Port": "8080",
            "RuntimeEnvironmentVariables": {
                "DB_ENGINE": "sqlite",
                "SQLITE_PATH": "/app/${SQLITE_FILE}",
                "GEMINI_MODEL": "${GEMINI_MODEL}"
            },
            "RuntimeEnvironmentSecrets": {
                "GEMINI_API_KEY": "${SECRET_ARN}"
            }
        }
    },
    "AuthenticationConfiguration": {
        "AccessRoleArn": "${ACCESS_ROLE_ARN}"
    },
    "AutoDeploymentsEnabled": true
}
JSON
)

INSTANCE_CONFIGURATION="{\"Cpu\":\"${CPU}\",\"Memory\":\"${MEMORY}\",\"InstanceRoleArn\":\"${INSTANCE_ROLE_ARN}\"}"

if [ -z "$SERVICE_ARN" ]; then
    info "Creating App Runner service $APP_NAME..."
    SERVICE_ARN="$(aws apprunner create-service \
        --service-name "$APP_NAME" \
        --region "$REGION" \
        --source-configuration "$SOURCE_CONFIGURATION" \
        --instance-configuration "$INSTANCE_CONFIGURATION" \
        --query 'Service.ServiceArn' --output text)" \
        || die "App Runner create-service failed -- see errors above. Common cause: App Runner not available in $REGION for this account (see deviation #5)."
    ok "Service created"
else
    ok "Service $APP_NAME already exists -- updating with the freshly pushed image"
    aws apprunner update-service \
        --service-arn "$SERVICE_ARN" \
        --region "$REGION" \
        --source-configuration "$SOURCE_CONFIGURATION" \
        --instance-configuration "$INSTANCE_CONFIGURATION" \
        --query 'Service.ServiceArn' --output text >/dev/null \
        || die "App Runner update-service failed -- see errors above."
    ok "Update triggered"
fi

info "Waiting for the service to reach RUNNING (this can take a few minutes)..."
for attempt in $(seq 1 30); do
    STATUS="$(aws apprunner describe-service --service-arn "$SERVICE_ARN" --region "$REGION" --query 'Service.Status' --output text)"
    [ "$STATUS" = "RUNNING" ] && break
    if [ "$STATUS" = "CREATE_FAILED" ] || [ "$STATUS" = "UPDATE_FAILED" ]; then
        die "Service status is $STATUS -- check: aws apprunner list-operations --service-arn $SERVICE_ARN --region $REGION"
    fi
    info "Status: $STATUS (attempt $attempt/30)..."
    sleep 15
done
[ "$STATUS" = "RUNNING" ] || warn "Service did not reach RUNNING after ~7.5 minutes (last status: $STATUS) -- check manually."
ok "Deployed"

# ---- Step 6: Retrieve, verify, and save the URL -------------------------------
step 6 "Verify and save URL"

SERVICE_URL="https://$(aws apprunner describe-service --service-arn "$SERVICE_ARN" --region "$REGION" --query 'Service.ServiceUrl' --output text)"

REACHABLE=0
for attempt in 1 2 3; do
    info "Checking $SERVICE_URL is reachable (attempt $attempt/3)..."
    if curl -sS -o /dev/null -w '%{http_code}' "$SERVICE_URL" | grep -qE '^(200|303|304)$'; then
        REACHABLE=1
        break
    fi
    sleep 10
done
[ "$REACHABLE" -eq 1 ] || warn "URL did not respond with 200/303/304 after 3 attempts -- it may still be starting. Check manually: curl -I $SERVICE_URL"

echo "$SERVICE_URL" > "$OUTPUT_FILE"

echo
echo "✅ APP RUNNER DEPLOYMENT COMPLETE!"
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🌐 Live App URL: ${SERVICE_URL}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
echo "✅ Deployment Details:"
echo "   Account: ${ACCOUNT_ID}"
echo "   Service: ${APP_NAME}"
echo "   Region: ${REGION}"
echo "   Instance: ${CPU} / ${MEMORY}"
echo "   Database: SQLite, baked into the image at build time (see deviation #2 above)"
echo "   App login (hardcoded): admin / demo123 -- the only gate in front of a public URL"
echo
echo "💰 Cost: App Runner does NOT scale to zero (see deviation #7) -- it bills"
echo "   continuously while running, even idle. Gemini calls bill against your"
echo "   AI Studio key's own quota, separate from AWS billing."
echo
echo "⏱️  Pause or delete promptly -- both a running meter and a public URL with"
echo "   only a hardcoded login are reasons not to leave this unattended."
echo
echo "📝 To pause (stops compute billing, keeps config):"
echo "   aws apprunner pause-service --service-arn ${SERVICE_ARN} --region ${REGION}"
echo
echo "📝 To fully tear down:"
echo "   aws apprunner delete-service --service-arn ${SERVICE_ARN} --region ${REGION}"
echo "   aws secretsmanager delete-secret --secret-id ${SECRET_NAME} --region ${REGION} --force-delete-without-recovery"
echo "   aws ecr delete-repository --repository-name ${ECR_REPO} --region ${REGION} --force"
echo "   aws iam detach-role-policy --role-name ${ACCESS_ROLE_NAME} --policy-arn arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
echo "   aws iam delete-role --role-name ${ACCESS_ROLE_NAME}"
echo "   aws iam delete-role-policy --role-name ${INSTANCE_ROLE_NAME} --policy-name read-gemini-secret"
echo "   aws iam delete-role --role-name ${INSTANCE_ROLE_NAME}"
echo
echo "Troubleshooting:"
echo "   aws apprunner describe-service --service-arn ${SERVICE_ARN} --region ${REGION}"
echo "   aws logs tail /aws/apprunner/${APP_NAME}/application --region ${REGION} --follow"
echo "   curl -I ${SERVICE_URL}"
echo
echo "URL saved to: ${OUTPUT_FILE}"
