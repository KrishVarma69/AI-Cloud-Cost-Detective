# AI Cloud Cost Detective — backend (FastAPI + AWS CLI v2)
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# --- AWS CLI v2 (the scanner shells out to `aws ...`) ---
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip ca-certificates \
 && ARCH="$(dpkg --print-architecture)" \
 && case "$ARCH" in \
      amd64) AWS_ARCH=x86_64 ;; \
      arm64) AWS_ARCH=aarch64 ;; \
      *) echo "unsupported arch: $ARCH" && exit 1 ;; \
    esac \
 && curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-${AWS_ARCH}.zip" -o /tmp/awscliv2.zip \
 && unzip -q /tmp/awscliv2.zip -d /tmp \
 && /tmp/aws/install \
 && rm -rf /tmp/aws /tmp/awscliv2.zip \
 && apt-get purge -y unzip \
 && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* \
 && aws --version

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as a non-root user; give it a home for the AWS CLI config/cache.
RUN useradd --create-home --uid 10001 appuser \
 && mkdir -p /home/appuser/.aws \
 && chown -R appuser:appuser /app /home/appuser
USER appuser
ENV HOME=/home/appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

# IMPORTANT: keep --workers 1. ProgressHub and the rate limiter hold state in
# memory, so a second worker would not see it. Scale out with a task queue first.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
