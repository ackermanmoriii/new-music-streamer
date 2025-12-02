#!/bin/bash
# Install system dependencies
apt-get update
apt-get install -y ffmpeg libavcodec-extra

# Install Python dependencies
pip install --no-cache-dir -r requirements.txt

# Create necessary directories
mkdir -p templates
