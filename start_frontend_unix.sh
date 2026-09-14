#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/frontend"
python3 -m http.server 5500
