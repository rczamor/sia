FROM python:3.14-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    git \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies, pinned by the lockfile for reproducible image builds
# (regenerate with `make lock` after changing pyproject.toml)
COPY pyproject.toml constraints.txt ./
COPY app/__init__.py app/__init__.py
RUN pip install --no-cache-dir -c constraints.txt .

# Application code
COPY . .
RUN chmod +x docker-entrypoint.sh

# Run as a non-root user
RUN useradd --create-home --uid 1000 sia && chown -R sia:sia /app
USER sia

EXPOSE 8000

# The entrypoint waits for Postgres and applies migrations, so a fresh DB just
# works. Shell form (via bash) so it runs even if a bind-mount drops the +x bit.
# --proxy-headers honors X-Forwarded-Proto/For from a TLS proxy, but only from
# connections matching FORWARDED_ALLOW_IPS (uvicorn default: 127.0.0.1) — set that
# env to your proxy's IP so Secure cookies/HSTS engage; see docs/deployment.md.
ENTRYPOINT ["bash", "docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
