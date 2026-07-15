let allChannels = [];
let categories = new Set();
let currentStreamUrl = "";
let currentAceId = null;
let currentAbortController = null; // Phase 2: Stale Alert Fix
let hlsInstance = null;
let currentProfile = 'original';
let playbackGeneration = 0;
let playbackRetryCount = 0;
let suppressPlayerErrors = false;
const MAX_PLAYBACK_RECOVERY_ATTEMPTS = 2;

function absolutizeUrl(url) {
    if (!url) return '';
    if (/^https?:\/\//i.test(url)) return url;
    return window.location.origin + url;
}

function isChromeBrowser() {
    const ua = navigator.userAgent;
    return /Chrome|CriOS/i.test(ua) && !/Edg|OPR|Firefox|FxiOS/i.test(ua);
}

function getInitialPlaybackProfile() {
    const saved = localStorage.getItem('ace_default_quality');
    if (saved) return saved;
    return 'original';
}

document.addEventListener('DOMContentLoaded', () => {
    loadChannels();
    loadSettings(); // Phase 2: Persistence
    loadTranscodeCfg(); // Phase 3: Transcode Config

    const player = getPlayerElement();
    if (player) {
        player.addEventListener('playing', hidePlayerStatus);
        player.addEventListener('loadedmetadata', hidePlayerStatus);
        player.addEventListener('canplay', hidePlayerStatus);
        player.addEventListener('error', () => {
            if (currentAceId && !suppressPlayerErrors) recoverPlayback('El reproductor nativo emitió un error.', true);
        });
    }

    // Phase 2: History API for Back Button
    window.addEventListener('popstate', (event) => {
        const modal = document.getElementById('player-modal');
        if (modal && modal.style.display === 'flex') {
            closePlayer(true);
        }
    });
});

// Phase 2: Settings Logic
function loadSettings() {
    const defaultQ = localStorage.getItem('ace_default_quality') || 'original';
    const sel = document.getElementById('default-quality');
    if (sel) sel.value = defaultQ;
}

function saveDefaultQuality() {
    const sel = document.getElementById('default-quality');
    if (sel) {
        localStorage.setItem('ace_default_quality', sel.value);
    }
}

// Phase 3: Server-Side Persistence
async function fetchSettings() {
    try {
        const res = await fetch('/api/settings');
        const settings = await res.json();

        // Populate inputs
        // Strip 'k' for numeric inputs
        document.getElementById('cfg-bitrate-720').value = (settings.transcode_720p_bitrate || '').replace('k', '');
        document.getElementById('cfg-bitrate-480').value = (settings.transcode_480p_bitrate || '').replace('k', '');
        document.getElementById('cfg-crf').value = settings.transcode_compat_crf || '';
        document.getElementById('cfg-endpoint').value = settings.acexy_public_endpoint || '';
        document.getElementById('cfg-token').value = settings.acexy_public_token || '';

        // v1.8.2 Advanced
        document.getElementById('cfg-vcodec').value = settings.transcode_video_codec || 'h264';
        document.getElementById('cfg-preset').value = settings.transcode_preset || 'veryfast';
        document.getElementById('cfg-abitrate').value = settings.transcode_audio_bitrate || '128k';
        document.getElementById('cfg-deinterlace').checked = settings.transcode_deinterlace || false;
        document.getElementById('cfg-orchestrator').checked = settings.orchestrator_enabled === true; // Default false if undefined

    } catch (e) {
        console.error("Failed to fetch settings:", e);
    }
}

async function saveSettings() {
    // Append 'k' if number provided
    let b720 = document.getElementById('cfg-bitrate-720').value;
    if (b720 && !b720.endsWith('k')) b720 += 'k';

    let b480 = document.getElementById('cfg-bitrate-480').value;
    if (b480 && !b480.endsWith('k')) b480 += 'k';

    const payload = {
        transcode_720p_bitrate: b720,
        transcode_480p_bitrate: b480,
        transcode_compat_crf: document.getElementById('cfg-crf').value,
        acexy_public_endpoint: document.getElementById('cfg-endpoint').value,
        acexy_public_token: document.getElementById('cfg-token').value,
        // v1.8.2
        transcode_video_codec: document.getElementById('cfg-vcodec').value,
        transcode_preset: document.getElementById('cfg-preset').value,
        transcode_audio_bitrate: document.getElementById('cfg-abitrate').value,
        transcode_deinterlace: document.getElementById('cfg-deinterlace').checked,
        orchestrator_enabled: document.getElementById('cfg-orchestrator').checked
    };

    try {
        await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        // Optional: Show saved toast?
    } catch (e) {
        console.error("Failed to save settings:", e);
    }
}

// Map old function names just in case HTML still references them
const loadTranscodeCfg = fetchSettings;
const saveTranscodeCfg = saveSettings;

// Transcoding Global State
let isTranscodingEnabled = false;

// Favorites & Theme Logic
let favorites = new Set(JSON.parse(localStorage.getItem('ace_favorites') || '[]'));

// Load Theme
const savedTheme = localStorage.getItem('ace_theme');
if (savedTheme === 'light') {
    document.documentElement.classList.add('light-mode');
    document.getElementById('theme-icon').textContent = '☀️';
} else {
    document.getElementById('theme-icon').textContent = '🌙';
}

function toggleTheme() {
    document.documentElement.classList.toggle('light-mode');
    const isLight = document.documentElement.classList.contains('light-mode');
    localStorage.setItem('ace_theme', isLight ? 'light' : 'dark');
    document.getElementById('theme-icon').textContent = isLight ? '☀️' : '🌙';
}

function toggleFavorite(e, id) {
    e.stopPropagation();
    if (favorites.has(id)) {
        favorites.delete(id);
    } else {
        favorites.add(id);
    }
    localStorage.setItem('ace_favorites', JSON.stringify([...favorites]));

    // UI Update
    const btn = e.target;
    btn.classList.toggle('active');
    btn.textContent = favorites.has(id) ? '★' : '☆';

    // Refresh if currently filtering favorites
    if (document.getElementById('categorySelect').value === 'favorites') {
        filterChannels();
    }
}

async function loadChannels() {
    try {
        // Version & Config Check
        fetch('/api/version').then(r => r.json()).then(d => {
            document.getElementById('version-display').textContent = d.version;
            isTranscodingEnabled = d.transcoding;

            // Show/Hide Elements based on feature flag
            const transcodeOpts = document.querySelectorAll('.transcode-opt');
            transcodeOpts.forEach(el => el.style.display = isTranscodingEnabled ? 'block' : 'none');

            const qualitySel = document.getElementById('quality-selector');
            if (qualitySel) {
                qualitySel.style.display = isTranscodingEnabled ? 'block' : 'none';
            }

        }).catch(e => { });

        const grid = document.getElementById('channel-grid');
        grid.innerHTML = '<div style="text-align:center;">Actualizando canales...</div>';

        const response = await fetch('/api/channels');
        if (!response.ok) throw new Error('Error de red');
        allChannels = await response.json();

        categories.clear();
        allChannels.forEach(ch => { if (ch.group) categories.add(ch.group); });
        populateCategoryDropdown();
        filterChannels();

    } catch (e) {
        document.getElementById('channel-grid').innerHTML = `<div style="text-align:center;color:red;">Error: ${e.message}</div>`;
    }
}

function populateCategoryDropdown() {
    const select = document.getElementById('categorySelect');
    const current = select.value;
    // Keep favorites as fixed option 2
    select.innerHTML = '<option value="all">Todas las categorías</option><option value="favorites">⭐ Favoritos</option>';
    Array.from(categories).sort().forEach(cat => {
        const opt = document.createElement('option');
        opt.value = cat; opt.textContent = cat;
        select.appendChild(opt);
    });
    if (categories.has(current) || current === 'favorites') select.value = current;
}

let filteredChannels = []; // Global variable for filtered channels

function filterChannels() {
    const search = document.getElementById('searchInput').value.toLowerCase();
    const cat = document.getElementById('categorySelect').value;

    filteredChannels = allChannels.filter(ch => {
        const matchesSearch = ch.name.toLowerCase().includes(search);
        if (!matchesSearch) return false;

        if (cat === 'all') return true;
        if (cat === 'favorites') return favorites.has(ch.id);
        return ch.group === cat;
    });

    renderChannels(filteredChannels);
}

// Zapping Logic
function playNextChannel() {
    if (!currentAceId || filteredChannels.length === 0) return;
    const idx = filteredChannels.findIndex(ch => ch.id === currentAceId);
    if (idx === -1) return;

    // Loop to start if at end
    const nextIdx = (idx + 1) % filteredChannels.length;
    playChannel(filteredChannels[nextIdx]);
}

function playPrevChannel() {
    if (!currentAceId || filteredChannels.length === 0) return;
    const idx = filteredChannels.findIndex(ch => ch.id === currentAceId);
    if (idx === -1) return;

    // Loop to end if at start
    const prevIdx = (idx - 1 + filteredChannels.length) % filteredChannels.length;
    playChannel(filteredChannels[prevIdx]);
}

function renderChannels(channelsToRender) {
    // Sort: Favorites first, then alphabetical
    channelsToRender.sort((a, b) => {
        const favA = favorites.has(a.id);
        const favB = favorites.has(b.id);
        if (favA && !favB) return -1;
        if (!favA && favB) return 1;
        return a.name.localeCompare(b.name);
    });

    const grid = document.getElementById('channel-grid');
    grid.innerHTML = '';

    if (channelsToRender.length === 0) {
        grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;">No hay resultados</div>';
        return;
    }

    channelsToRender.forEach(ch => {
        const card = document.createElement('div');
        card.className = 'channel-card';
        card.onclick = () => playChannel(ch);

        const isFav = favorites.has(ch.id);
        const starBtn = `<button class="star-btn ${isFav ? 'active' : ''}" onclick="toggleFavorite(event, '${ch.id}')">${isFav ? '★' : '☆'}</button>`;

        const FALLBACK_LOGO = '/placeholder.svg';

        const logo = ch.logo ?
            `<img src="${ch.logo}" class="channel-logo" loading="lazy" decoding="async" onerror="handleImageError(this, '${ch.id}')">`
            : '<div style="font-size:2rem;">📺</div>';

        // Stats Logic
        let statusDot = '<span class="status-dot dot-grey" title="Nunca visto"></span>';
        let techBadge = '';
        let lastSeenText = '';

        if (ch.stats) {
            const now = Math.floor(Date.now() / 1000);
            const diff = now - ch.stats.last_ok;

            // Status Dot Color
            if (ch.stats.diff_votes && ch.stats.diff_votes < 0) {
                statusDot = '<span class="status-dot dot-red" title="Reportado: Mala Calidad"></span>';
            } else if (diff < 86400) { // < 24h
                statusDot = '<span class="status-dot dot-green" title="Visto recientemente"></span>';
            } else if (diff < 604800) { // < 7 days
                statusDot = '<span class="status-dot dot-yellow" title="Visto esta semana"></span>';
            }

            // Relative Time
            if (diff < 60) lastSeenText = 'Hace instantes';
            else if (diff < 3600) lastSeenText = `Hace ${Math.floor(diff / 60)}m`;
            else if (diff < 86400) lastSeenText = `Hace ${Math.floor(diff / 3600)}h`;
            else lastSeenText = `Hace ${Math.floor(diff / 86400)}d`;

            // Tech Badge
            if (ch.stats.tech_info) {
                const t = ch.stats.tech_info;
                let res = '';
                if (t.height) res = t.height >= 720 ? `${t.height}p` : 'SD';
                if (t.fps) res += `${t.fps}`;

                let codec = t.acodec ? t.acodec.toUpperCase() : '';
                if (codec === 'AC3' || codec === 'EAC3') codec = '🔊 ' + codec;
                else codec = '';

                if (res || codec) {
                    techBadge = `<div class="tech-badge">${res} ${codec}</div>`;
                }
            }
        }

        // Dynamic Font Size for long names
        const nameLen = ch.name.length;
        let nameStyle = "";
        if (nameLen > 40) nameStyle = "font-size: 0.75rem;";
        else if (nameLen > 25) nameStyle = "font-size: 0.8rem;";

        card.innerHTML = `
            ${starBtn}
            ${statusDot}
            ${logo}
            <div class="channel-name" style="${nameStyle}">${ch.name} <span style="font-size:0.8em; color:#888;">[${ch.id.slice(-4)}]</span></div>
            ${techBadge}
            ${lastSeenText ? `<div class="last-seen">${lastSeenText}</div>` : ''}
        `;
        grid.appendChild(card);
    });
}


function isIOS() {
    return [
        'iPad Simulator', 'iPhone Simulator', 'iPod Simulator', 'iPad', 'iPhone', 'iPod'
    ].includes(navigator.platform) || (navigator.userAgent.includes("Mac") && "ontouchend" in document);
}

let loadTimeout;
let statsInterval;
let engineInfoInterval;

// Phase 5: Engine Info Logic
async function fetchEngineInfo(aceId, isUpdate = false) {
    const container = document.getElementById('player-engine-info');
    if (!container) return;

    if (!isUpdate) {
        container.innerHTML = '<span class="status-dot dot-grey" style="position:static; display:inline-block; margin-right:5px;"></span> Buscando info...';
    }
    // console.log(`[EngineInfo] Fetching for ID: ${aceId} (Update: ${isUpdate})`);

    try {
        const [engRes, strRes] = await Promise.all([
            fetch('/api/orchestrator/status'),
            fetch('/api/orchestrator/streams')
        ]);

        const engines = await engRes.json();
        const streams = await strRes.json();

        let html = '';

        const stream = Array.isArray(streams) ? streams.find(s =>
            [s.key, s.content_id, s.id].some(value =>
                typeof value === 'string' && value.toLowerCase().includes(aceId.toLowerCase())
            )
        ) : null;

        // Engine Info
        if (Array.isArray(engines)) {
            const engine = engines.find(e =>
                (stream && e.container_id === stream.container_id) ||
                (e.streams && e.streams.some(s => s.toLowerCase().includes(aceId.toLowerCase())))
            );
            if (engine) {
                const isHealthy = engine.health_status === 'healthy';
                const color = isHealthy ? '#2ea043' : '#da3633';
                html += `
                    <span class="status-dot" style="position:static; display:inline-block; margin-right:5px; background:${color}"></span>
                    Engine: <strong>${engine.container_name}</strong>
                `;
            }
        }

        // Stream Stats
        if (stream) {
            const peers = stream.peers !== undefined ? stream.peers : 0;
            const downVal = stream.speed_down ? stream.speed_down : 0;
            html += ` <span style="margin-left:10px; opacity:0.8;">| 👤 ${peers} | ⬇️ ${downVal} KB/s</span>`;
        }

        if (html === '') {
            container.innerHTML = 'Motor no identificado';
        } else {
            container.innerHTML = html;
        }

    } catch (e) {
        console.error("Engine info error", e);
        container.innerHTML = '';
    }
}

async function playChannel(channel) {
    if (!channel) return;

    const modal = document.getElementById('player-modal');
    hidePlayerStatus();
    resetPlayerEngine();
    if (engineInfoInterval) clearInterval(engineInfoInterval);

    fetchEngineInfo(channel.id); // Initial call
    engineInfoInterval = setInterval(() => fetchEngineInfo(channel.id, true), 3000); // Poll every 3s

    // ... rest of function continues ...

    // Append ID to title for visibility
    const displayTitle = `${channel.name} <span style="font-size:0.8em; color:#ddd;">[${channel.id.slice(-4)}]</span>`;
    document.getElementById('player-title').innerHTML = displayTitle;

    document.getElementById('player-tech-info').innerHTML = '';

    // Reset Quality Selector to Original
    const qualitySel = document.getElementById('quality-selector');
    if (qualitySel) qualitySel.value = 'original';

    // Find channel info for Direct Link
    // Find channel info for Direct Link
    const channelData = allChannels.find(ch => ch.id === channel.id);
    if (channelData && channelData.url) {
        activeDirectUrl = channelData.url;
    } else {
        activeDirectUrl = "";
    }

    // Reset Copy Button
    const vlcLink = document.getElementById('vlc-link');
    if (vlcLink) {
        vlcLink.innerHTML = "⏳ Generando...";
        vlcLink.disabled = true;
        vlcLink.removeAttribute('data-url');
        vlcLink.onclick = null;
        vlcLink.style.pointerEvents = "none";
        vlcLink.style.opacity = "0.5";
    }

    // Setup iOS Button
    // Setup iOS/Native Button (Hide on Desktop to prevent download confusion)
    const iosBtn = document.getElementById('ios-btn');
    if (isIOS() || /Android/i.test(navigator.userAgent)) {
        if (iosBtn) iosBtn.style.display = 'inline-block';
    } else {
        if (iosBtn) iosBtn.style.display = 'none';
    }

    // Capture ID for feedback
    currentAceId = channel.id;

    // Reset Feedback Buttons
    const likeBtn = document.getElementById('btn-like');
    const dislikeBtn = document.getElementById('btn-dislike');
    if (likeBtn) likeBtn.classList.remove('active-like');
    if (dislikeBtn) dislikeBtn.classList.remove('active-dislike');

    modal.style.display = 'flex';

    // Start Polling for Stats (Tech Info)
    if (statsInterval) clearInterval(statsInterval);
    statsInterval = setInterval(() => pollStats(channel.id), 5000);

    // Initial Play
    const startProfile = getInitialPlaybackProfile();

    // Update selector to match default
    if (qualitySel) qualitySel.value = startProfile;

    // Push History State (so Back button works)
    history.pushState({ modalOpen: true }, "", "#player");

    startPlayback(channel.id, startProfile, { force: false, resetRetries: true });
}

function getPlayerElement() {
    return document.getElementById('player');
}

function showPlayerStatus(title, message, options = {}) {
    const box = document.getElementById('player-error');
    const icon = document.getElementById('player-error-icon');
    const titleEl = document.getElementById('player-error-title');
    const messageEl = document.getElementById('player-error-message');
    const retryBtn = document.getElementById('player-retry-btn');

    if (!box) return;
    box.style.display = 'flex';
    if (icon) icon.textContent = options.icon || '⏳';
    if (titleEl) titleEl.textContent = title;
    if (messageEl) messageEl.textContent = message || '';
    if (retryBtn) retryBtn.style.display = options.retry ? 'inline-block' : 'none';
}

function hidePlayerStatus() {
    const box = document.getElementById('player-error');
    if (box) box.style.display = 'none';
}

function resetPlayerEngine() {
    if (loadTimeout) {
        clearTimeout(loadTimeout);
        loadTimeout = null;
    }

    if (hlsInstance) {
        hlsInstance.destroy();
        hlsInstance = null;
    }

    const player = getPlayerElement();
    if (player) {
        suppressPlayerErrors = true;
        player.pause();
        player.removeAttribute('src');
        player.load();
        setTimeout(() => { suppressPlayerErrors = false; }, 250);
    }
}

function attachHlsToPlayer(player, streamUrl, aceId, profile, generation) {
    if (hlsInstance) {
        hlsInstance.destroy();
        hlsInstance = null;
    }

    if (window.Hls && Hls.isSupported()) {
        hlsInstance = new Hls({
            // Some browser extensions wrap Worker message listeners and throw
            // when optional EME globals (MediaKeyMessageEvent) are absent.
            // Running the transmuxer on the main thread avoids losing hls.js
            // events while keeping playback compatible with those browsers.
            enableWorker: false,
            lowLatencyMode: false,
            backBufferLength: 30,
            manifestLoadingTimeOut: 20000,
            levelLoadingTimeOut: 20000,
            fragLoadingTimeOut: 30000
        });

        hlsInstance.on(Hls.Events.ERROR, (event, data) => {
            if (!data || generation !== playbackGeneration || currentAceId !== aceId) return;
            console.warn(data.fatal ? 'Fatal hls.js error:' : 'hls.js warning:', data);
            if (!data.fatal) return;

            if (data.type === Hls.ErrorTypes.MEDIA_ERROR && hlsInstance) {
                showPlayerStatus('Recuperando reproducción', 'hls.js detectó un error de medio. Reintentando...');
                hlsInstance.recoverMediaError();
                setTimeout(() => {
                    const stillStalled = player.readyState < 2 || player.paused;
                    if (stillStalled && generation === playbackGeneration && currentAceId === aceId) {
                        recoverPlayback('El reproductor no pudo recuperarse.', true);
                    }
                }, 4000);
                return;
            }

            recoverPlayback('El stream HLS falló durante la reproducción.', true);
        });

        hlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {
            hidePlayerStatus();
            const playPromise = player.play();
            if (playPromise) playPromise.catch(() => {
                hidePlayerStatus();
            });
        });

        hlsInstance.on(Hls.Events.FRAG_LOADED, () => {
            hidePlayerStatus();
        });

        hlsInstance.on(Hls.Events.MEDIA_ATTACHED, () => {
            hlsInstance.loadSource(streamUrl);
        });
        hlsInstance.attachMedia(player);
        return;
    }

    if (player.canPlayType('application/vnd.apple.mpegurl') || player.canPlayType('application/x-mpegURL')) {
        player.src = streamUrl;
        const playPromise = player.play();
        hidePlayerStatus();
        if (playPromise) playPromise.catch(() => {
            hidePlayerStatus();
        });
        return;
    }

    showPlayerStatus('Player no compatible', 'Este navegador no soporta HLS y hls.js no está disponible.', { icon: '⚠️', retry: true });
}

async function startPlayback(aceId, profile, options = {}) {
    const player = getPlayerElement();
    if (!player) return;

    const force = options.force === true;
    const resetRetries = options.resetRetries !== false;
    if (resetRetries) playbackRetryCount = 0;
    currentProfile = profile || 'original';
    const generation = ++playbackGeneration;

    // Abort previous request if any
    if (currentAbortController) {
        currentAbortController.abort();
    }
    currentAbortController = new AbortController();
    const signal = currentAbortController.signal;
    resetPlayerEngine();
    showPlayerStatus('Preparando stream', force ? 'Reiniciando AceStream y esperando segmentos...' : 'Conectando con AceStream...');

    try {
        // Phase 3: Configurable Quality Overrides (Now handled server-side)
        let url = `/api/hls/start/${aceId}?profile=${encodeURIComponent(currentProfile)}`;
        if (force) url += '&force=1';

        // No longer appending params here. Server reads settings.json directly.

        const res = await fetch(url, { signal });
        const data = await res.json().catch(() => ({ status: 'error', message: 'Respuesta inválida del servidor' }));
        if (signal.aborted || generation !== playbackGeneration) return;

        if (data.status === 'ok') {
            currentStreamUrl = data.url;
            player.muted = true;
            player.playsInline = true;
            player.autoplay = true;
            showPlayerStatus('Cargando player', `HLS preparado en ${data.attempts || 1} intento(s).`);
            attachHlsToPlayer(player, data.url, aceId, currentProfile, generation);

            // Enable Copy Button (Dropdown Trigger)
            const vlcBtn = document.getElementById('vlc-link');
            if (vlcBtn) {
                vlcBtn.setAttribute('data-url', absolutizeUrl(data.url));
                vlcBtn.disabled = false;
                vlcBtn.innerHTML = "🔗 Copiar...";
                vlcBtn.style.pointerEvents = "auto";
                vlcBtn.style.opacity = "1";
                vlcBtn.onclick = toggleCopyMenu; // Set trigger
                vlcBtn.removeAttribute('href'); // Ensure it's a button behavior
            }


            // Timeout Logic (20 seconds) - Only relevant if player is active
            if (loadTimeout) clearTimeout(loadTimeout);
            loadTimeout = setTimeout(() => {
                // Check if still playing THIS stream
                if (player.readyState === 0 && currentAceId === aceId) {
                    console.warn("Stream timeout");
                    recoverPlayback('El player no empezó a reproducir a tiempo.', true);
                }
            }, 20000);

            player.addEventListener('playing', () => {
                if (loadTimeout) clearTimeout(loadTimeout);
                hidePlayerStatus();
            }, { once: true });

        } else {
            const msg = data.message || `Error servidor: ${data.status}`;
            showPlayerStatus('Stream no disponible', msg, { icon: '⚠️', retry: data.retryable !== false });
        }
    } catch (e) {
        if (e.name === 'AbortError') {
            console.log("Fetch aborted (user closed player or switched)");
        } else {
            console.error(e);
            showPlayerStatus('Error de conexión', 'No se pudo contactar con el servidor HLS.', { icon: '⚠️', retry: true });
        }
    }
}

function recoverPlayback(reason, forceRestart) {
    if (!currentAceId) return;

    if (playbackRetryCount < MAX_PLAYBACK_RECOVERY_ATTEMPTS) {
        playbackRetryCount++;
        showPlayerStatus('Reintentando stream', `${reason} Intento ${playbackRetryCount}/${MAX_PLAYBACK_RECOVERY_ATTEMPTS}...`);
        startPlayback(currentAceId, currentProfile, { force: forceRestart, resetRetries: false });
        return;
    }

    resetPlayerEngine();
    showPlayerStatus('Stream no disponible', `${reason} No se pudo recuperar automáticamente.`, { icon: '⚠️', retry: true });
}

function retryCurrentPlayback(force = true) {
    if (!currentAceId) return;
    startPlayback(currentAceId, currentProfile, { force, resetRetries: true });
}

function changeQuality(profile) {
    if (!currentAceId) return;

    // Feedback
    const sel = document.getElementById('quality-selector');
    const oldText = sel.options[sel.selectedIndex].text;
    sel.options[sel.selectedIndex].text = "Cambiando... ⏳";
    sel.disabled = true;

    startPlayback(currentAceId, profile, { force: false, resetRetries: true }).then(() => {
        // ... (rest is same, promise usually resolves fast)
        // Note: startPlayback is async, so we might need to handle this better
        // but existing logic just unblocks UI which is fine.
    }).finally(() => {
        sel.disabled = false;
        // Refresh text just in case (hacky but works)
        if (profile === 'original') sel.options[0].text = "Original (Passthrough)";
        if (profile === 'max_compat') sel.options[1].text = "Compatibilidad (Recode)";
        if (profile === '720p') sel.options[2].text = "720p (Transcode)";
        if (profile === '480p') sel.options[3].text = "480p (Transcode)";
    });
}

function playNativeIOS() {
    if (!currentStreamUrl) {
        showPlayerStatus('Stream aún no listo', 'Espera a que cargue el stream antes de abrirlo directo.', { icon: '⏳' });
        return;
    }
    const fullUrl = absolutizeUrl(currentStreamUrl);
    // Open in new tab to trigger native player or download without blocking UI
    window.open(fullUrl, '_blank');
}

function closePlayer(fromHistory = false) {
    // Abort any pending fetch
    if (currentAbortController) {
        currentAbortController.abort();
        currentAbortController = null;
    }

    // Manage History
    if (!fromHistory) {
        // If closed manually (X button), go back to remove hash
        if (window.location.hash === '#player') {
            history.back();
            // history.back() triggers popstate, which calls closePlayer(true)
            // so we return here to let that handle the UI closing?
            // Actually it's cleaner to just let the popstate handler do the UI work.
            // But if we want instant response...
        }
    }

    currentStreamUrl = "";
    currentAceId = null;
    currentProfile = 'original';
    playbackGeneration++;
    resetPlayerEngine();
    document.getElementById('player-modal').style.display = 'none';
    if (statsInterval) clearInterval(statsInterval);
    if (engineInfoInterval) clearInterval(engineInfoInterval);
}

function playManual() {
    let id = document.getElementById('manualAceId').value.trim().replace('acestream://', '');
    if (id) playChannel({ id: id, name: 'ID: ' + id });
}

// Close modal on click outside
document.getElementById('player-modal').addEventListener('click', (e) => {
    if (e.target.id === 'player-modal') closePlayer();
});

function copyToClipboard(e, el) {
    e.preventDefault();
    const url = el.getAttribute('data-url') || el.href;

    const copyText = (text) => {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text);
        } else {
            const textArea = document.createElement("textarea");
            textArea.value = text;
            textArea.style.position = "fixed";
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();
            return new Promise((resolve, reject) => {
                try {
                    const successful = document.execCommand('copy');
                    document.body.removeChild(textArea);
                    successful ? resolve() : reject();
                } catch (err) {
                    document.body.removeChild(textArea);
                    reject(err);
                }
            });
        }
    };

    copyText(url).then(() => {
        const originalText = el.textContent;
        el.textContent = "✅ ¡Copiado!";
        setTimeout(() => el.textContent = originalText, 2000);
    }).catch(err => {
        console.error('Failed to copy', err);
        prompt("Copia este enlace manualmente:", url);
    });
}

// Register Service Worker
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').then(registration => {
            console.log('SW Registered:', registration);
        }).catch(error => {
            console.log('SW Registration failed:', error);
        });
    });
}

// M3U Dropdown
function toggleM3UMenu() {
    const menu = document.getElementById("m3u-menu");
    if (menu) menu.classList.toggle("show");
}

function getM3UUrl(profile) {
    // Construct absolute URL for copy
    const relative = `/api/playlist.m3u?profile=${profile}`;
    return window.location.origin + relative;
}

function downloadM3U(profile) {
    // profile: 'direct', 'original', '720p', '480p'
    const url = `/api/playlist.m3u?profile=${profile}`;
    window.location.href = url;
    toggleM3UMenu(); // close
}

function copyM3ULink(profile) {
    const url = getM3UUrl(profile);

    // Reuse existing copy logic or specifically:
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(() => {
            alert('Enlace copiado al portapapeles: ' + profile);
        }).catch(err => {
            console.error('Copy failed, using fallback', err);
            fallbackCopy(url);
        });
    } else {
        fallbackCopy(url);
    }
    toggleM3UMenu();
}


// Close Dropdown on click outside
// Copy Dropdown Logic
function toggleCopyMenu() {
    const dd = document.getElementById("copy-dropdown");
    dd.classList.toggle("show");
}

let activeDirectUrl = ""; // Stores the raw engine URL

function copyLinkAction(type) {
    const vlcBtn = document.getElementById('vlc-link');
    let urlToCopy = "";
    let msg = "";

    if (type === 'hls') {
        urlToCopy = vlcBtn.getAttribute('data-url'); // Already absolute from startPlayback
        msg = "🔗 Enlace HLS copiado";
    } else if (type === 'direct') {
        urlToCopy = activeDirectUrl;
        msg = "⚙️ Enlace Motor copiado";
    }

    if (urlToCopy) {
        // Secure Context (HTTPS/Localhost)
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(urlToCopy).then(() => {
                showCopyFeedback();
            }).catch(err => {
                console.error('Clipboard API failed, trying fallback:', err);
                fallbackCopy(urlToCopy);
            });
        } else {
            // Unsecure Context (HTTP) fallback
            fallbackCopy(urlToCopy);
        }
    }
    toggleCopyMenu(); // Close
}

function showCopyFeedback() {
    const vlcBtn = document.getElementById('vlc-link');
    const originalText = vlcBtn.innerText;
    // ^ Use innerText or preserve icon? The original code preserved it via closure or re-read? 
    // Original code:
    // const originalText = vlcBtn.innerHTML;
    // vlcBtn.innerHTML = "✅ ¡Copiado!";
    // setTimeout(() => vlcBtn.innerHTML = originalText, 2000); 

    // Let's just hardcode the icon if needed or assume simple text modification is fine. 
    // But wait, the button has a dropdown now. Changing innerHTML might break the chevron if it's inside?
    // Looking at index.html (previous steps), the button is just the toggler.

    // To be safe and simple:
    const originalContent = vlcBtn.innerHTML;
    vlcBtn.innerHTML = "✅ Copiado";
    setTimeout(() => vlcBtn.innerHTML = originalContent, 2000);
}

function fallbackCopy(text) {
    var textArea = document.createElement("textarea");
    textArea.value = text;

    // Avoid scrolling to bottom
    textArea.style.top = "0";
    textArea.style.left = "0";
    textArea.style.position = "fixed";
    textArea.style.opacity = "0";

    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();

    try {
        var successful = document.execCommand('copy');
        if (successful) showCopyFeedback();
    } catch (err) {
        console.error('Fallback copy failed:', err);
        alert('Error al copiar: ' + text);
    }

    document.body.removeChild(textArea);
}

// Global click to close copy dropdown
window.onclick = function (event) {
    if (!event.target.matches('#vlc-link') && !event.target.closest('#copy-dropdown')) {
        const dd = document.getElementById("copy-dropdown");
        if (dd && dd.classList.contains('show')) {
            dd.classList.remove('show');
        }
    }
    // Existing m3u dropdown logic...
    if (!event.target.matches('.icon-btn') && !event.target.matches('.m3u-dropdown *') && !event.target.matches('#vlc-link')) {
        var dropdowns = document.getElementsByClassName("dropdown-content-m3u"); // Renamed safely? Or reuse generic?
        // ... existing logic handles .dropdown-content generally?
        // Let's rely on specific checks or separate them.
    }
}

// Settings Logic
function openSettings() {
    document.getElementById('settings-modal').style.display = 'flex';
    loadSources();
}

function closeSettings() {
    document.getElementById('settings-modal').style.display = 'none';
}

document.getElementById('settings-modal').addEventListener('click', (e) => {
    if (e.target.id === 'settings-modal') closeSettings();
});

async function loadSources() {
    const list = document.getElementById('sources-list');
    list.innerHTML = '<li>Cargando...</li>';
    try {
        const res = await fetch('/api/sources');
        const sources = await res.json();

        list.innerHTML = '';
        if (sources.length === 0) {
            list.innerHTML = '<li style="justify-content:center;">No hay fuentes configuradas</li>';
            return;
        }

        sources.forEach(src => {
            const li = document.createElement('li');
            li.innerHTML = `
                <span class="source-url" title="${src.url}">${src.url}</span>
                <button class="delete-btn" onclick="deleteSource('${src.url}')">🗑️</button>
            `;
            list.appendChild(li);
        });
    } catch (e) {
        list.innerHTML = '<li>Error cargando fuentes</li>';
        console.error(e);
    }
}

async function addSource() {
    const input = document.getElementById('newSourceUrl');
    const url = input.value.trim();
    if (!url) return;

    try {
        const res = await fetch('/api/sources', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        const data = await res.json();
        if (res.ok) {
            input.value = ''; // Clear
            loadSources(); // Refresh list inside modal
            loadChannels(); // Refresh main grid background
        } else {
            alert("Error: " + (data.error || 'Desconocido'));
        }
    } catch (e) {
        alert("Error de conexión");
    }
}

async function deleteSource(url) {
    if (!confirm('¿Seguro que quieres eliminar esta fuente?')) return;

    try {
        const res = await fetch('/api/sources', {
            method: 'DELETE',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ url })
        });

        if (res.ok) {
            loadSources(); // Refresh list inside modal
            loadChannels(); // Refresh main grid background
        } else {
            alert("Error al eliminar");
        }
    } catch (e) {
        alert("Error de conexión");
    }
}

async function refreshChannelsFromServer() {
    const btn = document.querySelector('#settings-modal .modal-actions button');
    const originalText = btn.textContent;
    btn.textContent = "Actualizando...";
    btn.disabled = true;

    try {
        const res = await fetch('/api/sources/refresh', { method: 'POST' });
        if (res.ok) {
            alert("Canales actualizados correctamente");
            loadChannels(); // Refresh main grid
            closeSettings();
        } else {
            alert("Error actualizando canales");
        }
    } catch (e) {
        alert("Error de conexión");
    } finally {
        btn.textContent = originalText;
        btn.disabled = false;
    }
}

async function sendFeedback(vote) {
    if (!currentAceId) return;

    // UI Feedback immediately
    const likeBtn = document.getElementById('btn-like');
    const dislikeBtn = document.getElementById('btn-dislike');

    if (likeBtn) likeBtn.classList.remove('active-like');
    if (dislikeBtn) dislikeBtn.classList.remove('active-dislike');

    if (vote === 'like' && likeBtn) likeBtn.classList.add('active-like');
    if (vote === 'dislike' && dislikeBtn) dislikeBtn.classList.add('active-dislike');

    // Optimistic UI Update
    const ch = allChannels.find(c => c.id === currentAceId);
    let previousStats = null;

    if (ch) {
        if (!ch.stats) ch.stats = { success_count: 0, last_ok: Math.floor(Date.now() / 1000) };
        if (!ch.stats.diff_votes) ch.stats.diff_votes = 0;

        // Save previous state for rollback
        previousStats = { ...ch.stats };

        if (vote === 'like') ch.stats.diff_votes++;
        else ch.stats.diff_votes--;

        filterChannels(); // Re-render grid immediately
    }

    try {
        await fetch('/api/stats/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: currentAceId, vote: vote })
        });
    } catch (e) {
        console.error("Feedback error", e);
        // Rollback
        if (ch && previousStats) {
            ch.stats = previousStats;
            filterChannels();
        }
    }


}

function updatePlayerTechBadge(t) {
    const techDiv = document.getElementById('player-tech-info');
    let res = '';
    if (t.height) res = t.height >= 720 ? `${t.height}p` : 'SD';
    if (t.fps) res += ` ${t.fps}fps`;

    let codec = t.acodec ? t.acodec.toUpperCase() : '';
    if (codec === 'AC3' || codec === 'EAC3') codec = '🔊 ' + codec;
    else codec = '';

    if (res || codec) {
        techDiv.innerHTML = `<span class="tech-badge" style="font-size:0.9rem; padding:4px 8px;">${res} ${codec}</span>`;
    }
}

async function pollStats(aceId) {
    try {
        const res = await fetch('/api/channels');
        if (res.ok) {
            const freshChannels = await res.json();
            const freshCh = freshChannels.find(c => c.id === aceId);

            if (freshCh && freshCh.stats && freshCh.stats.tech_info) {
                updatePlayerTechBadge(freshCh.stats.tech_info);

                // Also update main list object for grid
                const localCh = allChannels.find(c => c.id === aceId);
                if (localCh) {
                    localCh.stats = freshCh.stats;
                    // Re-render grid to show badge there too
                    filterChannels();
                }
            }
        }
    } catch (e) { console.error("Poll stats error", e); }
}

function handleImageError(img, id) {
    const FALLBACK_LOGO = '/placeholder.svg';
    img.onerror = null;
    img.src = FALLBACK_LOGO;
    const ch = allChannels.find(c => c.id === id);
    if (ch) {
        ch.logo = FALLBACK_LOGO;
    }
}
