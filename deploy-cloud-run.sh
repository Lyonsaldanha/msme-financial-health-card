#!/usr/bin/env bash
# Deploys the MSME Financial Health Card to Cloud Run using SQLite instead of
# Cloud SQL -- no separate database service, so nothing here bills beyond
# Cloud Run itself. Safe to re-run.
#
# Deviations from a literal reading of the brief, and why:
#
# 1. **SQLite, not "no database."** The brief has no DB step at all and says
#    "buildable without external DB" -- but this app needs Postgres (or some
#    SQL database) for everything past the login page; without one, Dashboard
#    and Reports would throw on first use. SQLite avoids a second billed
#    resource (the actual goal of "trial credits only") while still leaving
#    the app fully functional. See db/config.py's DB_ENGINE=sqlite path.
# 2. **Data is pre-built locally and baked into the image, not written at
#    runtime.** Cloud Run's container filesystem is ephemeral -- anything
#    written after startup is lost on the next cold start (scale-to-zero,
#    then a fresh instance). This script runs the ETL/Analytics/AI engines
#    locally against a SQLite file *before* `docker build`, so the image
#    ships with all 6 customers' scorecards and reports already generated.
#    Clicking "Generate Health Card" in the deployed app still works for the
#    lifetime of that one running instance, but a fresh cold start reverts to
#    the baked-in snapshot. --max-instances=1 (per the brief) is also what
#    keeps this from becoming two divergent SQLite files under concurrent load.
# 3. **Gemini is not "covered by GCP trial credit."** It authenticates via an
#    AI Studio API key -- a separate quota system from GCP Cloud billing,
#    confirmed the hard way earlier in this project (a `limit: 0` free-tier
#    quota error had nothing to do with any GCP trial balance). Deploying to
#    Cloud Run doesn't change that billing relationship.
# 4. **Artifact Registry, not Container Registry (gcr.io).** GCR is
#    deprecated for new usage -- a brand-new project is the worst case to
#    rely on it in.
# 5. **GEMINI_API_KEY goes into Secret Manager**, not a plaintext
#    --set-env-vars value readable by anyone with run.services.get.
# 6. **Region is asia-south1 (Mumbai)**, matching this project's earlier,
#    more deliberate requirement (judge/demo latency from India) over the
#    generic us-central1 default that appears elsewhere in this brief.
# 7. **Built via `gcloud builds submit` (Cloud Build), not local `docker
#    build` + `docker push`.** Confirmed directly in Cloud Shell: the local
#    Docker daemon there cannot reliably reach Artifact Registry --
#    `docker push` failed repeatedly with `connection refused` even with
#    correct auth and IAM. Cloud Build builds and pushes from inside Google's
#    own network, sidestepping that path entirely, and means this script no
#    longer needs Docker installed/running locally at all.
#
# None of this is exotic -- it's the same script, done without the parts that
# would silently produce a broken or insecure deployment.

set -euo pipefail

# ---- Configuration (override via env vars) ---------------------------------
PROJECT_ID="${PROJECT_ID:-msme-fhc-demo}"
BILLING_ACCOUNT_ID="${BILLING_ACCOUNT_ID:-018F47-3AAAC7-3D2312}"
REGION="${REGION:-asia-south1}"                # Mumbai -- see deviation #6 above
APP_NAME="${APP_NAME:-msme-fhc}"
ARTIFACT_REPO="${APP_NAME}-repo"
SERVICE_ACCOUNT_NAME="${APP_NAME}-run-sa"
SQLITE_FILE="msme_fhc.db"                       # baked into the image at this path, relative to the Dockerfile's WORKDIR /app
GEMINI_API_KEY="${GEMINI_API_KEY:-demo-key}"    # falls back to the AI Engine's deterministic template narrative if unset/invalid
GEMINI_MODEL="${GEMINI_MODEL:-gemini-flash-lite-latest}"  # cheapest current model; export GEMINI_MODEL to override
OUTPUT_FILE="cloud-run-url.txt"

TOTAL_STEPS=6
step() { echo; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; echo "[$1/${TOTAL_STEPS}] $2"; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; }
ok()   { echo "✅ $1"; }
info() { echo "⏳ $1"; }
warn() { echo "⚠️  $1"; }
die()  { echo "❌ $1" >&2; exit 1; }

# ---- Dependency checks -------------------------------------------------------
# No local Docker required -- Cloud Build does the build+push remotely (see deviation #7).
command -v gcloud >/dev/null 2>&1 || die "gcloud CLI not found. Install: https://cloud.google.com/sdk/docs/install"
command -v uv     >/dev/null 2>&1 || die "uv not found (needed for the local pre-build step). Install: https://docs.astral.sh/uv/"
gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null | grep -q . \
    || die "No active gcloud auth. Run: gcloud auth login"
[ -f Dockerfile ] || die "Dockerfile not found in $(pwd). Run this script from the project root."

# ---- Step 1: Project + billing + APIs ---------------------------------------
step 1 "GCP project setup"

if gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
    ok "Project $PROJECT_ID already exists"
else
    info "Creating project $PROJECT_ID..."
    gcloud projects create "$PROJECT_ID" --quiet \
        || die "Could not create project '$PROJECT_ID' -- project IDs are globally unique; it may belong to someone else. Try a different PROJECT_ID."
    ok "Project created"
fi
gcloud config set project "$PROJECT_ID" --quiet

if [ "$(gcloud beta billing projects describe "$PROJECT_ID" --format='value(billingEnabled)' 2>/dev/null)" != "True" ]; then
    info "Linking billing account $BILLING_ACCOUNT_ID..."
    gcloud beta billing projects link "$PROJECT_ID" --billing-account="$BILLING_ACCOUNT_ID" --quiet || {
        warn "Billing link failed. Link it manually, then re-run this script:"
        warn "  https://console.cloud.google.com/billing/linkedaccount?project=$PROJECT_ID"
        die "Cannot continue without billing enabled (Cloud Run's build step requires it even on the free tier)."
    }
    ok "Billing linked"
else
    ok "Billing already enabled"
fi

info "Enabling required APIs..."
gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com --quiet \
    || die "API enablement failed -- try enabling run.googleapis.com manually in the console and re-run."
ok "APIs enabled"

# ---- Step 2: Pre-build the SQLite database locally ---------------------------
step 2 "Pre-build local database (baked into the image -- see deviation #2)"

rm -f "$SQLITE_FILE"
info "Running ETL Engine..."
DB_ENGINE=sqlite SQLITE_PATH="$SQLITE_FILE" uv run python etl_engine.py
info "Running Analytics Engine..."
DB_ENGINE=sqlite SQLITE_PATH="$SQLITE_FILE" uv run python analytics_engine.py
info "Running AI Engine (model: $GEMINI_MODEL; uses GEMINI_API_KEY if set and valid, else the deterministic fallback narrative)..."
DB_ENGINE=sqlite SQLITE_PATH="$SQLITE_FILE" GEMINI_API_KEY="$GEMINI_API_KEY" GEMINI_MODEL="$GEMINI_MODEL" uv run python ai_engine.py
[ -f "$SQLITE_FILE" ] || die "Pre-build did not produce $SQLITE_FILE -- check the errors above."
ok "Local database populated ($SQLITE_FILE)"

# ---- Step 3: Build and push via Cloud Build -----------------------------------
step 3 "Build and push (Cloud Build -- see deviation #7)"

if gcloud artifacts repositories describe "$ARTIFACT_REPO" --location="$REGION" >/dev/null 2>&1; then
    ok "Artifact Registry repo $ARTIFACT_REPO already exists"
else
    info "Creating Artifact Registry repo..."
    gcloud artifacts repositories create "$ARTIFACT_REPO" --repository-format=docker --location="$REGION" --quiet
    ok "Repo created"
fi

IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${APP_NAME}:latest"
info "Submitting build to Cloud Build (includes $SQLITE_FILE via the Dockerfile's COPY . . step)..."
info "This uploads the project directory and builds remotely -- typically 2-4 minutes."
gcloud builds submit --tag "$IMAGE" --region="$REGION" . \
    || die "Cloud Build failed -- see errors above. Check: gcloud builds list --region=$REGION --limit=1"
ok "Image built and pushed"

# ---- Step 4: Service account + secret ----------------------------------------
step 4 "Service account and secrets"

SA_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
if gcloud iam service-accounts describe "$SA_EMAIL" >/dev/null 2>&1; then
    ok "Service account $SERVICE_ACCOUNT_NAME already exists"
else
    info "Creating a minimally-scoped service account for Cloud Run..."
    gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" --display-name="$APP_NAME demo runtime" --quiet
    gcloud projects add-iam-policy-binding "$PROJECT_ID" \
        --member="serviceAccount:${SA_EMAIL}" --role="roles/secretmanager.secretAccessor" --quiet >/dev/null
    ok "Service account created with secretmanager.secretAccessor"
    info "Waiting for IAM propagation..."
    sleep 10
fi

if gcloud secrets describe "${APP_NAME}-gemini-key" >/dev/null 2>&1; then
    printf '%s' "$GEMINI_API_KEY" | gcloud secrets versions add "${APP_NAME}-gemini-key" --data-file=- --quiet >/dev/null
else
    printf '%s' "$GEMINI_API_KEY" | gcloud secrets create "${APP_NAME}-gemini-key" --data-file=- --replication-policy=automatic --quiet >/dev/null
fi
ok "Gemini key stored in Secret Manager"

# ---- Step 5: Deploy to Cloud Run ----------------------------------------------
step 5 "Deploy to Cloud Run"

gcloud run deploy "$APP_NAME" \
    --image="$IMAGE" \
    --platform=managed \
    --region="$REGION" \
    --service-account="$SA_EMAIL" \
    --allow-unauthenticated \
    --memory=1Gi \
    --cpu=1 \
    --timeout=300 \
    --max-instances=1 \
    --set-env-vars="DB_ENGINE=sqlite,SQLITE_PATH=/app/${SQLITE_FILE},GEMINI_MODEL=${GEMINI_MODEL}" \
    --set-secrets="GEMINI_API_KEY=${APP_NAME}-gemini-key:latest" \
    --quiet \
    || die "Cloud Run deploy failed -- see errors above. Common cause: image not fully propagated in Artifact Registry yet -- wait 30s and re-run this script (it's idempotent)."
ok "Deployed"

# ---- Step 6: Retrieve, verify, and save the URL -------------------------------
step 6 "Verify and save URL"

SERVICE_URL="$(gcloud run services describe "$APP_NAME" --region="$REGION" --format='value(status.url)')"
[ -n "$SERVICE_URL" ] || die "Could not retrieve service URL. Check manually: gcloud run services describe $APP_NAME --region $REGION"

REACHABLE=0
for attempt in 1 2 3; do
    info "Checking $SERVICE_URL is reachable (attempt $attempt/3)..."
    if curl -sS -o /dev/null -w '%{http_code}' "$SERVICE_URL" | grep -qE '^(200|303|304)$'; then
        REACHABLE=1
        break
    fi
    sleep 5
done
[ "$REACHABLE" -eq 1 ] || warn "URL did not respond with 200/303/304 after 3 attempts -- it may still be starting. Check manually: curl -I $SERVICE_URL"

echo "$SERVICE_URL" > "$OUTPUT_FILE"

echo
echo "✅ CLOUD RUN DEPLOYMENT COMPLETE!"
echo
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🌐 Live App URL: ${SERVICE_URL}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo
echo "✅ Deployment Details:"
echo "   Project: ${PROJECT_ID}"
echo "   Billing: Trial Account (${BILLING_ACCOUNT_ID})"
echo "   Service: ${APP_NAME}"
echo "   Region: ${REGION}"
echo "   Database: SQLite, baked into the image at build time (see deviation #2 above)"
echo "   App login (hardcoded): admin / demo123 -- the only gate in front of a public URL"
echo
echo "💰 Cost: Cloud Run + Artifact Registry storage only -- no Cloud SQL. Gemini calls"
echo "   bill against your AI Studio key's own quota, separate from GCP trial credit."
echo
echo "⏱️  Tear down promptly -- a public URL with only a hardcoded login is not something"
echo "   to leave running unattended."
echo
echo "📝 To cleanup:"
echo "   gcloud run services delete ${APP_NAME} --region ${REGION} --quiet"
echo "   gcloud secrets delete ${APP_NAME}-gemini-key --quiet"
echo "   gcloud artifacts repositories delete ${ARTIFACT_REPO} --location=${REGION} --quiet"
echo "   gcloud iam service-accounts delete ${SA_EMAIL} --quiet"
echo
echo "Troubleshooting:"
echo "   gcloud run services describe ${APP_NAME} --region ${REGION}"
echo "   gcloud logging read \"resource.type=cloud_run_revision\" --limit 50"
echo "   curl -I ${SERVICE_URL}"
echo
echo "URL saved to: ${OUTPUT_FILE}"
