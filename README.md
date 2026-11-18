# ✂️ ShortsCut AI — YouTube Shorts Generator & Video Editor

An AI-powered web application that turns long-form YouTube videos into viral, high-quality (1080p Full HD) vertical 9:16 Shorts, and includes a full timeline video editor with silence removal and chroma key overlays.

![UI Preview](static/index.html)

---

## ✨ Features

### 🎬 1. Automated YouTube Shorts Generator
- **Smart Highlight Detection:** Analyzes audio energy peaks and transcripts to find viral, engaging moments.
- **True 1080p HD Processing:** Downloads highest-quality stream with `yt-dlp` and resamples with Lanczos sinc-filtering (`flags=lanczos`, `CRF 18`).
- **Interactive Crop Control:** Pan horizontally (0% to 100%) to frame speakers or subjects perfectly in 9:16 vertical view.
- **AI-Powered Speech Analysis:** Uses **Groq (Llama 3)** or **Google Gemini** to generate contextual titles, descriptions, and hashtags based on what is *actually* spoken in the clip.
- **Sequential Preview:** Play all generated highlights one after another before exporting.
- **Direct YouTube Upload:** Upload created shorts directly to your YouTube channel via OAuth 2.0.

### 🎞️ 2. Multi-Clip Video Editor
- **Timeline Sequence:** Upload multiple clips, rearrange with drag-and-drop, and preview in real-time.
- **AI Silence Removal:** Automatically scans audio waveforms to detect and cut silent, dead-air pauses.
- **Chroma Key Overlays:** Add green-screen or blue-screen video overlays on top of your main clips with customizable key color, similarity, and blend settings.
- **Trimming & Editing:** Trim starts/ends, cut unwanted middle segments, adjust volume, and apply noise reduction.
- **Precap & Coming Up Intros:** Add branded intro and outro cards.

---

## 🛠️ Tech Stack

- **Backend:** Python 3.11, Flask, Flask-CORS
- **Video & Audio Processing:** FFmpeg, FFprobe, Pillow
- **YouTube Extraction:** yt-dlp (Node.js runtime integration)
- **AI Models:** Groq (Llama 3.3 70B / Llama 3 8B), Google Gemini 1.5/2.0
- **Frontend:** HTML5, CSS3 (Modern Glassmorphic Dark UI), Vanilla JavaScript

---

## 🚀 Quick Start (Local Setup)

### Prerequisites
Make sure you have installed:
1. **Python 3.11+**
2. **FFmpeg**: `brew install ffmpeg`
3. **Node.js**: `brew install node`

### 1. Clone the repository
```bash
git clone https://github.com/YOUR_USERNAME/shortscut-ai.git
cd shortscut-ai
```

### 2. Install Python dependencies
```bash
pip install -r requirements.txt
```

### 3. Start the server
```bash
python3.11 server.py
```

### 4. Open in browser
Navigate to:
```
http://localhost:5555
```

---

## ⚙️ AI Configuration (Optional)
Click the **⚙️** icon in the top-right header to input your free API key:
- **Groq API Key:** [Get free key at console.groq.com](https://console.groq.com/keys)
- **Google Gemini API Key:** [Get key at aistudio.google.com](https://aistudio.google.com/apikey)

*(If no API key is provided, the app will automatically analyze transcripts directly for contextual titles).*

---

## 🌐 Hosting & Deployment
The project includes pre-configured deployment files for shared hosting / cPanel:
- `passenger_wsgi.py`: WSGI entry point for Phusion Passenger.
- `.htaccess`: Apache URL rewriting rules.
- `setup_hosting.sh`: Auto-installation script for server dependencies.

---

## 📄 License
MIT License. Free to use, modify, and distribute.
