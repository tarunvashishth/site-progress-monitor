#!/bin/bash
# Single-container mode for free hosts that allow only one service: API + worker together.
# If either process exits, the container exits so the platform restarts both.
python -m cpm.worker.main &
uvicorn cpm.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
wait -n
exit 1
