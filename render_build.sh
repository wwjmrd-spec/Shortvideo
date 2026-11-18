#!/usr/bin/env bash
# exit on error
set -o errexit

# Install Python packages
pip install --upgrade pip
pip install -r requirements.txt

# Install static FFmpeg binary into ~/.local/bin if not present
if ! command -v ffmpeg &> /dev/null; then
  echo "Downloading static FFmpeg..."
  curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -o ffmpeg.tar.xz
  tar -xf ffmpeg.tar.xz
  mkdir -p $HOME/.local/bin
  cp ffmpeg-*-static/ffmpeg ffmpeg-*-static/ffprobe $HOME/.local/bin/
  rm -rf ffmpeg.tar.xz ffmpeg-*-static
  echo "✅ FFmpeg installed to $HOME/.local/bin"
fi
