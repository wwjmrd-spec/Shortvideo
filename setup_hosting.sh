#!/bin/bash
# ═══════════════════════════════════════════════════════
# ShortsCut AI — cPanel Shared Hosting Setup Script
# Run this via SSH on your shared hosting
# ═══════════════════════════════════════════════════════

echo "🎬 ShortsCut AI — cPanel Setup"
echo "================================"

# Get the app directory
APP_DIR="$(cd "$(dirname "$0")" && pwd)"
echo "📁 App directory: $APP_DIR"

# Step 1: Check Python
echo ""
echo "📌 Step 1: Checking Python..."
if command -v python3 &>/dev/null; then
    PY=$(command -v python3)
    echo "✅ Found Python: $PY ($(python3 --version))"
else
    echo "❌ Python3 not found. Check if your host provides it."
    echo "   Try: which python3.11 or which python3.9"
    exit 1
fi

# Step 2: Create virtual environment
echo ""
echo "📌 Step 2: Creating virtual environment..."
cd "$APP_DIR"
$PY -m venv venv 2>/dev/null || python3 -m venv venv
source venv/bin/activate
echo "✅ Virtual environment created"

# Step 3: Install Python dependencies
echo ""
echo "📌 Step 3: Installing Python packages..."
pip install --upgrade pip
pip install flask flask-cors requests Pillow yt-dlp
echo "✅ Python packages installed"

# Step 4: Check for ffmpeg
echo ""
echo "📌 Step 4: Checking ffmpeg..."
if command -v ffmpeg &>/dev/null; then
    echo "✅ ffmpeg found: $(ffmpeg -version 2>&1 | head -1)"
else
    echo "⚠️  ffmpeg NOT found on this server."
    echo "   Options:"
    echo "   1. Ask your hosting provider to install it"
    echo "   2. Download a static ffmpeg binary:"
    echo "      curl -L https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz -o ffmpeg.tar.xz"
    echo "      tar xf ffmpeg.tar.xz && mv ffmpeg-*-static/ffmpeg ffmpeg-*-static/ffprobe $APP_DIR/venv/bin/"
    echo "   The Video Editor and Shorts Generator need ffmpeg to work."
fi

# Step 5: Check for Node.js (needed by yt-dlp)
echo ""
echo "📌 Step 5: Checking Node.js..."
if command -v node &>/dev/null; then
    echo "✅ Node.js found: $(node --version)"
else
    echo "⚠️  Node.js NOT found. yt-dlp needs it to download YouTube videos."
    echo "   Install via nvm: curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.40.1/install.sh | bash"
    echo "   Then: nvm install --lts"
fi

# Step 6: Create required directories
echo ""
echo "📌 Step 6: Creating directories..."
mkdir -p "$APP_DIR/temp" "$APP_DIR/downloads" "$APP_DIR/editor_uploads"
chmod 755 "$APP_DIR/temp" "$APP_DIR/downloads" "$APP_DIR/editor_uploads"
echo "✅ Directories created"

# Step 7: Set permissions
echo ""
echo "📌 Step 7: Setting permissions..."
chmod 755 "$APP_DIR/server.py"
chmod 755 "$APP_DIR/passenger_wsgi.py"
echo "✅ Permissions set"

# Step 8: Detect cPanel username for .htaccess
echo ""
echo "📌 Step 8: Updating .htaccess paths..."
CPANEL_USER=$(whoami)
HTACCESS="$APP_DIR/.htaccess"
if [ -f "$HTACCESS" ]; then
    sed -i "s|/home/wwjmerco|/home/$CPANEL_USER|g" "$HTACCESS"
    echo "✅ Updated .htaccess with user: $CPANEL_USER"
    echo "   App root: /home/$CPANEL_USER/email/video/shorts-generator"
else
    echo "⚠️  .htaccess not found"
fi

echo ""
echo "═══════════════════════════════════════════════"
echo "✅ Setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. In cPanel → Setup Python App:"
echo "   - Python version: 3.9+ (whatever is available)"
echo "   - App root: email/video/shorts-generator"
echo "   - App URL: /email/video/shorts-generator"
echo "   - Startup file: passenger_wsgi.py"
echo "   - Entry point: application"
echo ""
echo "2. If your cPanel doesn't have 'Setup Python App':"
echo "   You may need to use the .htaccess + CGI method instead."
echo "   Contact your hosting provider about Python support."
echo ""
echo "3. Visit: https://your-domain.com/email/video/shorts-generator/"
echo "═══════════════════════════════════════════════"
