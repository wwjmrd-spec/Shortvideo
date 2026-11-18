"""
YouTube Shorts Generator — Backend Server
Downloads YouTube videos, detects highlight moments via audio energy analysis,
and generates 9:16 vertical clips (10-15s) ready for YouTube Shorts.
"""

import os
import json
import uuid
import subprocess
import re
import math
import shutil
from pathlib import Path
from flask import Flask, request, jsonify, send_file, redirect, send_from_directory
from flask_cors import CORS

app = Flask(__name__, static_folder='static', static_url_path='/email/video/shorts-generator/static')
CORS(app, origins="*")  # Allow all origins so hosted frontend can reach local/VPS backend

# URL prefix for all API routes when deployed
URL_PREFIX = "/email/video/shorts-generator"

BASE_DIR = Path(__file__).parent
TEMP_DIR = BASE_DIR / "temp"
DOWNLOADS_DIR = BASE_DIR / "downloads"
TEMP_DIR.mkdir(exist_ok=True)
DOWNLOADS_DIR.mkdir(exist_ok=True)

# Add ~/.local/bin to PATH if present (for Render custom ffmpeg)
home_bin = Path.home() / ".local" / "bin"
if home_bin.exists() and str(home_bin) not in os.environ.get("PATH", ""):
    os.environ["PATH"] = f"{home_bin}:{os.environ.get('PATH', '')}"

# Store job state in memory
jobs = {}


def get_clean_env():
    """Environment without proxy variables so yt-dlp connects directly."""
    return {k: v for k, v in os.environ.items() if not k.lower().endswith('_proxy')}


def get_base_ytdlp_cmd():
    """Build base yt-dlp arguments to bypass bot protection and datacenter 429."""
    cmd = [
        "yt-dlp",
        "--socket-timeout", "30",
        "--retries", "5",
        "--extractor-retries", "5",
        "--no-check-certificates",
        "--geo-bypass",
        "--no-update",
        "--js-runtimes", "node",
        "--remote-components", "ejs:github",
        "--extractor-args", "youtube:player_client=ios,android,mweb",
        "--user-agent", "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
    ]

    # Support cookies from file or environment variable (essential for cloud/Render)
    cookies_file = BASE_DIR / "cookies.txt"
    if os.environ.get("YOUTUBE_COOKIES") and not cookies_file.exists():
        try:
            cookies_file.write_text(os.environ.get("YOUTUBE_COOKIES"))
        except Exception:
            pass

    if cookies_file.exists():
        cmd += ["--cookies", str(cookies_file)]

    # Support custom proxy if set in environment (e.g. residential proxy on Render)
    if os.environ.get("YOUTUBE_PROXY"):
        cmd += ["--proxy", os.environ.get("YOUTUBE_PROXY")]

    return cmd


def get_video_info(url):
    """Get video metadata using yt-dlp without downloading."""
    cmd = get_base_ytdlp_cmd() + [
        "--dump-json", "--no-download",
        "--no-playlist",
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=180, env=get_clean_env())
    if result.returncode != 0:
        raise Exception(f"yt-dlp error: {result.stderr[:500]}")
    return json.loads(result.stdout)


def download_video(url, job_id):
    """Download video using yt-dlp."""
    output_path = TEMP_DIR / f"{job_id}.%(ext)s"
    cmd = get_base_ytdlp_cmd() + [
        "-f", "bestvideo[height<=1080]+bestaudio/bestvideo+bestaudio/best[height<=1080]/best",
        "--merge-output-format", "mp4",
        "-o", str(output_path),
        "--no-playlist",
        url
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, env=get_clean_env())
    if result.returncode != 0:
        raise Exception(f"Download failed: {result.stderr[:500]}")

    # Find the downloaded file
    for f in TEMP_DIR.glob(f"{job_id}.*"):
        if f.suffix in ('.mp4', '.mkv', '.webm'):
            return str(f)
    raise Exception("Downloaded file not found")


def get_video_duration(filepath):
    """Get video duration using ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_format",
        filepath
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    return float(data["format"]["duration"])


def get_video_dimensions(filepath):
    """Get video width and height."""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams",
        "-select_streams", "v:0",
        filepath
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    data = json.loads(result.stdout)
    stream = data["streams"][0]
    return int(stream["width"]), int(stream["height"])


def analyze_audio_energy(filepath, segment_duration=2.0):
    """
    Analyze audio energy levels using a SINGLE ffmpeg pass.
    Extracts raw PCM audio, then computes RMS energy per segment in Python.
    Much faster than running ffmpeg per-second.
    """
    import struct

    duration = get_video_duration(filepath)
    sample_rate = 16000  # 16kHz mono is enough for energy analysis

    # Single ffmpeg call to extract all audio as raw PCM
    cmd = [
        "ffmpeg", "-i", filepath,
        "-ac", "1",              # mono
        "-ar", str(sample_rate), # 16kHz
        "-f", "s16le",           # signed 16-bit little-endian
        "-vn",                   # no video
        "-"
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=120)
    if result.returncode != 0:
        # Fallback: return empty energies
        return [], duration

    raw_audio = result.stdout
    # Each sample is 2 bytes (s16le)
    num_samples = len(raw_audio) // 2
    samples_per_segment = int(sample_rate * segment_duration)

    energies = []
    for i in range(0, num_samples, samples_per_segment):
        chunk = raw_audio[i * 2:(i + samples_per_segment) * 2]
        if len(chunk) < 4:
            continue

        # Compute RMS energy of this chunk
        n = len(chunk) // 2
        fmt = f"<{n}h"
        try:
            values = struct.unpack(fmt, chunk[:n * 2])
            rms = math.sqrt(sum(v * v for v in values) / n)
            # Normalize to 0-100 scale (max s16 value is 32768)
            energy = (rms / 32768.0) * 100
        except Exception:
            energy = 0

        t = (i / samples_per_segment) * segment_duration
        energies.append((t, energy))

    return energies, duration


def detect_scene_changes(filepath, threshold=0.3):
    """Detect scene changes in the video using ffmpeg."""
    cmd = [
        "ffmpeg", "-i", filepath,
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    stderr = result.stderr

    scenes = []
    for match in re.finditer(r'pts_time:([\d.]+)', stderr):
        scenes.append(float(match.group(1)))

    return scenes


def find_highlight_segments(energies, duration, scene_changes,
                            clip_duration=12, num_clips=5, min_gap=15):
    """
    Find the most engaging segments based on audio energy and scene activity.
    Returns list of (start_time, end_time, score) tuples.
    """
    if not energies:
        # Fallback: evenly spaced segments
        segments = []
        gap = duration / (num_clips + 1)
        for i in range(num_clips):
            start = gap * (i + 1) - clip_duration / 2
            start = max(0, min(start, duration - clip_duration))
            segments.append((start, start + clip_duration, 50))
        return segments

    # Create a scoring window for each possible start position
    candidates = []
    step = 1.0  # 1 second steps

    for start in range(0, int(duration - clip_duration), int(step)):
        end = start + clip_duration

        # Audio energy score for this window
        window_energies = [e for t, e in energies if start <= t < end]
        if not window_energies:
            continue
        avg_energy = sum(window_energies) / len(window_energies)
        peak_energy = max(window_energies)

        # Scene change bonus (more scene changes = more dynamic)
        scene_count = sum(1 for s in scene_changes if start <= s < end)
        scene_bonus = scene_count * 5

        # Avoid very beginning and very end (usually intro/outro)
        position_penalty = 0
        if start < 10 or start > duration - 15:
            position_penalty = -20

        total_score = avg_energy * 0.6 + peak_energy * 0.4 + scene_bonus + position_penalty
        candidates.append((start, end, total_score))

    # Sort by score descending
    candidates.sort(key=lambda x: x[2], reverse=True)

    # Select top segments with minimum gap between them
    selected = []
    for start, end, score in candidates:
        if len(selected) >= num_clips:
            break
        # Check minimum gap from already selected
        too_close = any(abs(start - s) < min_gap for s, e, sc in selected)
        if not too_close:
            selected.append((start, end, score))

    # Sort by start time for nice ordering
    selected.sort(key=lambda x: x[0])
    return selected


def generate_short_clip(input_path, output_path, start, duration,
                        crop_position=50, target_w=1080, target_h=1920):
    """
    Generate a 9:16 vertical clip from horizontal video.
    crop_position: 0=left, 50=center, 100=right (horizontal pan control)
    """
    src_w, src_h = get_video_dimensions(input_path)
    target_ratio = 9 / 16
    src_ratio = src_w / src_h

    if src_ratio > target_ratio:
        crop_h = src_h
        crop_w = int(src_h * target_ratio)
    else:
        crop_w = src_w
        crop_h = int(src_w / target_ratio)

    # Apply crop_position (0=left, 50=center, 100=right)
    max_x = src_w - crop_w
    max_y = src_h - crop_h
    crop_x = int(max_x * (crop_position / 100))
    crop_y = max_y // 2  # always vertically centered

    vf = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={target_w}:{target_h}:flags=lanczos"

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start),
        "-i", input_path,
        "-t", str(duration),
        "-vf", vf,
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise Exception(f"FFmpeg error: {result.stderr[:300]}")
    return output_path


def extract_thumbnail(input_path, thumb_path, start, crop_position=50,
                      target_w=1080, target_h=1920):
    """Extract a thumbnail frame from the video at the given timestamp."""
    src_w, src_h = get_video_dimensions(input_path)
    target_ratio = 9 / 16

    if src_w / src_h > target_ratio:
        crop_h = src_h
        crop_w = int(src_h * target_ratio)
    else:
        crop_w = src_w
        crop_h = int(src_w / target_ratio)

    max_x = src_w - crop_w
    crop_x = int(max_x * (crop_position / 100))
    crop_y = (src_h - crop_h) // 2

    vf = f"crop={crop_w}:{crop_h}:{crop_x}:{crop_y},scale={target_w}:{target_h}:flags=lanczos"

    cmd = [
        "ffmpeg", "-y",
        "-ss", str(start + 2),  # 2s into the clip for a good frame
        "-i", input_path,
        "-vf", vf,
        "-frames:v", "1",
        "-q:v", "1",
        thumb_path
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    return thumb_path


def generate_title_and_hashtags(video_title, clip_index, start_time, duration,
                                 transcript_segment=None, ai_config=None):
    """
    Generate UNIQUE title, description and hashtags for each clip.
    Analyzes what's actually being said in THIS specific clip.
    """
    # Try AI-powered generation first (uses actual transcript)
    if transcript_segment and ai_config and len(transcript_segment.strip()) > 15:
        try:
            result = ai_generate_metadata(video_title, transcript_segment,
                                           clip_index, ai_config)
            if result:
                return result
        except Exception:
            pass

    # Fallback: extract key phrase from THIS clip's transcript
    if transcript_segment and len(transcript_segment.strip()) > 20:
        text = transcript_segment.strip()

        # Split into sentences and find the most interesting one
        sentences = re.split(r'[.!?]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 10]

        # Pick the sentence with the most content words (most "interesting")
        stopwords = {'the','a','an','and','or','but','in','on','at','to','for','of','is',
                     'it','this','that','with','from','by','as','our','my','we','i','you',
                     'ever','most','very','just','also','so','no','yes','not','be','was',
                     'are','been','has','had','have','do','did','will','would','can','could',
                     'its','they','them','then','than','there','here','what','when','where',
                     'how','why','who','all','each','some','if','about','up','out','like',
                     'dont','know','think','going','really','right','gonna','want','got',
                     'yeah','okay','well','thing','things','get','one','two','dont','thats',
                     'youre','were','hes','shes','theyre','weve','ive','im','lets','theres'}

        best_sentence = ""
        best_score = 0
        for s in sentences:
            s_words = s.split()
            content_count = sum(1 for w in s_words
                               if w.lower().strip('.,!?\"\'-') not in stopwords
                               and len(w.strip('.,!?\"\'-')) > 2)
            if content_count > best_score:
                best_score = content_count
                best_sentence = s

        # Build title from the key sentence (truncate to ~60 chars)
        if best_sentence and len(best_sentence) > 10:
            # Capitalize first letter
            key_phrase = best_sentence[0].upper() + best_sentence[1:]
            if len(key_phrase) > 60:
                key_phrase = key_phrase[:57].rsplit(' ', 1)[0] + '...'
            title = f'{key_phrase} 🎬'
        else:
            # Use middle section of transcript as title
            words = text.split()
            mid = max(0, len(words) // 4)
            snippet_words = words[mid:mid+8]
            snippet = ' '.join(snippet_words)
            if len(snippet) > 60:
                snippet = snippet[:57].rsplit(' ', 1)[0] + '...'
            title = f'{snippet.capitalize()} 🎬'

        if len(title) > 80:
            title = title[:77] + '...'

        # Description: use first 2 sentences for context
        desc_sentences = [s.strip() for s in re.split(r'[.!?]+', text) if len(s.strip()) > 5][:2]
        desc = '. '.join(desc_sentences)
        if len(desc) > 200:
            desc = desc[:197].rsplit(' ', 1)[0] + '...'
        if not desc:
            desc = text[:200]

        # Hashtags from unique content words in THIS clip
        all_words = text.split()
        content_words = [w for w in all_words
                         if w.lower().strip('.,!?\"\'-') not in stopwords
                         and len(w.strip('.,!?\"\'-')) > 3]
        seen_tags = set()
        hashtags = []
        for w in content_words:
            clean_w = re.sub(r'[^a-zA-Z0-9]', '', w)
            if not clean_w:
                continue
            tag = '#' + clean_w.capitalize()
            if tag.lower() not in seen_tags and len(tag) > 3:
                seen_tags.add(tag.lower())
                hashtags.append(tag)
                if len(hashtags) >= 6:
                    break

        hashtags.extend(['#Shorts', '#YouTubeShorts'])
        return title, desc, hashtags[:10]

    # Last resort: use timestamp + clip index (NOT video title copy)
    mins = int(start_time // 60)
    secs = int(start_time % 60)
    title = f"Moment at {mins}:{secs:02d} 🎬"
    desc = f"Interesting moment from the video at {mins}:{secs:02d}"
    hashtags = ['#Shorts', '#YouTubeShorts', '#Clips']
    return title, desc, hashtags


def ai_generate_metadata(video_title, transcript_segment, clip_index, ai_config):
    """Use AI to generate UNIQUE title, description & hashtags from the clip's transcript."""
    prompt = f"""You are a YouTube Shorts expert. Read this transcript from Clip #{clip_index} and create a UNIQUE title based on what the speaker is saying in THIS specific moment.

Transcript of this clip:
---
{transcript_segment[:800]}
---

Rules:
1. The title MUST describe what's being discussed IN THIS CLIP ONLY
2. DO NOT copy or paraphrase the original video title: "{video_title}"
3. DO NOT use generic clickbait like "Wait for it", "You won't believe", "This is insane"
4. The title should feel like a quote or key takeaway from what's being said
5. Each clip should have a COMPLETELY DIFFERENT title — imagine you're writing a headline for a news article about this specific moment

Return ONLY a JSON object:
{{
  "title": "A unique, specific title about what's being said (max 65 chars, 1-2 emojis)",
  "description": "1-2 sentences explaining what the speaker is discussing in this clip (max 180 chars)",
  "hashtags": ["#Topic1", "#Topic2", "#Topic3", "#Topic4", "#Topic5", "#Shorts", "#YouTubeShorts"]
}}

IMPORTANT: hashtags must be specific to the WORDS and TOPICS mentioned in the transcript, not generic.
Return ONLY valid JSON, nothing else."""

    result = ai_call(prompt, ai_config, max_tokens=400)
    if not result:
        return None

    try:
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            title = data.get("title", "")[:80]
            desc = data.get("description", "")[:200]
            hashtags = data.get("hashtags", [])
            # Verify title isn't just copying the video title
            if title and hashtags:
                title_lower = title.lower().strip()
                vid_lower = video_title.lower().strip()
                # If title is too similar to video title, reject and let fallback handle it
                if title_lower == vid_lower or vid_lower in title_lower:
                    return None
                return title, desc or f"Clip {clip_index} highlights", hashtags[:10]
    except (json.JSONDecodeError, KeyError):
        pass

    return None


def get_transcript_for_segment(timed_segments, start, duration):
    """Get the transcript text for a specific time segment with context."""
    end = start + duration
    words = []
    for t, text in timed_segments:
        # Include words within the clip timeframe (with small buffer)
        if start - 1 <= t <= end + 1:
            words.append(text)
    result = ' '.join(words)
    # If we got very little text, expand the window
    if len(result) < 30:
        words = []
        for t, text in timed_segments:
            if start - 5 <= t <= end + 5:
                words.append(text)
        result = ' '.join(words)
    return result


# ──────────────────────────────────────
# AI Integration
# ──────────────────────────────────────

def extract_transcript(url, job_id):
    """Extract transcript/subtitles from a YouTube video using yt-dlp."""
    sub_path = TEMP_DIR / f"{job_id}_subs"
    cmd = get_base_ytdlp_cmd() + [
        "--write-auto-sub", "--sub-lang", "en",
        "--skip-download",
        "--sub-format", "vtt",
        "-o", str(sub_path),
        "--no-playlist",
        url
    ]
    subprocess.run(cmd, capture_output=True, text=True, timeout=120, env=get_clean_env())

    # Find the subtitle file
    transcript_text = ""
    timestamps = []
    for f in TEMP_DIR.glob(f"{job_id}_subs*.vtt"):
        try:
            content = f.read_text(encoding='utf-8', errors='ignore')
            # Parse VTT: extract text with timestamps
            lines = content.split('\n')
            current_time = None
            for line in lines:
                line = line.strip()
                # Match timestamp lines like 00:00:01.000 --> 00:00:03.000
                ts_match = re.match(r'(\d{2}):(\d{2}):(\d{2})\.\d+\s*-->', line)
                if ts_match:
                    h, m, s = int(ts_match.group(1)), int(ts_match.group(2)), int(ts_match.group(3))
                    current_time = h * 3600 + m * 60 + s
                elif line and not line.startswith('WEBVTT') and not line.startswith('Kind:') \
                     and not line.startswith('Language:') and not re.match(r'^\d+$', line) \
                     and '-->' not in line:
                    # Clean HTML tags
                    clean = re.sub(r'<[^>]+>', '', line)
                    if clean.strip():
                        transcript_text += clean.strip() + " "
                        if current_time is not None:
                            timestamps.append((current_time, clean.strip()))
        except Exception:
            pass
        finally:
            f.unlink(missing_ok=True)

    return transcript_text.strip(), timestamps


def ai_call(prompt, ai_config, max_tokens=1000):
    """Call Groq or Gemini API. Returns the response text."""
    groq_key = ai_config.get("groq_key", "")
    gemini_key = ai_config.get("gemini_key", "")

    # Try Groq first
    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            resp = client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.7,
            )
            return resp.choices[0].message.content
        except Exception as e:
            print(f"Groq error: {e}")

    # Fallback to Gemini
    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
            resp = model.generate_content(prompt)
            return resp.text
        except Exception as e:
            print(f"Gemini error: {e}")

    return None


def ai_find_highlights(transcript_text, timed_segments, video_title,
                        duration, clip_duration, num_clips, ai_config):
    """Use AI to find the most interesting moments in the video transcript."""
    if not transcript_text or len(transcript_text) < 50:
        return None

    # Truncate transcript if too long (keep under ~8K tokens)
    max_chars = 12000
    if len(transcript_text) > max_chars:
        transcript_text = transcript_text[:max_chars] + "..."

    prompt = f"""You are a viral content expert. Analyze this YouTube video transcript and find the {num_clips} most interesting, engaging, or viral-worthy moments.

Video Title: "{video_title}"
Video Duration: {duration:.0f} seconds
Desired clip duration: {clip_duration} seconds each

Transcript:
{transcript_text}

Return ONLY a JSON array with exactly {num_clips} objects. Each object must have:
- "start": start time in seconds (number)
- "reason": why this moment is interesting (string, max 15 words)

Rules:
- Moments should be at least 15 seconds apart from each other
- Avoid the first 10 seconds (usually intro) and last 10 seconds (usually outro)
- Pick moments with: surprising facts, emotional peaks, funny moments, key insights, dramatic reveals
- Start times must be between 10 and {max(10, duration - clip_duration - 5):.0f}

Return ONLY the JSON array, no other text. Example:
[{{"start": 45, "reason": "Shocking reveal about the main topic"}}, {{"start": 120, "reason": "Hilarious reaction moment"}}]"""

    result = ai_call(prompt, ai_config, max_tokens=800)
    if not result:
        return None

    try:
        # Extract JSON from response
        json_match = re.search(r'\[.*\]', result, re.DOTALL)
        if json_match:
            highlights = json.loads(json_match.group())
            segments = []
            for h in highlights[:num_clips]:
                start = float(h.get("start", 0))
                start = max(0, min(start, duration - clip_duration))
                segments.append({
                    "start": start,
                    "duration": clip_duration,
                    "reason": h.get("reason", ""),
                    "score": 90  # AI-selected = high score
                })
            return segments
    except (json.JSONDecodeError, KeyError):
        pass

    return None




# ──────────────────────────────────────
# API Key Config
# ──────────────────────────────────────

@app.route(f"{URL_PREFIX}/api/config", methods=["POST"])
def save_config():
    """Save/validate AI API keys."""
    data = request.json
    groq_key = data.get("groq_key", "").strip()
    gemini_key = data.get("gemini_key", "").strip()

    # Quick validation
    status = {"groq": False, "gemini": False}

    if groq_key:
        try:
            from groq import Groq
            client = Groq(api_key=groq_key)
            client.chat.completions.create(
                model="llama-3.3-70b-versatile",
                messages=[{"role": "user", "content": "Say OK"}],
                max_tokens=5
            )
            status["groq"] = True
        except Exception:
            status["groq"] = False

    if gemini_key:
        try:
            import google.generativeai as genai
            genai.configure(api_key=gemini_key)
            model = genai.GenerativeModel("gemini-2.0-flash")
            model.generate_content("Say OK")
            status["gemini"] = True
        except Exception:
            status["gemini"] = False

    return jsonify(status)


# ──────────────────────────────────────
# EDITOR API Routes
# ──────────────────────────────────────

EDITOR_UPLOADS = BASE_DIR / "editor_uploads"
EDITOR_UPLOADS.mkdir(exist_ok=True)

editor_jobs = {}


@app.route(f"{URL_PREFIX}/api/editor/upload", methods=["POST"])
def editor_upload():
    """Upload video clips for the editor."""
    if 'files' not in request.files:
        return jsonify({"error": "No files uploaded"}), 400

    files = request.files.getlist('files')
    if not files:
        return jsonify({"error": "No files selected"}), 400

    clips = []
    for f in files:
        if not f.filename:
            continue
        clip_id = str(uuid.uuid4())[:8]
        ext = Path(f.filename).suffix or '.mp4'
        safe_name = f"{clip_id}{ext}"
        filepath = EDITOR_UPLOADS / safe_name
        f.save(str(filepath))

        # Get video info with ffprobe
        duration = 0
        width = 0
        height = 0
        try:
            probe = subprocess.run(
                ["ffprobe", "-v", "quiet", "-print_format", "json",
                 "-show_format", "-show_streams", str(filepath)],
                capture_output=True, text=True, timeout=30
            )
            info = json.loads(probe.stdout)
            duration = float(info.get("format", {}).get("duration", 0))
            for s in info.get("streams", []):
                if s.get("codec_type") == "video":
                    width = int(s.get("width", 0))
                    height = int(s.get("height", 0))
                    break
        except Exception:
            pass

        clips.append({
            "id": clip_id,
            "filename": safe_name,
            "original_name": f.filename,
            "duration": round(duration, 2),
            "width": width,
            "height": height,
            "path": str(filepath)
        })

    return jsonify({"clips": clips})


@app.route(f"{URL_PREFIX}/api/editor/detect-silence", methods=["POST"])
def detect_silence():
    """Detect silent (non-speaking) parts in a video clip using ffmpeg silencedetect."""
    data = request.json
    filename = data.get("filename", "")
    noise_db = int(data.get("noise_db", -30))
    min_silence = float(data.get("min_silence", 0.5))

    filepath = EDITOR_UPLOADS / filename
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    # Get duration
    duration = 0
    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(filepath)],
            capture_output=True, text=True, timeout=30
        )
        info = json.loads(probe.stdout)
        duration = float(info.get("format", {}).get("duration", 0))
    except Exception:
        return jsonify({"error": "Could not read file"}), 500

    # Run silencedetect
    cmd = [
        "ffmpeg", "-i", str(filepath),
        "-af", f"silencedetect=noise={noise_db}dB:d={min_silence}",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    stderr = result.stderr

    # Parse silence intervals
    silence_starts = []
    silence_ends = []
    for line in stderr.split('\n'):
        if 'silence_start:' in line:
            match = re.search(r'silence_start:\s*([\d.]+)', line)
            if match:
                silence_starts.append(float(match.group(1)))
        if 'silence_end:' in line:
            match = re.search(r'silence_end:\s*([\d.]+)', line)
            if match:
                silence_ends.append(float(match.group(1)))

    # Build speaking intervals (inverse of silence)
    speaking = []
    cursor = 0.0

    for i, s_start in enumerate(silence_starts):
        if s_start > cursor + 0.1:
            speaking.append({"start": round(cursor, 2), "end": round(s_start, 2)})
        if i < len(silence_ends):
            cursor = silence_ends[i]

    if cursor < duration - 0.1:
        speaking.append({"start": round(cursor, 2), "end": round(duration, 2)})

    # If no silence found, return the whole clip
    if not speaking:
        speaking = [{"start": 0, "end": round(duration, 2)}]

    total_speaking = sum(s["end"] - s["start"] for s in speaking)
    total_silence = duration - total_speaking

    return jsonify({
        "speaking_segments": speaking,
        "total_duration": round(duration, 2),
        "speaking_duration": round(total_speaking, 2),
        "silence_removed": round(total_silence, 2),
        "silence_count": len(silence_starts)
    })


@app.route(f"{URL_PREFIX}/api/editor/merge", methods=["POST"])
def editor_merge():
    """Merge clips with edits: trim, crop, rotate, volume, noise reduction."""
    import threading

    data = request.json
    clips = data.get("clips", [])
    noise_reduction = data.get("noise_reduction", False)
    noise_strength = int(data.get("noise_strength", 15))
    output_resolution = data.get("output_resolution", "1920:1080")
    precap_text = data.get("precap_text", "").strip()
    precap_duration = float(data.get("precap_duration", 3))
    outro_text = data.get("outro_text", "").strip()
    outro_duration = float(data.get("outro_duration", 3))

    if not clips:
        return jsonify({"error": "No clips provided"}), 400

    job_id = str(uuid.uuid4())[:8]
    editor_jobs[job_id] = {
        "status": "processing",
        "progress": 0,
        "error": None,
        "output_file": None
    }

    def process_merge():
        try:
            processed_files = []
            total = len(clips)

            for i, clip in enumerate(clips):
                editor_jobs[job_id]["progress"] = int((i / total) * 80)

                src = EDITOR_UPLOADS / clip["filename"]
                if not src.exists():
                    raise FileNotFoundError(f"Clip not found: {clip['filename']}")

                out_name = f"{job_id}_proc_{i}.mp4"
                out_path = DOWNLOADS_DIR / out_name

                # Build ffmpeg filter chain
                vfilters = []
                afilters = []

                # 1. Trim
                trim_start = float(clip.get("trim_start", 0))
                trim_end = float(clip.get("trim_end", 0))

                # 2. Cut middle (remove a section)
                cut_from = float(clip.get("cut_from", 0))
                cut_to = float(clip.get("cut_to", 0))

                # 3. Crop
                crop = clip.get("crop", "none")
                if crop and crop != "none":
                    ratio_map = {
                        "16:9": "min(iw\\,ih*16/9):min(ih\\,iw*9/16)",
                        "9:16": "min(iw\\,ih*9/16):min(ih\\,iw*16/9)",
                        "1:1": "min(iw\\,ih):min(iw\\,ih)",
                        "4:3": "min(iw\\,ih*4/3):min(ih\\,iw*3/4)"
                    }
                    if crop in ratio_map:
                        vfilters.append(f"crop={ratio_map[crop]}")

                # 4. Rotate
                rotate = int(clip.get("rotate", 0))
                if rotate == 90:
                    vfilters.append("transpose=1")
                elif rotate == 180:
                    vfilters.append("transpose=1,transpose=1")
                elif rotate == 270:
                    vfilters.append("transpose=2")

                # 5. Scale to output resolution
                if output_resolution and output_resolution != "original":
                    vfilters.append(f"scale={output_resolution}:force_original_aspect_ratio=decrease:flags=lanczos")
                    vfilters.append(f"pad={output_resolution}:(ow-iw)/2:(oh-ih)/2:color=black")

                # 6. Volume
                volume = float(clip.get("volume", 100)) / 100.0
                if volume != 1.0:
                    afilters.append(f"volume={volume}")

                # 7. Noise reduction (global)
                if noise_reduction:
                    afilters.append(f"afftdn=nf=-{noise_strength}")

                # Handle cut from middle
                if cut_from > 0 and cut_to > 0 and cut_to > cut_from:
                    # Split into two parts and concat
                    vf = ",".join(vfilters) if vfilters else "null"
                    af = ",".join(afilters) if afilters else "anull"

                    part1 = DOWNLOADS_DIR / f"{job_id}_part1_{i}.mp4"
                    part2 = DOWNLOADS_DIR / f"{job_id}_part2_{i}.mp4"

                    # Part 1: start to cut_from
                    cmd1 = ["ffmpeg", "-y", "-i", str(src)]
                    if trim_start > 0:
                        cmd1 += ["-ss", str(trim_start)]
                    cmd1 += ["-to", str(cut_from - trim_start)]
                    cmd1 += ["-vf", vf, "-af", af,
                             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                             "-c:a", "aac", "-b:a", "192k", str(part1)]

                    # Part 2: cut_to to end
                    cmd2 = ["ffmpeg", "-y", "-i", str(src),
                            "-ss", str(cut_to)]
                    if trim_end > 0:
                        cmd2 += ["-to", str(trim_end - cut_to)]
                    cmd2 += ["-vf", vf, "-af", af,
                             "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                             "-c:a", "aac", "-b:a", "192k", str(part2)]

                    subprocess.run(cmd1, capture_output=True, timeout=300)
                    subprocess.run(cmd2, capture_output=True, timeout=300)

                    # Concat the two parts
                    concat_file = DOWNLOADS_DIR / f"{job_id}_concat_{i}.txt"
                    concat_file.write_text(f"file '{part1}'\nfile '{part2}'\n")

                    cmd3 = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                            "-i", str(concat_file),
                            "-c", "copy", str(out_path)]
                    subprocess.run(cmd3, capture_output=True, timeout=300)

                    # Cleanup
                    part1.unlink(missing_ok=True)
                    part2.unlink(missing_ok=True)
                    concat_file.unlink(missing_ok=True)
                else:
                    # Normal processing
                    vf = ",".join(vfilters) if vfilters else "null"
                    af = ",".join(afilters) if afilters else "anull"

                    cmd = ["ffmpeg", "-y", "-i", str(src)]
                    if trim_start > 0:
                        cmd += ["-ss", str(trim_start)]
                    if trim_end > 0:
                        cmd += ["-to", str(trim_end - trim_start)]
                    cmd += ["-vf", vf, "-af", af,
                            "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
                            "-c:a", "aac", "-b:a", "192k",
                            str(out_path)]

                    result = subprocess.run(cmd, capture_output=True,
                                            text=True, timeout=300)
                    if result.returncode != 0:
                        raise RuntimeError(
                            f"ffmpeg error on clip {i+1}: {result.stderr[-500:]}")

                # ── Chroma Key Overlay ──
                overlay_data = clip.get("overlay")
                if overlay_data and out_path.exists():
                    overlay_src = EDITOR_UPLOADS / overlay_data["filename"]
                    if overlay_src.exists():
                        ovr_out = DOWNLOADS_DIR / f"{job_id}_ovr_{i}.mp4"
                        key_color = overlay_data.get("color", "#00FF00")
                        # Convert hex to 0xRRGGBB for ffmpeg
                        if key_color.startswith("#"):
                            key_color = "0x" + key_color[1:]
                        similarity = float(overlay_data.get("similarity", 0.3))
                        blend_val = float(overlay_data.get("blend", 0.1))

                        # Use chromakey on overlay, then composite onto base
                        filter_complex = (
                            f"[1:v]chromakey={key_color}:{similarity}:{blend_val},"
                            f"scale=iw:ih:force_original_aspect_ratio=decrease[ovr];"
                            f"[0:v][ovr]overlay=(W-w)/2:(H-h)/2:shortest=1[out]"
                        )

                        cmd = [
                            "ffmpeg", "-y",
                            "-i", str(out_path),
                            "-i", str(overlay_src),
                            "-filter_complex", filter_complex,
                            "-map", "[out]", "-map", "0:a?",
                            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                            "-c:a", "aac", "-b:a", "192k",
                            "-pix_fmt", "yuv420p",
                            str(ovr_out)
                        ]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                        if result.returncode == 0 and ovr_out.exists():
                            out_path.unlink(missing_ok=True)
                            ovr_out.rename(out_path)
                            print(f"Chroma key overlay applied to clip {i+1}")
                        else:
                            print(f"Chroma key error: {result.stderr[-300:]}")

                processed_files.append(out_path)

            # Final merge: concat all processed clips
            editor_jobs[job_id]["progress"] = 85

            # Generate precap/outro text overlay clips if provided
            res = output_resolution if output_resolution != "original" else "1920:1080"
            res_w, res_h = res.split(":")
            w, h = int(res_w), int(res_h)

            def create_text_clip(text, duration, out_path, label="PRECAP"):
                """Create a video clip with styled text using Pillow + ffmpeg."""
                try:
                    from PIL import Image, ImageDraw, ImageFont

                    # Create dark gradient image
                    img = Image.new('RGB', (w, h), (8, 8, 18))
                    draw = ImageDraw.Draw(img)

                    # Draw subtle radial gradient overlay
                    for i in range(h):
                        alpha = int(20 * (1 - abs(i - h/2) / (h/2)))
                        draw.line([(0, i), (w, i)], fill=(alpha, alpha, alpha+5))

                    # Try to load a nice font, fallback to default
                    font_size = max(28, min(60, w // 20))
                    label_size = max(14, font_size // 3)
                    try:
                        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", font_size)
                        label_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", label_size)
                    except Exception:
                        try:
                            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
                            label_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", label_size)
                        except Exception:
                            font = ImageFont.load_default()
                            label_font = font

                    # Draw label (e.g. "PRECAP" or "COMING UP")
                    lbox = draw.textbbox((0, 0), label, font=label_font)
                    lw = lbox[2] - lbox[0]
                    draw.text(((w - lw) // 2, h // 2 - font_size - label_size - 10),
                              label, font=label_font, fill=(120, 120, 180))

                    # Draw main text (word-wrap if needed)
                    words = text.split()
                    lines = []
                    current_line = ""
                    max_text_w = w - 120
                    for word in words:
                        test = f"{current_line} {word}".strip()
                        tbox = draw.textbbox((0, 0), test, font=font)
                        if tbox[2] - tbox[0] > max_text_w and current_line:
                            lines.append(current_line)
                            current_line = word
                        else:
                            current_line = test
                    if current_line:
                        lines.append(current_line)

                    total_text_h = len(lines) * (font_size + 8)
                    y_start = h // 2 - total_text_h // 2 + 10

                    for i, line in enumerate(lines):
                        bbox = draw.textbbox((0, 0), line, font=font)
                        tw = bbox[2] - bbox[0]
                        x = (w - tw) // 2
                        y = y_start + i * (font_size + 8)
                        # Shadow
                        draw.text((x + 2, y + 2), line, font=font, fill=(30, 30, 50))
                        # Main text
                        draw.text((x, y), line, font=font, fill=(255, 255, 255))

                    # Draw decorative line under text
                    line_y = y_start + total_text_h + 20
                    line_w = min(200, w // 4)
                    draw.line([(w//2 - line_w//2, line_y), (w//2 + line_w//2, line_y)],
                              fill=(108, 92, 231), width=3)

                    # Save frame as PNG
                    frame_path = out_path.with_suffix('.png')
                    img.save(str(frame_path))

                    # Convert to video with ffmpeg
                    cmd = [
                        "ffmpeg", "-y",
                        "-loop", "1", "-i", str(frame_path),
                        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo",
                        "-t", str(duration),
                        "-c:v", "libx264", "-preset", "fast",
                        "-tune", "stillimage", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "128k",
                        "-shortest", str(out_path)
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    frame_path.unlink(missing_ok=True)

                    if result.returncode != 0:
                        print(f"Text clip ffmpeg error: {result.stderr[-300:]}")
                        return False
                    return out_path.exists()

                except Exception as e:
                    print(f"Text clip error: {e}")
                    return False

            if precap_text:
                precap_file = DOWNLOADS_DIR / f"{job_id}_precap.mp4"
                if create_text_clip(precap_text, precap_duration, precap_file, "📌 PRECAP"):
                    processed_files.insert(0, precap_file)

            if outro_text:
                outro_file = DOWNLOADS_DIR / f"{job_id}_outro.mp4"
                if create_text_clip(outro_text, outro_duration, outro_file, "🔚 COMING UP"):
                    processed_files.append(outro_file)

            # Final merge
            final_output = DOWNLOADS_DIR / f"{job_id}_merged.mp4"

            if len(processed_files) == 1:
                shutil.move(str(processed_files[0]), str(final_output))
            else:
                concat_list = DOWNLOADS_DIR / f"{job_id}_final_concat.txt"
                with open(concat_list, 'w') as f:
                    for pf in processed_files:
                        f.write(f"file '{pf}'\n")

                cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                       "-i", str(concat_list),
                       "-c", "copy", str(final_output)]
                result = subprocess.run(cmd, capture_output=True,
                                        text=True, timeout=600)

                if result.returncode != 0:
                    raise RuntimeError(f"Merge failed: {result.stderr[-500:]}")

                for pf in processed_files:
                    pf.unlink(missing_ok=True)
                concat_list.unlink(missing_ok=True)

            editor_jobs[job_id]["status"] = "done"
            editor_jobs[job_id]["progress"] = 100
            editor_jobs[job_id]["output_file"] = f"{job_id}_merged.mp4"

        except Exception as e:
            editor_jobs[job_id]["status"] = "error"
            editor_jobs[job_id]["error"] = str(e)

    thread = threading.Thread(target=process_merge, daemon=True)
    thread.start()
    return jsonify({"job_id": job_id, "status": "processing"})


@app.route(f"{URL_PREFIX}/api/editor/status/<job_id>")
def editor_status(job_id):
    """Check merge job status."""
    if job_id not in editor_jobs:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(editor_jobs[job_id])


@app.route(f"{URL_PREFIX}/api/editor/preview/<job_id>")
def editor_preview(job_id):
    """Stream the merged video."""
    if job_id not in editor_jobs:
        return jsonify({"error": "Job not found"}), 404
    job = editor_jobs[job_id]
    if job["status"] != "done" or not job.get("output_file"):
        return jsonify({"error": "Video not ready"}), 400
    filepath = DOWNLOADS_DIR / job["output_file"]
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(str(filepath), mimetype='video/mp4')


# ──────────────────────────────────────
# API Routes
# ──────────────────────────────────────

@app.route(f"{URL_PREFIX}/api/analyze", methods=["POST"])
def analyze_video():
    """Step 1: Start background job to download and analyze video."""
    import threading

    data = request.json
    url = data.get("url", "").strip()
    num_clips = int(data.get("num_clips", 5))
    clip_duration = int(data.get("clip_duration", 12))
    ai_config = {
        "groq_key": data.get("groq_key", ""),
        "gemini_key": data.get("gemini_key", "")
    }
    has_ai = bool(ai_config.get("groq_key") or ai_config.get("gemini_key"))

    if not url:
        return jsonify({"error": "No URL provided"}), 400

    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {"status": "starting", "progress": 0}

    def run_analysis():
        try:
            # Get video info
            jobs[job_id]["status"] = "fetching_info"
            jobs[job_id]["progress"] = 5
            info = get_video_info(url)
            title = info.get("title", "Unknown")
            thumbnail = info.get("thumbnail", "")
            video_duration = info.get("duration", 0)

            jobs[job_id].update({
                "title": title,
                "thumbnail": thumbnail,
                "video_duration": video_duration
            })

            # Download
            jobs[job_id]["status"] = "downloading"
            jobs[job_id]["progress"] = 15
            filepath = download_video(url, job_id)
            jobs[job_id]["filepath"] = filepath
            jobs[job_id]["progress"] = 50

            # Try AI-powered analysis if keys provided
            ai_segments = None
            timed_transcript = []
            transcript_text = ""

            if has_ai:
                jobs[job_id]["status"] = "extracting_transcript"
                jobs[job_id]["progress"] = 55
                transcript_text, timed_transcript = extract_transcript(url, job_id)

                if transcript_text:
                    jobs[job_id]["status"] = "ai_analyzing"
                    jobs[job_id]["progress"] = 70
                    ai_segments = ai_find_highlights(
                        transcript_text, timed_transcript, title,
                        video_duration, clip_duration, num_clips, ai_config
                    )

            # Store transcript data for later use in generate
            jobs[job_id]["transcript_text"] = transcript_text
            jobs[job_id]["timed_transcript"] = timed_transcript
            jobs[job_id]["ai_config"] = ai_config
            jobs[job_id]["url"] = url

            if ai_segments:
                # AI found highlights
                segments = []
                for i, seg in enumerate(ai_segments):
                    segments.append({
                        "id": i + 1,
                        "start": round(seg["start"], 1),
                        "end": round(seg["start"] + seg["duration"], 1),
                        "duration": seg["duration"],
                        "score": seg.get("score", 90),
                        "label": f"🤖 {seg.get('reason', 'AI-selected highlight')}"
                    })
            else:
                # Fallback: audio energy analysis
                jobs[job_id]["status"] = "analyzing_audio"
                jobs[job_id]["progress"] = 55
                energies, duration = analyze_audio_energy(filepath, segment_duration=2.0)
                jobs[job_id]["progress"] = 75

                jobs[job_id]["status"] = "detecting_scenes"
                jobs[job_id]["progress"] = 80
                scene_changes = detect_scene_changes(filepath)
                jobs[job_id]["progress"] = 90

                jobs[job_id]["status"] = "finding_highlights"
                highlights = find_highlight_segments(
                    energies, duration, scene_changes,
                    clip_duration=clip_duration,
                    num_clips=num_clips,
                    min_gap=max(15, clip_duration + 5)
                )

                segments = []
                for i, (start, end, score) in enumerate(highlights):
                    segments.append({
                        "id": i + 1,
                        "start": round(start, 1),
                        "end": round(end, 1),
                        "duration": round(end - start, 1),
                        "score": round(score, 1),
                        "label": f"Highlight #{i+1}"
                    })

            jobs[job_id].update({
                "status": "analyzed",
                "progress": 100,
                "segments": segments,
                "ai_used": ai_segments is not None
            })

        except Exception as e:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = str(e)

    thread = threading.Thread(target=run_analysis, daemon=True)
    thread.start()

    return jsonify({"job_id": job_id, "status": "started"})


@app.route(f"{URL_PREFIX}/api/generate", methods=["POST"])
def generate_shorts():
    """Step 2: Generate clips with crop position, thumbnails, titles & hashtags."""
    data = request.json
    job_id = data.get("job_id")
    segments = data.get("segments", [])

    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404

    job = jobs[job_id]
    filepath = job.get("filepath")
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "Source video not found"}), 404

    video_title = job.get("title", "Video")
    job["status"] = "generating"
    job["progress"] = 0

    generated = []
    total = len(segments)

    try:
        for i, seg in enumerate(segments):
            start = float(seg["start"])
            duration = float(seg["duration"])
            crop_pos = int(seg.get("crop_position", 50))
            clip_name = f"{job_id}_short_{i+1}.mp4"
            thumb_name = f"{job_id}_thumb_{i+1}.jpg"
            output_path = str(DOWNLOADS_DIR / clip_name)
            thumb_path = str(DOWNLOADS_DIR / thumb_name)

            # Generate the clip
            generate_short_clip(filepath, output_path, start, duration,
                                crop_position=crop_pos)

            # Extract thumbnail
            extract_thumbnail(filepath, thumb_path, start,
                              crop_position=crop_pos)

            # Generate title, description and hashtags (AI-powered if keys available)
            transcript_seg = ""
            ai_cfg = job.get("ai_config")
            timed = job.get("timed_transcript", [])
            if timed:
                transcript_seg = get_transcript_for_segment(timed, start, duration)

            title, description, hashtags = generate_title_and_hashtags(
                video_title, i + 1, start, duration,
                transcript_segment=transcript_seg,
                ai_config=ai_cfg)

            generated.append({
                "id": i + 1,
                "filename": clip_name,
                "start": seg["start"],
                "duration": seg["duration"],
                "crop_position": crop_pos,
                "download_url": f"{URL_PREFIX}/api/download/{clip_name}",
                "thumbnail_url": f"{URL_PREFIX}/api/download/{thumb_name}",
                "title": title,
                "description": description,
                "hashtags": hashtags
            })

            job["progress"] = int(((i + 1) / total) * 100)

        job["status"] = "complete"
        job["progress"] = 100
        job["generated"] = generated

        return jsonify({"status": "complete", "clips": generated})

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        return jsonify({"error": str(e)}), 500


@app.route(f"{URL_PREFIX}/api/preview/<job_id>")
def preview_video(job_id):
    """Stream the downloaded source video for preview."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    filepath = jobs[job_id].get("filepath")
    if not filepath or not os.path.exists(filepath):
        return jsonify({"error": "Video not found"}), 404
    return send_file(filepath, mimetype='video/mp4')


@app.route(f"{URL_PREFIX}/api/youtube/auth", methods=["POST"])
def youtube_auth():
    """Start YouTube OAuth2 flow."""
    import signal
    data = request.json
    client_id = data.get("client_id", "").strip()
    client_secret = data.get("client_secret", "").strip()

    if not client_id or not client_secret:
        return jsonify({"error": "Client ID and Secret required"}), 400

    # Clear any previous auth state
    app.config.pop("YT_AUTH_ERROR", None)
    app.config.pop("YT_CREDENTIALS", None)
    app.config["YT_CLIENT_ID"] = client_id
    app.config["YT_CLIENT_SECRET"] = client_secret

    OAUTH_PORT = 8585

    # Kill any leftover process on the OAuth port
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{OAUTH_PORT}"],
            capture_output=True, text=True, timeout=5
        )
        if result.stdout.strip():
            for pid in result.stdout.strip().split('\n'):
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except Exception:
                    pass
            import time
            time.sleep(0.5)
    except Exception:
        pass

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        import threading

        client_config = {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [f"http://localhost:{OAUTH_PORT}"]
            }
        }

        flow = InstalledAppFlow.from_client_config(
            client_config,
            scopes=["https://www.googleapis.com/auth/youtube.upload"]
        )

        def run_flow():
            try:
                creds = flow.run_local_server(
                    port=OAUTH_PORT,
                    open_browser=True,
                    success_message="✅ Authorization complete! You can close this tab and go back to ShortsCut AI."
                )
                app.config["YT_CREDENTIALS"] = creds
            except Exception as e:
                app.config["YT_AUTH_ERROR"] = str(e)

        thread = threading.Thread(target=run_flow, daemon=True)
        thread.start()

        return jsonify({
            "status": "auth_started",
            "message": "Check your browser to authorize",
            "redirect_uri": f"http://localhost:{OAUTH_PORT}"
        })

    except ImportError:
        return jsonify({"error": "google-auth-oauthlib not installed. Run: pip install google-auth-oauthlib google-api-python-client"}), 500
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route(f"{URL_PREFIX}/api/youtube/status")
def youtube_status():
    """Check if YouTube is authenticated."""
    creds = app.config.get("YT_CREDENTIALS")
    error = app.config.get("YT_AUTH_ERROR")
    if error:
        return jsonify({"authenticated": False, "error": error})
    if creds and creds.valid:
        return jsonify({"authenticated": True})
    return jsonify({"authenticated": False})


@app.route(f"{URL_PREFIX}/api/youtube/upload", methods=["POST"])
def youtube_upload():
    """Upload a generated short to YouTube."""
    creds = app.config.get("YT_CREDENTIALS")
    if not creds or not creds.valid:
        return jsonify({"error": "Not authenticated with YouTube"}), 401

    data = request.json
    filename = data.get("filename", "")
    title = data.get("title", "Short Video")
    description = data.get("description", "")
    tags = data.get("tags", [])

    filepath = DOWNLOADS_DIR / filename
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        youtube = build("youtube", "v3", credentials=creds)

        body = {
            "snippet": {
                "title": title[:100],
                "description": description[:5000],
                "tags": tags[:30],
                "categoryId": "22"
            },
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
                "shorts": {"shortsEligibility": "ELIGIBLE"}
            }
        }

        media = MediaFileUpload(
            str(filepath), mimetype="video/mp4", resumable=True
        )

        req = youtube.videos().insert(
            part="snippet,status", body=body, media_body=media
        )

        response = None
        while response is None:
            status, response = req.next_chunk()

        video_id = response.get("id")
        return jsonify({
            "status": "uploaded",
            "video_id": video_id,
            "url": f"https://youtube.com/shorts/{video_id}"
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route(f"{URL_PREFIX}/api/download/<filename>")
def download_file(filename):
    """Download a generated clip."""
    filepath = DOWNLOADS_DIR / filename
    if not filepath.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(str(filepath), as_attachment=True, download_name=filename)


@app.route(f"{URL_PREFIX}/api/status/<job_id>")
def job_status(job_id):
    """Check job status."""
    if job_id not in jobs:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(jobs[job_id])


@app.route(f"{URL_PREFIX}/api/cleanup/<job_id>", methods=["POST"])
def cleanup(job_id):
    """Clean up temp files for a job."""
    for f in TEMP_DIR.glob(f"{job_id}.*"):
        f.unlink(missing_ok=True)
    return jsonify({"status": "cleaned"})


@app.route("/")
@app.route("/index.html")
@app.route("/static/index.html")
@app.route(f"{URL_PREFIX}")
@app.route(f"{URL_PREFIX}/")
def root_redirect():
    return redirect(f"{URL_PREFIX}/static/index.html")


@app.route(f"{URL_PREFIX}/static/index.html")
def index():
    return send_file(BASE_DIR / "static" / "index.html")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5555))
    print(f"🎬 YouTube Shorts Generator running at http://localhost:{port}")
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
