#!/bin/sh
set -e

APP_PORT="${PORT:-8100}"

echo "Starting ParagraphMargin API server on port ${APP_PORT}..."
exec uvicorn api.app:app --host 0.0.0.0 --port "${APP_PORT}"
