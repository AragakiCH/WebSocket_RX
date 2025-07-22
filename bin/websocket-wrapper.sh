#!/bin/bash
exec uvicorn ws.main:app --host 0.0.0.0 --port 8000
