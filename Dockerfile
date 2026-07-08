FROM python:3.12-slim

# Install uv (pinned digest-less latest is fine for a hackathon demo image)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Dependencies first so code-only changes don't bust the layer cache
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

ENV STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0

# Cloud Run injects $PORT and requires the container to listen on it -- shell
# form (not exec form) so that substitution actually happens at container start.
CMD uv run streamlit run app.py --server.port=${PORT:-8080} --server.address=0.0.0.0
