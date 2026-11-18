// ============================================================
// ShortsCut AI — Frontend Logic v2
// Preview → Edit → Generate → Results + YouTube Upload
// ============================================================

// API URL: always use same origin (works for localhost, tunnel, or any deployment)
const API = window.location.origin + '/email/video/shorts-generator/api';
const $ = (s) => document.querySelector(s);

// State
let currentJobId = null;
let segments = [];
let ytAuthenticated = false;

// AI Config (stored in localStorage)
function getAIKeys() {
  return {
    groq_key: localStorage.getItem('groq_key') || '',
    gemini_key: localStorage.getItem('gemini_key') || ''
  };
}

function hasAIKeys() {
  const keys = getAIKeys();
  return !!(keys.groq_key || keys.gemini_key);
}

function updateAIBadge() {
  const badge = document.getElementById('aiBadge');
  if (badge) badge.style.display = hasAIKeys() ? 'block' : 'none';
}

// DOM refs
const urlInput       = $('#urlInput');
const analyzeBtn     = $('#analyzeBtn');
const progressSection = $('#progressSection');
const progressLabel  = $('#progressLabel');
const progressPct    = $('#progressPct');
const progressFill   = $('#progressFill');
const statusLog      = $('#statusLog');
const step2          = $('#step2');
const videoThumb     = $('#videoThumb');
const videoTitle     = $('#videoTitle');
const videoDuration  = $('#videoDuration');
const previewPlayer  = $('#previewPlayer');
const timelineBar    = $('#timelineBar');
const step3          = $('#step3');
const segmentsList   = $('#segmentsList');
const generateBtn    = $('#generateBtn');
const genProgressSection = $('#genProgressSection');
const genProgressLabel = $('#genProgressLabel');
const genProgressPct = $('#genProgressPct');
const genProgressFill = $('#genProgressFill');
const step4          = $('#step4');
const resultsGrid    = $('#resultsGrid');
const toastBox       = $('#toastBox');

// YouTube Modal
const ytConnectBtn   = $('#ytConnectBtn');
const ytBtnText      = $('#ytBtnText');
const ytModal        = $('#ytModal');
const ytModalClose   = $('#ytModalClose');
const ytAuthBtn      = $('#ytAuthBtn');

// ── Toast ──
function toast(msg, type = 'info') {
  const icons = { info: 'ℹ️', success: '✅', error: '❌' };
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${icons[type]||''}</span> ${msg}`;
  toastBox.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    el.style.transform = 'translateX(30px)';
    el.style.transition = 'all 0.3s';
    setTimeout(() => el.remove(), 300);
  }, 4000);
}

// ── Helpers ──
function formatTime(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function log(msg) {
  statusLog.textContent += msg + '\n';
  statusLog.scrollTop = statusLog.scrollHeight;
}

function setProgress(fill, label, pct, labelText, pctVal) {
  fill.style.width = `${pctVal}%`;
  pct.textContent = `${pctVal}%`;
  label.textContent = labelText;
}

// ── Status label mapping ──
const STATUS_LABELS = {
  starting: '🚀 Starting up...',
  fetching_info: '📡 Fetching video info from YouTube...',
  downloading: '⬇️ Downloading video (this may take a few minutes)...',
  analyzing_audio: '🔊 Analyzing audio energy levels...',
  detecting_scenes: '🎬 Detecting scene changes...',
  finding_highlights: '🔍 Finding best highlight moments...',
  analyzed: '✅ Analysis complete!',
  error: '❌ Error occurred',
};

// ═══════════════════════════════════════
// STEP 1: Analyze
// ═══════════════════════════════════════
analyzeBtn.addEventListener('click', async () => {
  const url = urlInput.value.trim();
  if (!url) { toast('Please paste a YouTube URL', 'error'); return; }

  analyzeBtn.disabled = true;
  progressSection.classList.add('active');
  step2.classList.remove('active');
  step3.classList.remove('active');
  step4.classList.remove('active');
  statusLog.textContent = '';
  setProgress(progressFill, progressLabel, progressPct, 'Connecting to server...', 0);
  log('🚀 Starting analysis...');

  try {
    const aiKeys = getAIKeys();
    log(aiKeys.groq_key || aiKeys.gemini_key ? '🤖 AI-powered analysis...' : '📡 Sending URL to server...');
    
    let res;
    try {
      res = await fetch(`${API}/analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url,
          num_clips: +$('#numClips').value,
          clip_duration: +$('#clipDuration').value,
          ...aiKeys
        })
      });
    } catch (fetchErr) {
      throw new Error('Cannot reach the server. Make sure the server is running on this machine.');
    }

    // Check if response is JSON
    const contentType = res.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      const text = await res.text();
      console.error('Non-JSON response:', text.substring(0, 200));
      throw new Error('Server returned an error page. Make sure the Flask server is running (python3.11 server.py)');
    }

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Failed to start analysis');
    }

    const data = await res.json();
    currentJobId = data.job_id;
    log(`🆔 Job started: ${currentJobId}`);
    await pollJobStatus(currentJobId);

  } catch (err) {
    log(`❌ Error: ${err.message}`);
    toast(err.message, 'error');
    setProgress(progressFill, progressLabel, progressPct, 'Failed', 0);
    analyzeBtn.disabled = false;
  }
});

async function pollJobStatus(jobId) {
  let lastStatus = '';
  let videoDur = 0;

  while (true) {
    await new Promise(r => setTimeout(r, 3000));

    try {
      const res = await fetch(`${API}/status/${jobId}`);
      if (!res.ok) throw new Error('Failed to check status');

      const job = await res.json();
      const statusText = STATUS_LABELS[job.status] || job.status;
      setProgress(progressFill, progressLabel, progressPct, statusText, job.progress || 0);

      if (job.status !== lastStatus) {
        log(statusText);
        lastStatus = job.status;
      }

      if (job.video_duration) videoDur = job.video_duration;

      // Done!
      if (job.status === 'analyzed') {
        segments = job.segments;
        log(`🔍 Found ${segments.length} highlight segments`);

        // Show step 2: Preview
        showPreview(job, videoDur);
        // Show step 3: Edit
        renderSegments();
        step3.classList.add('active');

        toast(`Found ${segments.length} highlight moments!`, 'success');
        analyzeBtn.disabled = false;
        return;
      }

      if (job.status === 'error') {
        throw new Error(job.error || 'Analysis failed');
      }

    } catch (err) {
      log(`❌ Error: ${err.message}`);
      toast(err.message, 'error');
      setProgress(progressFill, progressLabel, progressPct, 'Failed', 0);
      analyzeBtn.disabled = false;
      return;
    }
  }
}

// ═══════════════════════════════════════
// STEP 2: Video Preview
// ═══════════════════════════════════════
function showPreview(job, duration) {
  // Video info
  videoThumb.src = job.thumbnail || '';
  videoTitle.textContent = job.title || 'Video';
  videoDuration.textContent = `Duration: ${formatTime(duration)} · ${segments.length} highlights detected`;

  // Set preview player source to the downloaded video
  previewPlayer.src = `${API}/preview/${currentJobId}`;
  previewPlayer.load();

  // Build timeline markers
  renderTimeline(duration);

  step2.classList.add('active');
  step2.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function renderTimeline(duration) {
  const track = timelineBar.querySelector('.timeline-track');
  track.innerHTML = '';

  segments.forEach((seg, i) => {
    const leftPct = (seg.start / duration) * 100;
    const widthPct = (seg.duration / duration) * 100;

    const marker = document.createElement('div');
    marker.className = 'timeline-marker';
    marker.style.left = `${leftPct}%`;
    marker.style.width = `${Math.max(widthPct, 1.5)}%`;
    marker.textContent = i + 1;
    marker.title = `Highlight #${i+1}: ${formatTime(seg.start)} → ${formatTime(seg.start + seg.duration)}`;

    // Click marker to seek video to that point
    marker.addEventListener('click', () => {
      previewPlayer.currentTime = seg.start;
      previewPlayer.play();
    });

    track.appendChild(marker);
  });
}

// ═══════════════════════════════════════
// STEP 3: Edit Segments
// ═══════════════════════════════════════
function renderSegments() {
  segmentsList.innerHTML = '';
  segments.forEach((seg, i) => {
    if (seg.crop_position === undefined) seg.crop_position = 50;

    const el = document.createElement('div');
    el.className = 'segment-item';
    el.innerHTML = `
      <div class="seg-num">${i + 1}</div>
      <div class="seg-info" style="flex:1">
        <div class="seg-edit-row">
          <div class="seg-field">
            <label>Start (sec)</label>
            <input type="number" class="seg-input" data-field="start" value="${seg.start}" step="0.5" min="0">
          </div>
          <div class="seg-field">
            <label>Duration (sec)</label>
            <input type="number" class="seg-input" data-field="duration" value="${seg.duration}" step="0.5" min="3" max="60">
          </div>
          <div class="seg-field">
            <label>Preview</label>
            <button class="seg-preview-btn" title="Jump to this time in video">▶ Play</button>
          </div>
          <div class="seg-field" style="flex:2">
            <label>Frame: <span class="crop-label">${seg.crop_position === 0 ? 'Left' : seg.crop_position === 100 ? 'Right' : seg.crop_position === 50 ? 'Center' : seg.crop_position + '%'}</span></label>
            <input type="range" class="seg-slider" data-field="crop_position" value="${seg.crop_position}" min="0" max="100" step="5">
          </div>
        </div>
        <div class="seg-meta">⚡ Score: ${seg.score} · End: ${formatTime(seg.start + seg.duration)}</div>
      </div>
      <button class="seg-remove" data-idx="${i}" title="Remove">✕</button>
    `;

    // Live-edit handlers
    el.querySelectorAll('.seg-input').forEach(inp => {
      inp.addEventListener('change', () => {
        seg[inp.dataset.field] = parseFloat(inp.value);
        if (inp.dataset.field === 'start') seg.end = seg.start + seg.duration;
        if (inp.dataset.field === 'duration') seg.end = seg.start + seg.duration;
        el.querySelector('.seg-meta').textContent =
          `⚡ Score: ${seg.score} · End: ${formatTime(seg.start + seg.duration)}`;
        // Update timeline
        if (previewPlayer.duration) renderTimeline(previewPlayer.duration);
      });
    });

    // Preview button — seek video player
    el.querySelector('.seg-preview-btn').addEventListener('click', () => {
      previewPlayer.currentTime = seg.start;
      previewPlayer.play();
      step2.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });

    // Crop slider
    const slider = el.querySelector('.seg-slider');
    const cropLabel = el.querySelector('.crop-label');
    slider.addEventListener('input', () => {
      const v = parseInt(slider.value);
      seg.crop_position = v;
      cropLabel.textContent = v === 0 ? 'Left' : v === 100 ? 'Right' : v === 50 ? 'Center' : v + '%';
    });

    // Remove
    el.querySelector('.seg-remove').addEventListener('click', () => {
      segments.splice(i, 1);
      renderSegments();
      if (previewPlayer.duration) renderTimeline(previewPlayer.duration);
      toast('Segment removed', 'info');
    });

    segmentsList.appendChild(el);
  });
}

// ═══════════════════════════════════════
// Generate Shorts
// ═══════════════════════════════════════
generateBtn.addEventListener('click', async () => {
  if (!currentJobId || segments.length === 0) {
    toast('No segments to generate', 'error');
    return;
  }

  generateBtn.disabled = true;
  genProgressSection.classList.add('active');
  step4.classList.remove('active');
  setProgress(genProgressFill, genProgressLabel, genProgressPct, 'Generating 9:16 shorts...', 0);

  try {
    toast('Generating shorts with thumbnails, titles & hashtags...', 'info');

    const res = await fetch(`${API}/generate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        job_id: currentJobId,
        segments: segments.map(s => ({
          start: s.start,
          duration: s.duration,
          crop_position: s.crop_position || 50
        }))
      })
    });

    if (!res.ok) {
      const err = await res.json();
      throw new Error(err.error || 'Generation failed');
    }

    const data = await res.json();
    setProgress(genProgressFill, genProgressLabel, genProgressPct, 'Complete!', 100);

    renderResults(data.clips);
    step4.classList.add('active');
    step4.scrollIntoView({ behavior: 'smooth', block: 'start' });
    toast(`${data.clips.length} shorts generated! 🎉`, 'success');

  } catch (err) {
    toast(err.message, 'error');
    setProgress(genProgressFill, genProgressLabel, genProgressPct, 'Failed', 0);
  } finally {
    generateBtn.disabled = false;
  }
});

// ═══════════════════════════════════════
// STEP 4: Results with Title, Hashtags, Thumbnail, YouTube Upload
// ═══════════════════════════════════════
function renderResults(clips) {
  resultsGrid.innerHTML = '';
  const base = window.location.origin;

  clips.forEach((clip) => {
    const hashStr = clip.hashtags ? clip.hashtags.join(' ') : '';
    const card = document.createElement('div');
    card.className = 'result-card';
    card.innerHTML = `
      <video src="${base}${clip.download_url}" controls playsinline></video>
      <div class="card-body">
        <div class="result-title-row">
          <h4 class="result-title" contenteditable="true" spellcheck="false">${clip.title || 'Short #' + clip.id}</h4>
          <button class="copy-btn" data-copy="title" title="Copy title">📋</button>
        </div>

        <div class="result-description">
          <p class="desc-text" contenteditable="true" spellcheck="false">${clip.description || ''}</p>
          <button class="copy-btn" data-copy="description" title="Copy description">📋</button>
        </div>

        <div class="result-hashtags">
          <p class="hashtag-text" contenteditable="true" spellcheck="false">${hashStr}</p>
          <button class="copy-btn" data-copy="hashtags" title="Copy hashtags">📋</button>
        </div>

        <div class="result-thumb-row">
          <img src="${base}${clip.thumbnail_url}" alt="thumbnail" class="result-thumb">
          <a class="thumb-dl-btn" href="${base}${clip.thumbnail_url}" download title="Download Thumbnail">
            🖼️ Thumbnail
          </a>
        </div>

        <p class="result-meta">From ${formatTime(clip.start)} · ${clip.duration}s · Crop: ${clip.crop_position}%</p>

        <a class="dl-btn" href="${base}${clip.download_url}" download>
          ⬇️ Download Short
        </a>

        <button class="yt-upload-btn" data-filename="${clip.filename}" ${!ytAuthenticated ? 'title="Connect YouTube first"' : ''}>
          📺 Upload to YouTube
        </button>
      </div>
    `;

    // Copy handlers
    card.querySelectorAll('.copy-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        let text = '';
        if (btn.dataset.copy === 'title') {
          text = card.querySelector('.result-title').textContent;
        } else if (btn.dataset.copy === 'description') {
          text = card.querySelector('.desc-text').textContent;
        } else {
          text = card.querySelector('.hashtag-text').textContent;
        }
        navigator.clipboard.writeText(text).then(() => {
          toast('Copied to clipboard!', 'success');
          btn.textContent = '✅';
          setTimeout(() => btn.textContent = '📋', 1500);
        });
      });
    });

    // YouTube upload handler
    card.querySelector('.yt-upload-btn').addEventListener('click', async (e) => {
      const btn = e.currentTarget;
      if (!ytAuthenticated) {
        toast('Please connect your YouTube channel first (top-right button)', 'error');
        return;
      }

      btn.disabled = true;
      btn.textContent = '⏳ Uploading...';

      const title = card.querySelector('.result-title').textContent;
      const desc = card.querySelector('.desc-text')?.textContent || '';
      const hashtags = card.querySelector('.hashtag-text').textContent;

      try {
        const res = await fetch(`${API}/youtube/upload`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            filename: btn.dataset.filename,
            title: title,
            description: `${desc}\n\n${hashtags}`,
            tags: hashtags.split(/\s+/).filter(t => t.startsWith('#')).map(t => t.slice(1))
          })
        });

        const data = await res.json();
        if (!res.ok) throw new Error(data.error || 'Upload failed');

        btn.textContent = '✅ Uploaded!';
        btn.classList.add('uploaded');
        toast(`Uploaded! → ${data.url}`, 'success');

        // Add link
        const link = document.createElement('a');
        link.href = data.url;
        link.target = '_blank';
        link.textContent = '🔗 View on YouTube';
        link.style.cssText = 'display:block;text-align:center;margin-top:6px;color:var(--accent-2);font-size:12px;';
        btn.parentElement.appendChild(link);

      } catch (err) {
        toast(err.message, 'error');
        btn.textContent = '📺 Upload to YouTube';
        btn.disabled = false;
      }
    });

    resultsGrid.appendChild(card);
  });
}

// ═══════════════════════════════════════
// YouTube OAuth
// ═══════════════════════════════════════
ytConnectBtn.addEventListener('click', () => {
  if (ytAuthenticated) {
    toast('Already connected to YouTube!', 'success');
    return;
  }
  ytModal.classList.add('active');
});

ytModalClose.addEventListener('click', () => {
  ytModal.classList.remove('active');
});

ytModal.addEventListener('click', (e) => {
  if (e.target === ytModal) ytModal.classList.remove('active');
});

ytAuthBtn.addEventListener('click', async () => {
  const clientId = $('#ytClientId').value.trim();
  const clientSecret = $('#ytClientSecret').value.trim();

  if (!clientId || !clientSecret) {
    toast('Please enter both Client ID and Secret', 'error');
    return;
  }

  ytAuthBtn.disabled = true;
  ytAuthBtn.textContent = '⏳ Opening browser...';

  try {
    const res = await fetch(`${API}/youtube/auth`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, client_secret: clientSecret })
    });

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || 'Auth failed');

    toast('Check your browser to authorize with Google', 'info');
    ytAuthBtn.textContent = '⏳ Waiting for authorization...';

    // Poll for auth completion
    await pollYtAuth();

  } catch (err) {
    toast(err.message, 'error');
    ytAuthBtn.textContent = '🔗 Authorize with Google';
    ytAuthBtn.disabled = false;
  }
});

async function pollYtAuth() {
  for (let i = 0; i < 60; i++) {
    await new Promise(r => setTimeout(r, 3000));

    try {
      const res = await fetch(`${API}/youtube/status`);
      const data = await res.json();

      if (data.authenticated) {
        ytAuthenticated = true;
        ytConnectBtn.classList.add('connected');
        ytBtnText.textContent = '✅ Connected';
        ytModal.classList.remove('active');
        toast('YouTube connected successfully! 🎉', 'success');
        ytAuthBtn.textContent = '🔗 Authorize with Google';
        ytAuthBtn.disabled = false;
        return;
      }

      if (data.error) {
        throw new Error(data.error);
      }

    } catch (err) {
      toast(err.message, 'error');
      ytAuthBtn.textContent = '🔗 Authorize with Google';
      ytAuthBtn.disabled = false;
      return;
    }
  }

  toast('Authorization timed out. Please try again.', 'error');
  ytAuthBtn.textContent = '🔗 Authorize with Google';
  ytAuthBtn.disabled = false;
}

// Check YouTube status on page load
(async () => {
  try {
    const res = await fetch(`${API}/youtube/status`);
    const data = await res.json();
    if (data.authenticated) {
      ytAuthenticated = true;
      ytConnectBtn.classList.add('connected');
      ytBtnText.textContent = '✅ Connected';
    }
  } catch (e) {}
})();

// ── Enter key triggers analyze ──
urlInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') analyzeBtn.click();
});

// ═══════════════════════════════════════
// TAB SWITCHING
// ═══════════════════════════════════════
document.querySelectorAll('.tab').forEach(tab => {
  tab.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    tab.classList.add('active');
    const target = tab.dataset.tab;
    document.getElementById(target === 'shorts' ? 'tabShorts' : 'tabEditor').classList.add('active');
  });
});

// ═══════════════════════════════════════
// VIDEO EDITOR
// ═══════════════════════════════════════
const editorState = {
  clips: [],       // { id, filename, original_name, duration, width, height, objectUrl, trim_start, trim_end, cut_from, cut_to, crop, rotate, volume }
  mergeJobId: null
};

const edDropzone     = $('#editorDropzone');
const edBrowseBtn    = $('#editorBrowseBtn');
const edFileInput    = $('#editorFileInput');
const edClipsSection = $('#editorClipsSection');
const edClipsList    = $('#editorClipsList');
const edClipCount    = $('#editorClipCount');
const mergeBtn       = $('#mergeBtn');
const noiseReduction = $('#noiseReduction');
const noiseStrength  = $('#noiseStrength');
const noiseStrWrap   = $('#noiseStrengthWrap');
const noiseStrVal    = $('#noiseStrengthVal');
const mergeProgSection = $('#mergeProgressSection');
const mergeProgLabel = $('#mergeProgressLabel');
const mergeProgPct   = $('#mergeProgressPct');
const mergeProgFill  = $('#mergeProgressFill');
const edResultSection = $('#editorResultSection');
const edResultVideo  = $('#editorResultVideo');
const edDownloadBtn  = $('#editorDownloadBtn');

// ── Dropzone ──
edDropzone.addEventListener('click', () => edFileInput.click());
edBrowseBtn.addEventListener('click', (e) => { e.stopPropagation(); edFileInput.click(); });

edDropzone.addEventListener('dragover', (e) => { e.preventDefault(); edDropzone.classList.add('drag-over'); });
edDropzone.addEventListener('dragleave', () => edDropzone.classList.remove('drag-over'));
edDropzone.addEventListener('drop', (e) => {
  e.preventDefault();
  edDropzone.classList.remove('drag-over');
  if (e.dataTransfer.files.length) uploadEditorFiles(e.dataTransfer.files);
});

edFileInput.addEventListener('change', () => {
  if (edFileInput.files.length) uploadEditorFiles(edFileInput.files);
  edFileInput.value = '';
});

// ── Upload Files ──
async function uploadEditorFiles(fileList) {
  // Convert FileList to Array immediately (FileList gets invalidated when input is cleared)
  const files = Array.from(fileList);
  const formData = new FormData();
  for (const f of files) formData.append('files', f);

  toast('Uploading clips...', 'info');

  try {
    const res = await fetch(`${API}/editor/upload`, { method: 'POST', body: formData });
    if (!res.ok) { const err = await res.json(); throw new Error(err.error || 'Upload failed'); }
    const data = await res.json();

    // Create object URLs for local preview
    let fileIdx = 0;
    for (const clip of data.clips) {
      if (fileIdx < files.length) {
        clip.objectUrl = URL.createObjectURL(files[fileIdx]);
      } else {
        clip.objectUrl = '';
      }
      clip.trim_start = 0;
      clip.trim_end = clip.duration;
      clip.cut_from = 0;
      clip.cut_to = 0;
      clip.crop = 'none';
      clip.rotate = 0;
      clip.volume = 100;
      editorState.clips.push(clip);
      fileIdx++;
    }

    renderEditorClips();
    toast(`${data.clips.length} clip(s) added!`, 'success');
  } catch (err) {
    toast(err.message, 'error');
  }
}

// ── Render Clip Cards ──
let selectedClipIdx = -1;
let playAllMode = false;

function renderEditorClips() {
  const clips = editorState.clips;
  edClipCount.textContent = `${clips.length} clip${clips.length !== 1 ? 's' : ''}`;
  mergeBtn.disabled = clips.length === 0;

  if (clips.length > 0) {
    edClipsSection.classList.add('active');
  } else {
    edClipsSection.classList.remove('active');
    selectedClipIdx = -1;
  }

  // Auto-select first clip and start preview when clips are first added
  if (clips.length > 0 && selectedClipIdx === -1) {
    selectedClipIdx = 0;
    showClipPreview(clips[0], 0);
  }

  // Render Timeline
  const timeline = document.getElementById('edTimeline');
  timeline.innerHTML = '';

  clips.forEach((clip, i) => {
    const thumb = document.createElement('div');
    thumb.className = 'ed-tl-clip' + (i === selectedClipIdx ? ' selected' : '');
    thumb.draggable = true;

    thumb.innerHTML = `
      <video src="${clip.objectUrl}" muted preload="metadata"></video>
      <span class="tl-index">${i + 1}</span>
      <span class="tl-label">${clip.original_name}</span>
      ${clip.overlay ? '<span class="tl-overlay-badge">OVR</span>' : ''}
      <button class="tl-remove">✕</button>
    `;

    // Click to select & preview
    thumb.addEventListener('click', (e) => {
      if (e.target.classList.contains('tl-remove')) return;
      playAllMode = false;
      selectedClipIdx = i;
      renderEditorClips();
      showClipPreview(clip, i);
      showClipEditor(clip, i);
    });

    // Remove button
    thumb.querySelector('.tl-remove').addEventListener('click', (e) => {
      e.stopPropagation();
      editorState.clips.splice(i, 1);
      if (selectedClipIdx >= editorState.clips.length) selectedClipIdx = Math.max(0, editorState.clips.length - 1);
      if (editorState.clips.length === 0) selectedClipIdx = -1;
      renderEditorClips();
      if (editorState.clips.length > 0 && selectedClipIdx >= 0) {
        showClipPreview(editorState.clips[selectedClipIdx], selectedClipIdx);
        showClipEditor(editorState.clips[selectedClipIdx], selectedClipIdx);
      } else {
        hideClipEditor();
      }
      toast('Clip removed', 'info');
    });

    // Drag to reorder
    thumb.addEventListener('dragstart', (e) => {
      e.dataTransfer.effectAllowed = 'move';
      e.dataTransfer.setData('text/plain', i.toString());
      thumb.style.opacity = '0.4';
    });
    thumb.addEventListener('dragend', () => { thumb.style.opacity = '1'; });
    thumb.addEventListener('dragover', (e) => {
      e.preventDefault();
      thumb.style.borderColor = 'var(--primary)';
    });
    thumb.addEventListener('dragleave', () => {
      thumb.style.borderColor = i === selectedClipIdx ? 'var(--accent)' : 'transparent';
    });
    thumb.addEventListener('drop', (e) => {
      e.preventDefault();
      const from = parseInt(e.dataTransfer.getData('text/plain'));
      if (from !== i) {
        const [moved] = editorState.clips.splice(from, 1);
        editorState.clips.splice(i, 0, moved);
        selectedClipIdx = i;
        renderEditorClips();
      }
    });

    timeline.appendChild(thumb);
  });
}

// ── Sequential Playback ──
function showClipPreview(clip, idx) {
  const player = document.getElementById('edPreviewPlayer');
  const empty = document.getElementById('edPreviewEmpty');
  const nowPlaying = document.getElementById('edNowPlaying');

  player.src = clip.objectUrl;
  player.classList.add('active');
  empty.classList.add('hidden');
  player.load();

  nowPlaying.textContent = `${idx + 1}/${editorState.clips.length} · ${clip.original_name}`;

  // Highlight playing clip in timeline
  document.querySelectorAll('.ed-tl-clip').forEach((el, i) => {
    el.classList.toggle('playing', i === idx);
  });
}

// Play All — sequential playback through all clips
document.getElementById('edPlayAllBtn').addEventListener('click', () => {
  if (editorState.clips.length === 0) { toast('No clips to play', 'error'); return; }
  playAllMode = true;
  selectedClipIdx = 0;
  renderEditorClips();
  showClipPreview(editorState.clips[0], 0);

  const player = document.getElementById('edPreviewPlayer');
  player.play();
});

// Auto-advance to next clip when current finishes
document.getElementById('edPreviewPlayer').addEventListener('ended', () => {
  if (!playAllMode) return;
  const next = selectedClipIdx + 1;
  if (next < editorState.clips.length) {
    selectedClipIdx = next;
    renderEditorClips();
    showClipPreview(editorState.clips[next], next);
    document.getElementById('edPreviewPlayer').play();
  } else {
    playAllMode = false;
    document.getElementById('edNowPlaying').textContent = '✅ Finished';
    document.querySelectorAll('.ed-tl-clip').forEach(el => el.classList.remove('playing'));
  }
});

// ── Clip Editor Panel ──
let overlayPendingClipIdx = -1;

function showClipEditor(clip, idx) {
  const editor = document.getElementById('edClipEditor');
  const title = document.getElementById('edEditorTitle');
  const body = document.getElementById('edEditorBody');
  editor.style.display = 'block';

  title.textContent = `✏️ ${clip.original_name} · ${clip.duration}s`;
  body.innerHTML = `
    <div class="clip-row">
      <div class="clip-field"><label>✂️ Trim Start (s)</label>
        <input type="number" class="ce-input" data-key="trim_start" value="${clip.trim_start}" step="0.1" min="0" max="${clip.duration}">
      </div>
      <div class="clip-field"><label>✂️ Trim End (s)</label>
        <input type="number" class="ce-input" data-key="trim_end" value="${clip.trim_end}" step="0.1" min="0" max="${clip.duration}">
      </div>
      <div class="clip-field"><label>🔪 Cut From (s)</label>
        <input type="number" class="ce-input" data-key="cut_from" value="${clip.cut_from}" step="0.1" min="0" max="${clip.duration}">
      </div>
      <div class="clip-field"><label>🔪 Cut To (s)</label>
        <input type="number" class="ce-input" data-key="cut_to" value="${clip.cut_to}" step="0.1" min="0" max="${clip.duration}">
      </div>
    </div>
    <div class="clip-row">
      <div class="clip-field"><label>🖼️ Crop</label>
        <select class="ce-input" data-key="crop">
          <option value="none" ${clip.crop==='none'?'selected':''}>None</option>
          <option value="16:9" ${clip.crop==='16:9'?'selected':''}>16:9</option>
          <option value="9:16" ${clip.crop==='9:16'?'selected':''}>9:16</option>
          <option value="1:1" ${clip.crop==='1:1'?'selected':''}>1:1</option>
          <option value="4:3" ${clip.crop==='4:3'?'selected':''}>4:3</option>
        </select>
      </div>
      <div class="clip-field"><label>🔄 Rotate</label>
        <select class="ce-input" data-key="rotate">
          <option value="0" ${clip.rotate==0?'selected':''}>0°</option>
          <option value="90" ${clip.rotate==90?'selected':''}>90°</option>
          <option value="180" ${clip.rotate==180?'selected':''}>180°</option>
          <option value="270" ${clip.rotate==270?'selected':''}>270°</option>
        </select>
      </div>
      <div class="clip-field" style="flex:2"><label>🔊 Volume: <span id="ceVolLabel">${clip.volume}%</span></label>
        <input type="range" class="ce-input" data-key="volume" value="${clip.volume}" min="0" max="200" step="5">
      </div>
    </div>
    <div class="ed-overlay-section">
      <h4>🎭 Chroma Key Overlay</h4>
      <p style="font-size:11px;color:var(--text-3);margin:0 0 8px">Add a green-screen clip on top. The green background will be removed automatically.</p>
      <div class="ed-overlay-row" id="overlayRow">
        ${clip.overlay
          ? `<div class="ed-overlay-info">
               <span>🎭 ${clip.overlay.name}</span>
               <button class="ed-overlay-remove" id="removeOverlayBtn">✕</button>
             </div>`
          : `<button class="ed-overlay-btn" id="addOverlayBtn">＋ Add Overlay Clip</button>`
        }
      </div>
      ${clip.overlay ? `
      <div class="clip-row" style="margin-top:8px">
        <div class="clip-field"><label>🎨 Key Color</label>
          <input type="color" id="overlayColor" value="${clip.overlay.color || '#00FF00'}">
        </div>
        <div class="clip-field"><label>🎚️ Similarity</label>
          <input type="number" id="overlaySim" value="${clip.overlay.similarity || 0.3}" min="0.05" max="0.9" step="0.05">
        </div>
        <div class="clip-field"><label>🌫️ Blend</label>
          <input type="number" id="overlayBlend" value="${clip.overlay.blend || 0.1}" min="0" max="1" step="0.05">
        </div>
      </div>` : ''}
    </div>
  `;

  // Input handlers
  body.querySelectorAll('.ce-input').forEach(inp => {
    const handler = () => {
      const key = inp.dataset.key;
      if (key === 'volume') {
        clip[key] = parseInt(inp.value);
        document.getElementById('ceVolLabel').textContent = `${clip.volume}%`;
      } else if (inp.tagName === 'SELECT') {
        clip[key] = inp.value;
      } else {
        clip[key] = parseFloat(inp.value);
      }
    };
    inp.addEventListener('input', handler);
    inp.addEventListener('change', handler);
  });

  // Overlay add
  const addBtn = body.querySelector('#addOverlayBtn');
  if (addBtn) {
    addBtn.addEventListener('click', () => {
      overlayPendingClipIdx = idx;
      document.getElementById('overlayFileInput').click();
    });
  }

  // Overlay remove
  const removeBtn = body.querySelector('#removeOverlayBtn');
  if (removeBtn) {
    removeBtn.addEventListener('click', () => {
      delete clip.overlay;
      showClipEditor(clip, idx);
      renderEditorClips();
      toast('Overlay removed', 'info');
    });
  }

  // Overlay settings
  const colorInp = body.querySelector('#overlayColor');
  if (colorInp) colorInp.addEventListener('input', (e) => { clip.overlay.color = e.target.value; });
  const simInp = body.querySelector('#overlaySim');
  if (simInp) simInp.addEventListener('change', (e) => { clip.overlay.similarity = parseFloat(e.target.value); });
  const blendInp = body.querySelector('#overlayBlend');
  if (blendInp) blendInp.addEventListener('change', (e) => { clip.overlay.blend = parseFloat(e.target.value); });
}

// Overlay file input handler
document.getElementById('overlayFileInput').addEventListener('change', async (e) => {
  const file = e.target.files[0];
  if (!file || overlayPendingClipIdx < 0) return;
  const clip = editorState.clips[overlayPendingClipIdx];
  if (!clip) return;

  const formData = new FormData();
  formData.append('files', file);
  toast('Uploading overlay...', 'info');
  try {
    const res = await fetch(`${API}/editor/upload`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error('Upload failed');
    const data = await res.json();
    clip.overlay = {
      filename: data.clips[0].filename,
      name: file.name,
      color: '#00FF00',
      similarity: 0.3,
      blend: 0.1
    };
    showClipEditor(clip, overlayPendingClipIdx);
    renderEditorClips();
    toast(`🎭 Overlay "${file.name}" added`, 'success');
  } catch (err) {
    toast('Overlay upload failed: ' + err.message, 'error');
  }
  e.target.value = '';
  overlayPendingClipIdx = -1;
});

function hideClipEditor() {
  document.getElementById('edClipEditor').style.display = 'none';
  const player = document.getElementById('edPreviewPlayer');
  player.classList.remove('active');
  document.getElementById('edPreviewEmpty').classList.remove('hidden');
  selectedClipIdx = -1;
}

// Close editor button
document.getElementById('edEditorClose').addEventListener('click', () => {
  hideClipEditor();
  selectedClipIdx = -1;
  renderEditorClips();
});

// Add more clips button
document.getElementById('addMoreClipsBtn').addEventListener('click', () => {
  edFileInput.click();
});

function createGreenScreenClip() {
  return {
    type: 'greenscreen',
    id: 'gs_' + Date.now(),
    duration: 3,
    color: '#00FF00',
    original_name: 'Green Screen'
  };
}

// ── Noise Reduction Toggle ──
noiseReduction.addEventListener('change', () => {
  noiseStrWrap.style.display = noiseReduction.checked ? 'flex' : 'none';
});
noiseStrength.addEventListener('input', () => {
  noiseStrVal.textContent = `${noiseStrength.value} dB`;
});

// ── Green Screen Button ──
document.getElementById('addGreenScreenBtn').addEventListener('click', () => {
  editorState.clips.push(createGreenScreenClip());
  renderEditorClips();
  toast('🟩 Green screen clip added — drag to reorder', 'success');
});

// ── AI Silence Removal ──
document.getElementById('removeSilenceBtn').addEventListener('click', async () => {
  const videoClips = editorState.clips;
  if (videoClips.length === 0) {
    toast('Upload video clips first', 'error');
    return;
  }

  const btn = document.getElementById('removeSilenceBtn');
  btn.disabled = true;
  btn.textContent = '⏳ Analyzing...';
  toast('🤫 Scanning clips for silence...', 'info');

  let totalRemoved = 0;
  let clipsProcessed = 0;

  for (const clip of videoClips) {
    try {
      const res = await fetch(`${API}/editor/detect-silence`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          filename: clip.filename,
          noise_db: -30,
          min_silence: 0.5
        })
      });

      if (!res.ok) continue;
      const data = await res.json();

      if (data.silence_removed > 0.5 && data.speaking_segments.length > 0) {
        // Set trim to first speaking segment start and last speaking segment end
        const firstSpeak = data.speaking_segments[0];
        const lastSpeak = data.speaking_segments[data.speaking_segments.length - 1];
        clip.trim_start = firstSpeak.start;
        clip.trim_end = lastSpeak.end;

        // If there's a gap in the middle, use cut to remove the largest silent gap
        if (data.speaking_segments.length > 1) {
          let biggestGap = 0;
          let gapStart = 0, gapEnd = 0;
          for (let s = 0; s < data.speaking_segments.length - 1; s++) {
            const gap = data.speaking_segments[s + 1].start - data.speaking_segments[s].end;
            if (gap > biggestGap) {
              biggestGap = gap;
              gapStart = data.speaking_segments[s].end;
              gapEnd = data.speaking_segments[s + 1].start;
            }
          }
          if (biggestGap > 0.5) {
            clip.cut_from = gapStart;
            clip.cut_to = gapEnd;
          }
        }

        totalRemoved += data.silence_removed;
        clipsProcessed++;
      }
    } catch (err) {
      console.error('Silence detect error:', err);
    }
  }

  renderEditorClips();
  btn.disabled = false;
  btn.textContent = '🤫 AI Remove Silence';

  if (clipsProcessed > 0) {
    toast(`✅ Removed ${totalRemoved.toFixed(1)}s of silence from ${clipsProcessed} clip(s)`, 'success');
  } else {
    toast('No significant silence found in clips', 'info');
  }
});

// ── Merge & Export ──
mergeBtn.addEventListener('click', async () => {
  if (editorState.clips.length === 0) { toast('Add clips first', 'error'); return; }

  mergeBtn.disabled = true;
  mergeProgSection.classList.add('active');
  edResultSection.classList.remove('active');
  setProgress(mergeProgFill, mergeProgLabel, mergeProgPct, 'Starting merge...', 0);

  try {
    const payload = {
      clips: editorState.clips.map(c => {
        const clipData = {
          filename: c.filename,
          trim_start: c.trim_start,
          trim_end: c.trim_end,
          cut_from: c.cut_from,
          cut_to: c.cut_to,
          crop: c.crop,
          rotate: c.rotate,
          volume: c.volume
        };
        if (c.overlay) {
          clipData.overlay = {
            filename: c.overlay.filename,
            color: c.overlay.color || '#00FF00',
            similarity: c.overlay.similarity || 0.3,
            blend: c.overlay.blend || 0.1
          };
        }
        return clipData;
      }),
      noise_reduction: noiseReduction.checked,
      noise_strength: parseInt(noiseStrength.value),
      output_resolution: $('#outputResolution').value,
      precap_text: ($('#precapText') || {}).value || '',
      precap_duration: parseFloat(($('#precapDuration') || {}).value || 3),
      outro_text: ($('#outroText') || {}).value || '',
      outro_duration: parseFloat(($('#outroDuration') || {}).value || 3)
    };

    const res = await fetch(`${API}/editor/merge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    if (!res.ok) { const err = await res.json(); throw new Error(err.error || 'Merge failed'); }
    const data = await res.json();
    editorState.mergeJobId = data.job_id;

    // Poll for progress
    await pollMergeStatus(data.job_id);

  } catch (err) {
    toast(err.message, 'error');
    setProgress(mergeProgFill, mergeProgLabel, mergeProgPct, 'Failed', 0);
    mergeBtn.disabled = false;
  }
});

async function pollMergeStatus(jobId) {
  while (true) {
    await new Promise(r => setTimeout(r, 2000));
    try {
      const res = await fetch(`${API}/editor/status/${jobId}`);
      const job = await res.json();

      setProgress(mergeProgFill, mergeProgLabel, mergeProgPct,
        job.status === 'done' ? '✅ Complete!' : `Processing... ${job.progress}%`, job.progress);

      if (job.status === 'done') {
        const videoUrl = `${API}/editor/preview/${jobId}`;
        edResultVideo.src = videoUrl;
        edResultVideo.load();
        edDownloadBtn.href = videoUrl;
        edDownloadBtn.download = `merged_video_${jobId}.mp4`;

        edResultSection.classList.add('active');
        edResultSection.scrollIntoView({ behavior: 'smooth', block: 'start' });
        toast('Video merged successfully! 🎉', 'success');
        mergeBtn.disabled = false;
        return;
      }

      if (job.status === 'error') {
        throw new Error(job.error || 'Merge failed');
      }
    } catch (err) {
      toast(err.message, 'error');
      setProgress(mergeProgFill, mergeProgLabel, mergeProgPct, 'Failed', 0);
      mergeBtn.disabled = false;
      return;
    }
  }
}

// ═══════════════════════════════════════
// AI SETTINGS MODAL
// ═══════════════════════════════════════
const settingsBtn   = document.getElementById('settingsBtn');
const settingsModal = document.getElementById('settingsModal');
const settingsClose = document.getElementById('settingsClose');
const saveKeysBtn   = document.getElementById('saveKeysBtn');
const groqKeyInput  = document.getElementById('groqKeyInput');
const geminiKeyInput= document.getElementById('geminiKeyInput');
const groqStatus    = document.getElementById('groqStatus');
const geminiStatus  = document.getElementById('geminiStatus');

// Open/close
settingsBtn.addEventListener('click', () => {
  settingsModal.classList.add('active');
  groqKeyInput.value = localStorage.getItem('groq_key') || '';
  geminiKeyInput.value = localStorage.getItem('gemini_key') || '';
});

settingsClose.addEventListener('click', () => {
  settingsModal.classList.remove('active');
});

settingsModal.addEventListener('click', (e) => {
  if (e.target === settingsModal) settingsModal.classList.remove('active');
});

// Save & validate
saveKeysBtn.addEventListener('click', async () => {
  const groqKey = groqKeyInput.value.trim();
  const geminiKey = geminiKeyInput.value.trim();

  saveKeysBtn.disabled = true;
  saveKeysBtn.textContent = '⏳ Validating...';
  groqStatus.textContent = '';
  geminiStatus.textContent = '';

  // Save to localStorage immediately
  if (groqKey) localStorage.setItem('groq_key', groqKey);
  else localStorage.removeItem('groq_key');

  if (geminiKey) localStorage.setItem('gemini_key', geminiKey);
  else localStorage.removeItem('gemini_key');

  // Validate via backend
  try {
    const res = await fetch(`${API}/config`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ groq_key: groqKey, gemini_key: geminiKey })
    });
    const status = await res.json();

    if (groqKey) {
      groqStatus.textContent = status.groq ? '✓ Valid' : '✗ Invalid';
      groqStatus.className = 'key-status ' + (status.groq ? 'valid' : 'invalid');
      if (!status.groq) localStorage.removeItem('groq_key');
    }

    if (geminiKey) {
      geminiStatus.textContent = status.gemini ? '✓ Valid' : '✗ Invalid';
      geminiStatus.className = 'key-status ' + (status.gemini ? 'valid' : 'invalid');
      if (!status.gemini) localStorage.removeItem('gemini_key');
    }

    updateAIBadge();

    if ((groqKey && status.groq) || (geminiKey && status.gemini)) {
      toast('🤖 AI keys validated! AI features enabled.', 'success');
    } else if (!groqKey && !geminiKey) {
      toast('Keys removed. Using basic mode.', 'info');
    } else {
      toast('Key validation failed. Check your keys.', 'error');
    }

  } catch (err) {
    toast('Could not validate keys: ' + err.message, 'error');
  }

  saveKeysBtn.disabled = false;
  saveKeysBtn.textContent = '🔑 Save & Validate Keys';
});

// Init AI badge on page load
updateAIBadge();
