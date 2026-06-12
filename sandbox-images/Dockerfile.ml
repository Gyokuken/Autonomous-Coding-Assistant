# Sandbox image for the "ml" profile: adds numpy + CPU PyTorch so the agents can
# write and tensor-test deep-learning code. Built as `dualcore-sandbox:ml`.
# This image is large (~1GB) because of torch — building it takes a while.
FROM python:3.12-slim

RUN pip install --no-cache-dir "pytest>=8.0.0" "pytest-json-report>=1.5.0" "numpy>=1.26" \
 && pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

WORKDIR /work
