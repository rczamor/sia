FROM python:3.12-slim

WORKDIR /app

# System dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Python dependencies (layer-cached: metadata only, deps resolved from pyproject)
COPY pyproject.toml .
COPY app/__init__.py app/__init__.py
RUN pip install --no-cache-dir .

# Application code
COPY . .

# Run as a non-root user
RUN useradd --create-home --uid 1000 sia && chown -R sia:sia /app
USER sia

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
