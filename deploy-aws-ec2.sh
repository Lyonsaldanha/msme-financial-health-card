#!/usr/bin/env bash
# Sets up and runs the MSME Financial Health Card on a machine you've already
# provisioned yourself (an EC2 instance, or any Linux box with this repo
# already on it). No AWS CLI calls here, no instance/security-group/key-pair/
# IAM provisioning -- that's on you, done manually, per your own setup. This
# script only prepares the app environment and starts it:
#   1. uv sync    -- install Python dependencies
#   2. docker up  -- best-effort: ensure the Docker daemon is running (not
#                    required for anything below, Streamlit runs natively via
#                    uv; kept only in case you build/run the container image
#                    from this same box separately)
#   3. sqlite3    -- fresh local SQLite file for this run
#   4. Add data   -- ETL -> Analytics -> AI Engine, populating that file
#   5. Run Streamlit -- launches the app natively (uv run streamlit)
#
# Secrets: GEMINI_API_KEY is never read, set, or referenced as a shell
# variable anywhere in this script, and never echoed. Put it in a local .env
# file on this box (same as local dev -- see .env.example); python-dotenv
# (loaded by db/config.py) picks it up automatically when the Python
# processes below start, so this script never needs to touch it. If .env is
# missing or the key is invalid, the AI Engine already degrades to its
# deterministic fallback narrative (see ai/client.py) -- not an error either
# way, so this script doesn't need to know or care which case it is.

set -euo pipefail

SQLITE_FILE="${SQLITE_FILE:-msme_fhc.db}"
APP_PORT="${APP_PORT:-8080}"

TOTAL_STEPS=5
step() { echo; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; echo "[$1/${TOTAL_STEPS}] $2"; echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"; }
ok()   { echo "✅ $1"; }
info() { echo "⏳ $1"; }
warn() { echo "⚠️  $1"; }
die()  { echo "❌ $1" >&2; exit 1; }

command -v uv >/dev/null 2>&1 || die "uv not found. Install: https://docs.astral.sh/uv/"
[ -f pyproject.toml ] || die "pyproject.toml not found in $(pwd). Run this script from the project root."

if [ ! -f .env ]; then
    warn ".env not found -- Gemini calls will fail and the AI Engine will fall back to its deterministic template narrative instead. Not an error, just noting it (see .env.example if you want real Gemini output)."
fi

# ---- Step 1: Install dependencies ---------------------------------------------
step 1 "uv sync"
uv sync
ok "Dependencies installed"

# ---- Step 2: Ensure Docker is running (best-effort, non-blocking) ------------
step 2 "docker up"
if command -v docker >/dev/null 2>&1; then
    if ! docker info >/dev/null 2>&1; then
        info "Starting Docker daemon..."
        sudo systemctl enable --now docker 2>/dev/null || sudo service docker start 2>/dev/null || true
    fi
    if docker info >/dev/null 2>&1; then
        ok "Docker is running"
    else
        warn "Docker still not reachable -- continuing without it (not required for steps 3-5 below)."
    fi
else
    warn "Docker not installed -- skipping (not required for steps 3-5 below)."
fi

# ---- Step 3: Fresh SQLite database ---------------------------------------------
step 3 "sqlite3 setup"
rm -f "$SQLITE_FILE"
ok "Cleared $SQLITE_FILE (fresh database for this run)"

# ---- Step 4: Load and compute data ---------------------------------------------
step 4 "Add data (ETL -> Analytics -> AI Engine)"
info "Running ETL Engine..."
DB_ENGINE=sqlite SQLITE_PATH="$SQLITE_FILE" uv run python etl_engine.py
info "Running Analytics Engine..."
DB_ENGINE=sqlite SQLITE_PATH="$SQLITE_FILE" uv run python analytics_engine.py
info "Running AI Engine (reads GEMINI_API_KEY/GEMINI_MODEL from .env if present; falls back to the deterministic template otherwise)..."
DB_ENGINE=sqlite SQLITE_PATH="$SQLITE_FILE" uv run python ai_engine.py
[ -f "$SQLITE_FILE" ] || die "Data load did not produce $SQLITE_FILE -- check the errors above."
ok "Data loaded ($SQLITE_FILE)"

# ---- Step 5: Run Streamlit ------------------------------------------------------
step 5 "Run Streamlit"
info "Starting on port $APP_PORT (Ctrl+C to stop)..."
exec env DB_ENGINE=sqlite SQLITE_PATH="$SQLITE_FILE" \
    uv run streamlit run app.py --server.port="$APP_PORT" --server.address=0.0.0.0
