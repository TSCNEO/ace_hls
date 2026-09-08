let allChannels = [];
let categories = new Set();
let currentStreamUrl = "";
let currentAceId = null;
let currentIdentifierType = 'id';
let currentAbortController = null;
let hlsInstance = null;
let currentProfile = 'original';
let playbackGeneration = 0;
let playbackRetryCount = 0;
let suppressPlayerErrors = false;
const MAX_PLAYBACK_RECOVERY_ATTEMPTS = 2;

// Match Stream Queue for Sports Agenda Failover
let currentMatchStreamQueue = [];
let currentMatchQueueIndex = 0;
let currentMatchTitle = '';
let matchFailoverTimer = null;

function triggerMatchFailover(reason) {
    if (matchFailoverTimer) {
        clearTimeout(matchFailoverTimer);
        matchFailoverTimer = null;
    }

    if (!currentMatchStreamQueue || currentMatchStreamQueue.length <= 1) {
        return false;
    }

    if (currentMatchQueueIndex + 1 < currentMatchStreamQueue.length) {
        currentMatchQueueIndex++;
        const nextStream = currentMatchStreamQueue[currentMatchQueueIndex];
        console.warn(`[Failover] Switching to backup stream #${currentMatchQueueIndex + 1}: ${nextStream.channel_name} (${reason})`);
        showPlayerStatus(
            '⚡ Conmutando señal',
            `${reason} Saltando a señal de respaldo #${currentMatchQueueIndex + 1} (${nextStream.quality} · ${nextStream.source_name})...`,
            { icon: '🔄' }
        );

        setTimeout(() => {
            playAgendaStream(
                nextStream.stream_id,
                nextStream.channel_name,
                currentMatchStreamQueue,
                currentMatchQueueIndex,
                currentMatchTitle
            );
        }, 800);
        return true;
    }

    return false;
}

function absolutizeUrl(url) {
    if (!url) return '';
    if (/^https?:\/\//i.test(url)) return url;
    return window.location.origin + url;
}

function safeLogoUrl(value) {
    if (!value) return '';
    try {
        const parsed = new URL(value, window.location.origin);
        if (parsed.protocol === 'http:' || parsed.protocol === 'https:') return parsed.href;
    } catch (_error) {
        return '';
    }
    return '';
}

function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
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
    loadSettings();
    loadTranscodeCfg();

    const player = getPlayerElement();
    if (player) {
        player.addEventListener('playing', hidePlayerStatus);
        player.addEventListener('loadedmetadata', hidePlayerStatus);
        player.addEventListener('canplay', hidePlayerStatus);
        player.addEventListener('error', () => {
            if (currentAceId && !suppressPlayerErrors) recoverPlayback('El reproductor nativo emitió un error.', true);
        });
    }

    // Keep browser back navigation in sync with the player modal.
    window.addEventListener('popstate', (event) => {
        const modal = document.getElementById('player-modal');
        if (modal && modal.style.display === 'flex') {
            closePlayer(true);
        }
    });
});

// Local browser preferences
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

// Persistent server settings
async function fetchSettings() {
    try {
        const [res, backendRes] = await Promise.all([
            fetch('/api/settings'),
            fetch('/api/orchestrator/config')
        ]);
        const settings = await res.json();
        const backend = await backendRes.json();

        // Populate inputs
        // Strip 'k' for numeric inputs
        document.getElementById('cfg-bitrate-720').value = (settings.transcode_720p_bitrate || '').replace('k', '');
        document.getElementById('cfg-bitrate-480').value = (settings.transcode_480p_bitrate || '').replace('k', '');
        document.getElementById('cfg-crf').value = settings.transcode_compat_crf || '';
        document.getElementById('cfg-endpoint').value = settings.stream_public_endpoint || '';
        document.getElementById('cfg-token').value = settings.stream_public_token || '';

        document.getElementById('cfg-vcodec').value = settings.transcode_video_codec || 'h264';
        document.getElementById('cfg-preset').value = settings.transcode_preset || 'veryfast';
        document.getElementById('cfg-abitrate').value = settings.transcode_audio_bitrate || '128k';
        document.getElementById('cfg-deinterlace').checked = settings.transcode_deinterlace || false;
        const orchestratorToggle = document.getElementById('cfg-orchestrator');
        orchestratorToggle.checked = backend.enabled === true;
        orchestratorToggle.disabled = backend.managed_by_environment === true;
        document.getElementById('cfg-orchestrator-toggle').title = orchestratorToggle.disabled
            ? 'El backend está definido por STREAM_BACKEND.'
            : '';

        document.getElementById('cfg-backend').textContent = backend.backend || 'desconocido';
        document.getElementById('cfg-deployment').textContent = backend.backend === 'orchestrator'
            ? (backend.deployment === 'remote' ? 'Orchestrator remoto' : 'Orchestrator local')
            : 'AceXY legacy';
        document.getElementById('cfg-management-endpoint').textContent = backend.base_url || 'no disponible';
        document.getElementById('cfg-effective-endpoint').textContent = backend.public_endpoint || 'no disponible';
        document.getElementById('cfg-token-row').hidden = backend.backend !== 'acexy';

        const panelLink = document.getElementById('cfg-orchestrator-panel');
        if (backend.panel_url) {
            panelLink.href = backend.panel_url;
            panelLink.hidden = false;
            panelLink.style.display = 'inline-block';
        } else {
            panelLink.hidden = true;
            panelLink.style.display = 'none';
        }
        await updateOrchestratorConnectionStatus(backend);

    } catch (e) {
        console.error("Failed to fetch settings:", e);
        document.getElementById('cfg-orchestrator-status').textContent = 'No disponible';
    }
}

async function updateOrchestratorConnectionStatus(backend) {
    const status = document.getElementById('cfg-orchestrator-status');
    if (!backend.enabled) {
        status.textContent = 'Integración desactivada';
        return;
    }
    try {
        const response = await fetch('/api/orchestrator/overview');
        const data = await response.json();
        status.textContent = data.error ? `Error: ${data.error_code || 'conexión'}` : 'Conectado';
    } catch (error) {
        status.textContent = 'Error de conexión';
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
        stream_public_endpoint: document.getElementById('cfg-endpoint').value,
        stream_public_token: document.getElementById('cfg-token').value,
        transcode_video_codec: document.getElementById('cfg-vcodec').value,
        transcode_preset: document.getElementById('cfg-preset').value,
        transcode_audio_bitrate: document.getElementById('cfg-abitrate').value,
        transcode_deinterlace: document.getElementById('cfg-deinterlace').checked
    };
    const orchestratorToggle = document.getElementById('cfg-orchestrator');
    if (!orchestratorToggle.disabled) {
        payload.orchestrator_enabled = orchestratorToggle.checked;
    }

    try {
        const response = await fetch('/api/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        const result = await response.json();
        const feedback = document.getElementById('network-feedback');
        feedback.textContent = response.ok ? 'Configuración guardada.' : (result.message || 'No se pudo guardar.');
        feedback.className = `inline-feedback ${response.ok ? 'success' : 'error'}`;
        if (response.ok) await fetchSettings();
    } catch (e) {
        console.error("Failed to save settings:", e);
        const feedback = document.getElementById('network-feedback');
        feedback.textContent = 'Error de red al guardar.';
        feedback.className = 'inline-feedback error';
    }
}

// Names used by the settings form in index.html.
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

let activeSources = [];

async function loadSourcesDropdown() {
    try {
        const resp = await fetch('/api/sources');
        if (resp.ok) {
            activeSources = await resp.json();
            populateSourceDropdown();
        }
    } catch (e) {
        console.warn('Error loading sources for dropdown:', e);
    }
}

function populateSourceDropdown() {
    const select = document.getElementById('sourceSelect');
    if (!select) return;
    const current = select.value;
    select.replaceChildren();

    const allOpt = document.createElement('option');
    allOpt.value = 'all';
    allOpt.textContent = '📡 Todas las fuentes (Mix)';
    select.appendChild(allOpt);

    const enabledSources = (activeSources || []).filter(s => s.enabled !== false);
    enabledSources.forEach(s => {
        const opt = document.createElement('option');
        opt.value = s.id;
        const countStr = (s.validation && typeof s.validation.channel_count === 'number')
            ? ` (${s.validation.channel_count})`
            : '';
        opt.textContent = `${s.name}${countStr}`;
        select.appendChild(opt);
    });

    if (current && (current === 'all' || enabledSources.some(s => s.id === current))) {
        select.value = current;
    }
}

async function onSourceChange() {
    const sourceVal = document.getElementById('sourceSelect').value;
    const grid = document.getElementById('channel-grid');
    grid.innerHTML = '<div class="loading" style="text-align:center;">Cargando canales…</div>';

    try {
        const url = sourceVal === 'all' ? '/api/channels' : `/api/channels?source=${encodeURIComponent(sourceVal)}`;
        const resp = await fetch(url);
        if (!resp.ok) throw new Error('Error al cargar la fuente');
        allChannels = await resp.json();

        categories.clear();
        allChannels.forEach(ch => { if (ch.group) categories.add(ch.group); });
        populateCategoryDropdown();
        filterChannels();
    } catch (e) {
        const error = element('div', 'loading', `Error: ${e.message}`);
        error.style.color = 'red';
        grid.replaceChildren(error);
    }
}

async function loadChannels(silent = false) {
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

        loadSourcesDropdown();

        const sourceVal = document.getElementById('sourceSelect') ? document.getElementById('sourceSelect').value : 'all';
        const grid = document.getElementById('channel-grid');
        if (!silent && allChannels.length === 0) {
            grid.innerHTML = '<div class="loading" style="text-align:center;">Cargando canales…</div>';
        }

        const url = (sourceVal && sourceVal !== 'all')
            ? `/api/channels?source=${encodeURIComponent(sourceVal)}`
            : '/api/channels';
        const response = await fetch(url);
        if (!response.ok) throw new Error('Error de red');
        const freshChannels = await response.json();

        // Update when initial or channels changed
        const countChanged = freshChannels.length !== allChannels.length;
        if (countChanged || allChannels.length === 0) {
            allChannels = freshChannels;
            categories.clear();
            allChannels.forEach(ch => { if (ch.group) categories.add(ch.group); });
            populateCategoryDropdown();
            filterChannels();
        } else {
            allChannels = freshChannels;
        }

    } catch (e) {
        if (allChannels.length === 0) {
            const grid = document.getElementById('channel-grid');
            const error = element('div', 'loading', `Error: ${e.message}`);
            error.style.color = 'red';
            grid.replaceChildren(error);
        }
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
    channelsToRender.sort((a, b) => {
        const favA = favorites.has(a.id);
        const favB = favorites.has(b.id);
        if (favA && !favB) return -1;
        if (!favA && favB) return 1;
        return a.name.localeCompare(b.name);
    });

    const grid = document.getElementById('channel-grid');
    grid.replaceChildren();

    if (channelsToRender.length === 0) {
        const empty = element('div', 'loading', 'No hay resultados');
        empty.style.gridColumn = '1 / -1';
        grid.appendChild(empty);
        return;
    }

    channelsToRender.forEach(ch => {
        const card = document.createElement('div');
        card.className = 'channel-card';
        card.onclick = () => playChannel(ch);

        const isFav = favorites.has(ch.id);
        const starBtn = element('button', `star-btn ${isFav ? 'active' : ''}`, isFav ? '★' : '☆');
        starBtn.type = 'button';
        starBtn.addEventListener('click', event => toggleFavorite(event, ch.id));

        const statusDot = element('span', 'status-dot dot-grey');
        statusDot.title = 'Nunca visto';
        let techBadgeText = '';
        let lastSeenText = '';

        if (ch.stats) {
            const now = Math.floor(Date.now() / 1000);
            const diff = now - ch.stats.last_ok;

            if (ch.stats.diff_votes && ch.stats.diff_votes < 0) {
                statusDot.className = 'status-dot dot-red';
                statusDot.title = 'Reportado: mala calidad';
            } else if (diff < 86400) {
                statusDot.className = 'status-dot dot-green';
                statusDot.title = 'Visto recientemente';
            } else if (diff < 604800) {
                statusDot.className = 'status-dot dot-yellow';
                statusDot.title = 'Visto esta semana';
            }

            if (diff < 60) lastSeenText = 'Hace instantes';
            else if (diff < 3600) lastSeenText = `Hace ${Math.floor(diff / 60)}m`;
            else if (diff < 86400) lastSeenText = `Hace ${Math.floor(diff / 3600)}h`;
            else lastSeenText = `Hace ${Math.floor(diff / 86400)}d`;

            if (ch.stats.tech_info) {
                const t = ch.stats.tech_info;
                let res = '';
                if (t.height) res = t.height >= 720 ? `${t.height}p` : 'SD';
                if (t.fps) res += `${t.fps}`;

                let codec = t.acodec ? t.acodec.toUpperCase() : '';
                if (codec === 'AC3' || codec === 'EAC3') codec = '🔊 ' + codec;
                else codec = '';

                if (res || codec) {
                    techBadgeText = `${res} ${codec}`.trim();
                }
            }
        }

        const nameLen = ch.name.length;
        let nameStyle = "";
        if (nameLen > 40) nameStyle = "font-size: 0.75rem;";
        else if (nameLen > 25) nameStyle = "font-size: 0.8rem;";

        card.append(starBtn, statusDot);
        const logoUrl = safeLogoUrl(ch.logo);
        if (logoUrl) {
            const image = element('img', 'channel-logo');
            image.src = logoUrl;
            image.alt = '';
            image.loading = 'lazy';
            image.decoding = 'async';
            image.addEventListener('error', () => handleImageError(image, ch.id), { once: true });
            card.appendChild(image);
        } else {
            const fallback = element('div', '', '📺');
            fallback.style.fontSize = '2rem';
            card.appendChild(fallback);
        }
        const name = element('div', 'channel-name', ch.name);
        name.style.cssText = nameStyle;
        card.appendChild(name);

        const sourceLabel = ch.source_name ? ` · ${ch.source_name}` : '';
        const idSource = element('div', 'channel-meta-pill', `[${ch.id.slice(-4)}]${sourceLabel}`);
        card.appendChild(idSource);

        if (techBadgeText) card.appendChild(element('div', 'tech-badge', techBadgeText));
        if (lastSeenText) card.appendChild(element('div', 'last-seen', lastSeenText));
        grid.appendChild(card);
    });
}


function isIOS() {
    return [
        'iPad Simulator', 'iPhone Simulator', 'iPod Simulator', 'iPad', 'iPhone', 'iPod'
    ].includes(navigator.platform) || (navigator.userAgent.includes("Mac") && "ontouchend" in document);
}

let loadTimeout = null;
let hasPlayedSuccessfully = false;
let statsInterval;
let engineInfoInterval;

// Orchestrator engine information
async function fetchEngineInfo(aceId, isUpdate = false) {
    const container = document.getElementById('player-engine-info');
    if (!container) return;

    if (!isUpdate) {
        container.replaceChildren();
        const dot = element('span', 'status-dot dot-grey');
        dot.style.cssText = 'position:static; display:inline-block; margin-right:5px;';
        container.append(dot, document.createTextNode('Buscando info...'));
    }
    // console.log(`[EngineInfo] Fetching for ID: ${aceId} (Update: ${isUpdate})`);

    try {
        const [engRes, strRes] = await Promise.all([
            fetch('/api/orchestrator/status'),
            fetch('/api/orchestrator/streams')
        ]);

        const engines = await engRes.json();
        const streams = await strRes.json();

        container.replaceChildren();
        let identified = false;

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
                const dot = element('span', 'status-dot');
                dot.style.cssText = `position:static; display:inline-block; margin-right:5px; background:${isHealthy ? '#2ea043' : '#da3633'}`;
                container.append(dot, document.createTextNode('Engine: '));
                container.appendChild(element('strong', '', String(engine.container_name || 'sin nombre')));
                identified = true;
            }
        }

        // Stream Stats
        if (stream) {
            const peers = stream.peers !== undefined ? stream.peers : 0;
            const downVal = stream.speed_down ? stream.speed_down : 0;
            const stats = element('span', '', `| 👤 ${peers} | ⬇️ ${downVal} KB/s`);
            stats.style.cssText = 'margin-left:10px; opacity:0.8;';
            container.appendChild(stats);
            identified = true;
        }

        if (!identified) container.textContent = 'Motor no identificado';

    } catch (e) {
        console.error("Engine info error", e);
        container.textContent = '';
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
    document.getElementById('player-title').textContent = `${channel.name} [${channel.id.slice(-4)}]`;

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
    currentIdentifierType = channel.identifier_type || 'id';

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
    hasPlayedSuccessfully = false;
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

            // 1. Recover media errors (PTS discontinuities / buffer holes)
            if (data.type === Hls.ErrorTypes.MEDIA_ERROR && hlsInstance) {
                console.log('[Player] Recovering media error...');
                hlsInstance.recoverMediaError();
                setTimeout(() => {
                    const stillStalled = player.readyState < 2 || (player.paused && hasPlayedSuccessfully);
                    if (stillStalled && generation === playbackGeneration && currentAceId === aceId) {
                        recoverPlayback('El reproductor no pudo recuperarse del fallo de medio.', true);
                    }
                }, 5000);
                return;
            }

            // 2. Recover network errors (transient segment delays)
            if (data.type === Hls.ErrorTypes.NETWORK_ERROR && hlsInstance) {
                console.log('[Player] Recovering network error...');
                hlsInstance.startLoad();
                setTimeout(() => {
                    if (player.readyState < 2 && generation === playbackGeneration && currentAceId === aceId) {
                        recoverPlayback('Corte de red en el flujo HLS.', true);
                    }
                }, 6000);
                return;
            }

            // 3. Any other non-recoverable error triggers recovery/failover
            recoverPlayback('Fallo crítico en flujo HLS.', true);
        });

        const onProgressing = () => {
            if (loadTimeout) {
                clearTimeout(loadTimeout);
                loadTimeout = null;
            }
            if (player.currentTime > 0.1) {
                hasPlayedSuccessfully = true;
            }
            hidePlayerStatus();
        };

        player.addEventListener('playing', onProgressing);
        player.addEventListener('timeupdate', () => {
            if (player.currentTime > 0.1) {
                onProgressing();
            }
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
        let url = `/api/hls/start/${aceId}?profile=${encodeURIComponent(currentProfile)}`;
        if (currentIdentifierType === 'infohash') url += '&identifier_type=infohash';
        if (force) url += '&force=1';

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

            // Timeout Logic (35 seconds) - Trigger recovery ONLY if completely unresponsive on startup
            if (loadTimeout) clearTimeout(loadTimeout);
            loadTimeout = setTimeout(() => {
                if (!hasPlayedSuccessfully && (player.readyState < 2 || player.paused) && currentAceId === aceId) {
                    console.warn("[Player] Stream startup timeout without playable frames");
                    recoverPlayback('La señal tardó más de 35s en arrancar.', true);
                }
            }, 35000);

            const onStarted = () => {
                if (loadTimeout) {
                    clearTimeout(loadTimeout);
                    loadTimeout = null;
                }
                hasPlayedSuccessfully = true;
                hidePlayerStatus();
            };
            player.addEventListener('playing', onStarted, { once: true });
            player.addEventListener('timeupdate', () => {
                if (player.currentTime > 0.1) onStarted();
            });

        } else {
            if (triggerMatchFailover("Señal no disponible o sin peers.")) {
                return;
            }
            const msg = data.message || `Error servidor: ${data.status}`;
            showPlayerStatus('Stream no disponible', msg, { icon: '⚠️', retry: data.retryable !== false });
        }
    } catch (e) {
        if (e.name === 'AbortError') {
            console.log("Fetch aborted (user closed player or switched)");
        } else {
            console.error(e);
            if (triggerMatchFailover("Error de conexión con el servidor.")) {
                return;
            }
            showPlayerStatus('Error de conexión', 'No se pudo contactar con el servidor HLS.', { icon: '⚠️', retry: true });
        }
    }
}

function recoverPlayback(reason, forceRestart) {
    if (!currentAceId) return;

    if (playbackRetryCount < MAX_PLAYBACK_RECOVERY_ATTEMPTS) {
        playbackRetryCount++;
        showPlayerStatus('Reintentando stream', `${reason} Intento ${playbackRetryCount}/${MAX_PLAYBACK_RECOVERY_ATTEMPTS}...`);
        setTimeout(() => {
            if (currentAceId) {
                startPlayback(currentAceId, currentProfile, { force: forceRestart, resetRetries: false });
            }
        }, 1500);
        return;
    }

    // Only after retries on the current stream have failed, trigger failover
    if (triggerMatchFailover(reason)) {
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
    currentIdentifierType = 'id';
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

function downloadAgendaM3U(profile = 'all') {
    const url = `/agenda.m3u?profile=${encodeURIComponent(profile)}`;
    window.location.href = url;
    toggleM3UMenu();
}

function copyAgendaM3ULink(profile = 'all') {
    const url = `${window.location.origin}/agenda.m3u?profile=${encodeURIComponent(profile)}`;
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(url).then(() => {
            alert('Enlace M3U de Agenda copiado al portapapeles');
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

// Sources 2.0 and custom channels
let editingSourceId = null;
let editingCustomId = null;

function openSettings() {
    document.getElementById('settings-modal').style.display = 'flex';
    loadSources();
    loadCustomChannels();
}

function closeSettings() {
    document.getElementById('settings-modal').style.display = 'none';
}

document.getElementById('settings-modal').addEventListener('click', (e) => {
    if (e.target.id === 'settings-modal') closeSettings();
});

function showInlineFeedback(targetId, message, type = '') {
    const target = document.getElementById(targetId);
    target.textContent = message || '';
    target.className = `inline-feedback${message ? ' visible' : ''}${type ? ` ${type}` : ''}`;
}

async function responseJson(response) {
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        const error = new Error(data.error || `Error HTTP ${response.status}`);
        error.status = response.status;
        error.data = data;
        throw error;
    }
    return data;
}

function formatTimestamp(value) {
    if (!value) return 'sin datos';
    return new Date(value * 1000).toLocaleString();
}

function actionButton(label, title, handler, className = '') {
    const button = element('button', className, label);
    button.type = 'button';
    button.title = title;
    button.addEventListener('click', handler);
    return button;
}

async function loadSources() {
    const list = document.getElementById('sources-list');
    list.replaceChildren(element('div', 'source-row', 'Cargando fuentes…'));
    try {
        const sources = await responseJson(await fetch('/api/sources'));

        list.replaceChildren();
        if (sources.length === 0) {
            list.appendChild(element('div', 'source-row', 'No hay fuentes configuradas'));
            return;
        }

        sources.forEach(src => {
            const row = element('div', 'source-row');
            const toggle = element('input', 'source-toggle');
            toggle.type = 'checkbox';
            toggle.checked = src.enabled === true;
            toggle.title = src.enabled ? 'Desactivar fuente' : 'Validar y activar fuente';
            toggle.addEventListener('change', () => setSourceEnabled(src, toggle.checked));

            const main = element('div', 'source-main');
            const heading = element('div', 'source-heading');
            heading.appendChild(element('span', '', src.name));
            if (src.kind === 'mylinkpaste') {
                heading.appendChild(element('span', 'status-badge mylinkpaste', 'MylinkPaste'));
            }
            const validation = src.validation || {};
            const status = src.enabled ? (validation.status || 'pending') : 'disabled';
            heading.appendChild(element('span', `status-badge ${status}`, status));
            const url = element('div', 'source-url', src.url);
            url.title = src.url;
            const refresh = src.refresh || {};
            const meta = element(
                'div',
                'source-meta',
                `${validation.channel_count || 0} canales · última comprobación ${formatTimestamp(validation.checked_at)}${refresh.using_cache ? ' · usando caché' : ''}`,
            );
            main.append(heading, url, meta);
            const errorText = validation.error || refresh.last_error;
            if (errorText) main.appendChild(element('div', 'source-error', errorText));

            const actions = element('div', 'source-actions');
            actions.append(
                actionButton('Validar', 'Comprobar ahora', () => revalidateSource(src.id)),
                actionButton('Editar', 'Editar fuente', () => editSource(src)),
                actionButton('Eliminar', 'Eliminar fuente', () => deleteSourceById(src.id), 'delete-btn'),
            );
            row.append(toggle, main, actions);
            list.appendChild(row);
        });
    } catch (e) {
        list.replaceChildren(element('div', 'source-row source-error', e.message));
    }
}

function editSource(source) {
    editingSourceId = source.id;
    document.getElementById('sourceName').value = source.name;
    document.getElementById('sourceUrl').value = source.url;
    document.getElementById('sourceSaveButton').textContent = 'Validar y guardar';
    document.getElementById('sourceCancelButton').hidden = false;
    showInlineFeedback('source-feedback', `Editando ${source.name}`);
}

function cancelSourceEdit() {
    editingSourceId = null;
    document.getElementById('sourceName').value = '';
    document.getElementById('sourceUrl').value = '';
    document.getElementById('sourceSaveButton').textContent = 'Validar y añadir';
    document.getElementById('sourceCancelButton').hidden = true;
    showInlineFeedback('source-feedback', '');
}

async function saveSource() {
    let name = document.getElementById('sourceName').value.trim();
    const url = document.getElementById('sourceUrl').value.trim();
    if (!url) {
        showInlineFeedback('source-feedback', 'La URL o ID es obligatorio.', 'error');
        return;
    }
    if (!name) {
        if (url.toLowerCase().startsWith('mylinkpaste://') || (!url.startsWith('http://') && !url.startsWith('https://'))) {
            const raw = url.replace('mylinkpaste://', '').trim();
            name = `MylinkPaste (${raw.slice(0, 8)})`;
            document.getElementById('sourceName').value = name;
        } else {
            showInlineFeedback('source-feedback', 'Nombre y URL son obligatorios.', 'error');
            return;
        }
    }

    const endpoint = editingSourceId ? `/api/sources/${editingSourceId}` : '/api/sources';
    const method = editingSourceId ? 'PATCH' : 'POST';
    const payload = { name, url };
    showInlineFeedback('source-feedback', 'Descargando y validando la fuente…');

    try {
        let response = await fetch(endpoint, {
            method,
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        if (response.status === 422) {
            const invalid = await response.json();
            if (!confirm(`${invalid.error}\n\n¿Guardar la fuente desactivada para revalidarla más adelante?`)) {
                throw Object.assign(new Error(invalid.error), { status: 422 });
            }
            payload.allow_invalid_disabled = true;
            response = await fetch(endpoint, {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
        }
        await responseJson(response);
        cancelSourceEdit();
        showInlineFeedback('source-feedback', 'Fuente guardada correctamente.', 'success');
        await Promise.all([loadSources(), loadChannels()]);
    } catch (e) {
        showInlineFeedback('source-feedback', e.message, 'error');
    }
}

async function setSourceEnabled(source, enabled) {
    try {
        showInlineFeedback('source-feedback', enabled ? 'Validando antes de activar…' : 'Desactivando fuente…');
        await responseJson(await fetch(`/api/sources/${source.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ enabled }),
        }));
        showInlineFeedback('source-feedback', enabled ? 'Fuente activada.' : 'Fuente desactivada.', 'success');
        await Promise.all([loadSources(), loadChannels()]);
    } catch (e) {
        showInlineFeedback('source-feedback', e.message, 'error');
        await loadSources();
    }
}

async function revalidateSource(sourceId) {
    showInlineFeedback('source-feedback', 'Revalidando fuente…');
    try {
        await responseJson(await fetch(`/api/sources/${sourceId}/validate`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: '{}',
        }));
        showInlineFeedback('source-feedback', 'Fuente válida; caché actualizada.', 'success');
        await Promise.all([loadSources(), loadChannels()]);
    } catch (e) {
        showInlineFeedback('source-feedback', e.message, 'error');
        await loadSources();
    }
}

async function deleteSourceById(sourceId) {
    if (!confirm('¿Eliminar esta fuente y su caché?')) return;
    try {
        await responseJson(await fetch(`/api/sources/${sourceId}`, { method: 'DELETE' }));
        showInlineFeedback('source-feedback', 'Fuente eliminada.', 'success');
        await Promise.all([loadSources(), loadChannels()]);
    } catch (e) {
        showInlineFeedback('source-feedback', e.message, 'error');
    }
}

async function refreshChannelsFromServer() {
    const btn = document.querySelector('#settings-modal .modal-actions button');
    const originalText = btn.textContent;
    btn.textContent = "Actualizando...";
    btn.disabled = true;

    try {
        await responseJson(await fetch('/api/sources/refresh', { method: 'POST' }));
        showInlineFeedback('source-feedback', 'Canales actualizados correctamente.', 'success');
        await Promise.all([loadSources(), loadChannels()]);
    } catch (e) {
        showInlineFeedback('source-feedback', e.message, 'error');
    } finally {
        btn.textContent = originalText;
        btn.disabled = false;
    }
}

async function loadCustomChannels() {
    const list = document.getElementById('custom-channels-list');
    list.replaceChildren(element('div', 'source-row', 'Cargando canales…'));
    try {
        const channels = await responseJson(await fetch('/api/custom-channels'));
        list.replaceChildren();
        if (!channels.length) {
            list.appendChild(element('div', 'source-row', 'No hay canales personalizados'));
            return;
        }
        channels.forEach(channel => {
            const row = element('div', 'source-row');
            const main = element('div', 'source-main');
            main.append(
                element('div', 'source-heading', channel.name),
                element('div', 'source-meta', `${channel.identifier_type} · ${channel.stream_id}`),
                element('div', 'source-meta', `${channel.group || 'Personalizados'}${channel.tvg_id ? ` · tvg-id ${channel.tvg_id}` : ''}`),
            );
            const actions = element('div', 'source-actions');
            actions.append(
                actionButton('Editar', 'Editar canal', () => editCustomChannel(channel)),
                actionButton('Eliminar', 'Eliminar canal', () => deleteCustomChannel(channel.id), 'delete-btn'),
            );
            row.append(main, actions);
            list.appendChild(row);
        });
    } catch (e) {
        list.replaceChildren(element('div', 'source-row source-error', e.message));
    }
}

function editCustomChannel(channel) {
    editingCustomId = channel.id;
    document.getElementById('customName').value = channel.name;
    document.getElementById('customStreamId').value = channel.stream_id;
    document.getElementById('customGroup').value = channel.group || '';
    document.getElementById('customLogo').value = channel.logo || '';
    document.getElementById('customTvgId').value = channel.tvg_id || '';
    document.getElementById('customSaveButton').textContent = 'Guardar canal';
    document.getElementById('customCancelButton').hidden = false;
}

function cancelCustomEdit() {
    editingCustomId = null;
    ['customName', 'customStreamId', 'customGroup', 'customLogo', 'customTvgId'].forEach(id => {
        document.getElementById(id).value = '';
    });
    document.getElementById('customSaveButton').textContent = 'Añadir canal';
    document.getElementById('customCancelButton').hidden = true;
    showInlineFeedback('custom-feedback', '');
}

async function saveCustomChannel() {
    const payload = {
        name: document.getElementById('customName').value.trim(),
        stream_id: document.getElementById('customStreamId').value.trim(),
        group: document.getElementById('customGroup').value.trim() || 'Personalizados',
        logo: document.getElementById('customLogo').value.trim(),
        tvg_id: document.getElementById('customTvgId').value.trim(),
    };
    if (!payload.name || !payload.stream_id) {
        showInlineFeedback('custom-feedback', 'Nombre e identificador son obligatorios.', 'error');
        return;
    }
    try {
        await responseJson(await fetch(editingCustomId ? `/api/custom-channels/${editingCustomId}` : '/api/custom-channels', {
            method: editingCustomId ? 'PATCH' : 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        }));
        cancelCustomEdit();
        showInlineFeedback('custom-feedback', 'Canal guardado correctamente.', 'success');
        await Promise.all([loadCustomChannels(), loadChannels()]);
    } catch (e) {
        showInlineFeedback('custom-feedback', e.message, 'error');
    }
}

async function deleteCustomChannel(channelId) {
    if (!confirm('¿Eliminar este canal personalizado?')) return;
    try {
        await responseJson(await fetch(`/api/custom-channels/${channelId}`, { method: 'DELETE' }));
        showInlineFeedback('custom-feedback', 'Canal eliminado.', 'success');
        await Promise.all([loadCustomChannels(), loadChannels()]);
    } catch (e) {
        showInlineFeedback('custom-feedback', e.message, 'error');
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
    techDiv.replaceChildren();
    let res = '';
    if (t.height) res = t.height >= 720 ? `${t.height}p` : 'SD';
    if (t.fps) res += ` ${t.fps}fps`;

    let codec = t.acodec ? t.acodec.toUpperCase() : '';
    if (codec === 'AC3' || codec === 'EAC3') codec = '🔊 ' + codec;
    else codec = '';

    if (res || codec) {
        const badge = element('span', 'tech-badge', `${res} ${codec}`.trim());
        badge.style.cssText = 'font-size:0.9rem; padding:4px 8px;';
        techDiv.appendChild(badge);
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

/* ==========================================================================
   Sports Agenda (EPG) Logic
   ========================================================================== */
let currentMainView = 'channels';
let agendaData = null;
let selectedAgendaDay = 'all';
let trackedMatchEvents = new Set();
let probedMatchStreams = {};
let probingMatches = new Set();

function loadTrackedMatches() {
    try {
        const stored = localStorage.getItem('ace_tracked_matches');
        if (stored) {
            trackedMatchEvents = new Set(JSON.parse(stored));
        }
    } catch (e) {
        trackedMatchEvents = new Set();
    }
}

function saveTrackedMatches() {
    try {
        localStorage.setItem('ace_tracked_matches', JSON.stringify(Array.from(trackedMatchEvents)));
    } catch (e) {}
}

let trackedMatchesScheduleTimer = null;

function getMinutesUntilEvent(dateStr, timeStr) {
    if (!dateStr || !timeStr) return null;
    try {
        const parts = dateStr.split('/');
        const timeParts = timeStr.split(':');
        if (parts.length < 3 || timeParts.length < 2) return null;
        const day = parseInt(parts[0], 10);
        const month = parseInt(parts[1], 10) - 1;
        const year = parseInt(parts[2], 10);
        const hour = parseInt(timeParts[0], 10);
        const min = parseInt(timeParts[1], 10);
        const eventDate = new Date(year, month, day, hour, min);
        const now = new Date();
        return (eventDate.getTime() - now.getTime()) / 60000;
    } catch (e) {
        return null;
    }
}

async function toggleTrackMatch(eventKey, streams, isSoon = false) {
    if (trackedMatchEvents.has(eventKey)) {
        trackedMatchEvents.delete(eventKey);
        delete probedMatchStreams[eventKey];
    } else {
        trackedMatchEvents.add(eventKey);
        // Solo sonda automáticamente si el partido está en vivo o arranca en <= 15 min
        if (isSoon && streams && streams.length > 0) {
            probeMatchStreams(eventKey, streams);
        }
    }
    saveTrackedMatches();
    filterAgenda();
}

function checkTrackedMatchesSchedule() {
    if (!agendaData || !agendaData.days) return;

    agendaData.days.forEach(day => {
        (day.events || []).forEach(ev => {
            const eventKey = `${day.date || ''}_${ev.time || ''}_${ev.event || ''}`;
            if (!trackedMatchEvents.has(eventKey)) return;

            if (probedMatchStreams[eventKey] || probingMatches.has(eventKey)) return;

            const diffMin = (typeof ev.starts_in_minutes === 'number')
                ? ev.starts_in_minutes
                : getMinutesUntilEvent(day.date, ev.time);

            const isDue = ev.is_soon || ev.is_live || (diffMin !== null && diffMin <= 15 && diffMin >= -135);

            if (isDue && ev.available && ev.streams && ev.streams.length > 0) {
                console.log(`[Auto-Probe] Tracked match "${ev.event}" reached T-15m window (~${Math.round(diffMin || 0)}m). Probing live signals...`);
                probeMatchStreams(eventKey, ev.streams);
            }
        });
    });
}

async function probeMatchStreams(eventKey, streams) {
    if (!streams || streams.length === 0 || probingMatches.has(eventKey)) return;

    probingMatches.add(eventKey);
    filterAgenda();

    try {
        const candidates = streams.slice(0, 4);
        const res = await fetch('/api/agenda/probe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                streams: candidates,
                max_candidates: 3,
                stop_at_live: 2
            })
        });

        if (res.ok) {
            const data = await res.json();
            if (data.status === 'ok') {
                probedMatchStreams[eventKey] = data.probed || {};
            }
        }
    } catch (e) {
        console.error("Error probing match streams:", e);
    } finally {
        probingMatches.delete(eventKey);
        filterAgenda();
    }
}

function switchMainView(view) {
    currentMainView = view;
    const channelsView = document.getElementById('channels-view');
    const agendaView = document.getElementById('agenda-view');
    const channelsControls = document.getElementById('channels-controls');
    const tabChannels = document.getElementById('tabChannels');
    const tabAgenda = document.getElementById('tabAgenda');

    if (view === 'agenda') {
        if (channelsView) channelsView.style.display = 'none';
        if (agendaView) agendaView.style.display = 'block';
        if (channelsControls) channelsControls.style.display = 'none';
        if (tabChannels) tabChannels.classList.remove('active');
        if (tabAgenda) tabAgenda.classList.add('active');

        if (!agendaData) {
            loadAgenda();
        }
    } else {
        if (channelsView) channelsView.style.display = 'block';
        if (agendaView) agendaView.style.display = 'none';
        if (channelsControls) channelsControls.style.display = 'flex';
        if (tabChannels) tabChannels.classList.add('active');
        if (tabAgenda) tabAgenda.classList.remove('active');
    }
}

async function loadAgenda(forceRefresh = false) {
    loadTrackedMatches();
    const container = document.getElementById('agenda-container');
    const statusPill = document.getElementById('agendaStatus');

    if (container) {
        container.textContent = '';
        const loadingDiv = element('div', 'loading', '⏳ Cargando agenda deportiva...');
        loadingDiv.style.textAlign = 'center';
        loadingDiv.style.padding = '30px';
        container.appendChild(loadingDiv);
    }

    try {
        const url = forceRefresh ? '/api/agenda?refresh=1' : '/api/agenda';
        const res = await fetch(url);
        if (!res.ok) {
            throw new Error(`HTTP ${res.status}`);
        }
        agendaData = await res.json();

        if (statusPill && agendaData) {
            const total = agendaData.total_events || 0;
            const avail = agendaData.available_events || 0;
            statusPill.textContent = `📡 ${avail} disponibles / ${total} eventos`;
        }

        populateCompetitionFilter();
        updateDayTabs();
        filterAgenda();

        if (!trackedMatchesScheduleTimer) {
            trackedMatchesScheduleTimer = setInterval(checkTrackedMatchesSchedule, 60000);
        }
        checkTrackedMatchesSchedule();
    } catch (err) {
        console.error("Error loading sports agenda:", err);
        if (container) {
            container.textContent = '';
            const errDiv = element('div', 'loading', `❌ Error al cargar la agenda deportiva (${err.message}). Reintenta en unos instantes.`);
            errDiv.style.textAlign = 'center';
            errDiv.style.color = '#ff6b6b';
            errDiv.style.padding = '30px';
            container.appendChild(errDiv);
        }
    }
}

function populateCompetitionFilter() {
    const select = document.getElementById('agendaCompSelect');
    if (!select || !agendaData || !agendaData.days) return;
    const currentVal = select.value;
    const comps = new Set();
    agendaData.days.forEach(day => {
        (day.events || []).forEach(ev => {
            if (ev.competition && ev.competition.trim()) {
                comps.add(ev.competition.trim());
            }
        });
    });
    const sortedComps = Array.from(comps).sort((a, b) => a.localeCompare(b, 'es', { sensitivity: 'base' }));
    select.textContent = '';
    const defOpt = element('option', '', '🏆 Todas las competiciones');
    defOpt.value = '';
    select.appendChild(defOpt);
    sortedComps.forEach(c => {
        const opt = element('option', '', c);
        opt.value = c;
        if (c === currentVal) opt.selected = true;
        select.appendChild(opt);
    });
}

function updateDayTabs() {
    const tabsContainer = document.getElementById('agendaDayTabs');
    if (!tabsContainer || !agendaData || !agendaData.days) return;
    const availableOnly = !!document.getElementById('agendaAvailableOnly')?.checked;

    const dayButtons = tabsContainer.querySelectorAll('.day-tab-btn');
    dayButtons.forEach(btn => {
        const dAttr = btn.getAttribute('data-day');
        if (dAttr === 'all') {
            let totalAll = 0;
            agendaData.days.forEach(d => {
                totalAll += (d.events || []).filter(e => !availableOnly || e.available).length;
            });
            btn.textContent = `📅 Todos (${totalAll})`;
        } else {
            const idx = parseInt(dAttr, 10);
            const d = agendaData.days[idx];
            if (d) {
                const count = (d.events || []).filter(e => !availableOnly || e.available).length;
                const prefix = idx === 0 ? '⚽ Hoy' : (idx === 1 ? '🗓️ Mañana' : '🗓️ Pasado');
                btn.textContent = `${prefix} (${count})`;
                btn.style.display = 'inline-flex';
            } else {
                btn.style.display = 'none';
            }
        }
    });
}

function selectAgendaDay(dayAttr) {
    selectedAgendaDay = String(dayAttr);
    const tabs = document.querySelectorAll('#agendaDayTabs .day-tab-btn');
    tabs.forEach(t => {
        if (t.getAttribute('data-day') === selectedAgendaDay) {
            t.classList.add('active');
        } else {
            t.classList.remove('active');
        }
    });
    filterAgenda();
}

function filterAgenda() {
    if (!agendaData || !agendaData.days) return;

    const query = (document.getElementById('agendaSearchInput')?.value || '').trim().toLowerCase();
    const selectedComp = (document.getElementById('agendaCompSelect')?.value || '').trim().toLowerCase();
    const availableOnly = !!document.getElementById('agendaAvailableOnly')?.checked;
    const liveOnly = !!document.getElementById('agendaLiveOnly')?.checked;

    updateDayTabs();

    const filteredDays = [];

    agendaData.days.forEach((day, idx) => {
        if (selectedAgendaDay !== 'all' && String(idx) !== selectedAgendaDay) {
            return;
        }

        const matchingEvents = (day.events || []).filter(ev => {
            if (availableOnly && !ev.available) return false;
            if (liveOnly && !ev.is_live) return false;

            if (selectedComp) {
                const comp = (ev.competition || '').trim().toLowerCase();
                if (comp !== selectedComp) return false;
            }

            if (query) {
                const eventText = (ev.event || '').toLowerCase();
                const compText = (ev.competition || '').toLowerCase();
                const chanText = (ev.channels || []).join(' ').toLowerCase();
                const streamsText = (ev.streams || []).map(s => s.channel_name || '').join(' ').toLowerCase();

                if (!eventText.includes(query) && !compText.includes(query) && !chanText.includes(query) && !streamsText.includes(query)) {
                    return false;
                }
            }
            return true;
        });

        if (matchingEvents.length > 0) {
            filteredDays.push({
                ...day,
                events: matchingEvents,
                events_count: matchingEvents.length
            });
        }
    });

    renderAgenda(filteredDays);
}

function renderAgenda(days) {
    const container = document.getElementById('agenda-container');
    if (!container) return;

    container.textContent = '';

    if (!days || days.length === 0) {
        const emptyDiv = element('div', 'loading', 'No se han encontrado eventos deportivos con los filtros seleccionados.');
        emptyDiv.style.textAlign = 'center';
        emptyDiv.style.padding = '40px';
        emptyDiv.style.color = '#888';
        container.appendChild(emptyDiv);
        return;
    }

    days.forEach(day => {
        const section = element('section', 'agenda-day-section');

        const header = element('div', 'agenda-day-header');
        const titleSpan = element('span', '', `📅 ${day.title || day.date}`);
        const countSpan = element('span', 'agenda-day-count', `${day.events_count} eventos`);
        header.appendChild(titleSpan);
        header.appendChild(countSpan);
        section.appendChild(header);

        const pastEvents = (day.events || []).filter(e => e.is_past);
        const activeEvents = (day.events || []).filter(e => !e.is_past);

        if (pastEvents.length > 0) {
            const toggleBar = element('div', 'agenda-past-toggle-bar');
            const pastGrid = element('div', 'agenda-grid agenda-past-grid');
            const showInitially = activeEvents.length === 0;
            pastGrid.style.display = showInitially ? 'grid' : 'none';

            const toggleBtn = element(
                'button',
                'agenda-past-toggle-btn',
                showInitially
                    ? `🔼 Ocultar ${pastEvents.length} eventos anteriores de hoy`
                    : `⏪ Ver ${pastEvents.length} evento(s) anteriores de hoy`
            );
            toggleBtn.onclick = () => {
                const isHidden = pastGrid.style.display === 'none';
                pastGrid.style.display = isHidden ? 'grid' : 'none';
                toggleBtn.textContent = isHidden
                    ? `🔼 Ocultar ${pastEvents.length} eventos anteriores de hoy`
                    : `⏪ Ver ${pastEvents.length} evento(s) anteriores de hoy`;
            };
            toggleBar.appendChild(toggleBtn);
            section.appendChild(toggleBar);

            pastEvents.forEach(ev => renderAgendaCard(ev, day, pastGrid));
            section.appendChild(pastGrid);
        }

        const mainGrid = element('div', 'agenda-grid');
        activeEvents.forEach(ev => renderAgendaCard(ev, day, mainGrid));
        section.appendChild(mainGrid);

        container.appendChild(section);
    });
}

function renderAgendaCard(ev, day, targetContainer) {
    const eventKey = `${day.date || ''}_${ev.time || ''}_${ev.event || ''}`;
    const isTracked = trackedMatchEvents.has(eventKey);
    const isProbing = probingMatches.has(eventKey);
    const probeData = probedMatchStreams[eventKey] || null;

    const diffMin = (typeof ev.starts_in_minutes === 'number')
        ? ev.starts_in_minutes
        : getMinutesUntilEvent(day.date, ev.time);
    const isSoon = ev.is_soon || ev.is_live || (diffMin !== null && diffMin <= 15 && diffMin >= -135);

    const card = element('div', 'agenda-card' + (ev.is_live ? ' is-live' : '') + (isTracked ? ' is-tracked' : '') + (ev.is_past ? ' is-past' : ''));

    // Card Header
    const cardHeader = element('div', 'agenda-card-header');

    const timeWrapper = element('div', 'agenda-time-wrapper');
    const starBtn = element('button', 'track-event-btn' + (isTracked ? ' active' : ''), isTracked ? '★' : '☆');
    starBtn.title = isTracked
        ? 'Seguimiento activo (clic para desactivar)'
        : (isSoon
            ? 'Marcar partido en seguimiento (comprueba señales vivas ahora)'
            : 'Marcar partido en seguimiento (se comprobará 15 min antes del partido)');
    starBtn.onclick = (e) => {
        e.stopPropagation();
        toggleTrackMatch(eventKey, ev.streams || [], isSoon);
    };
    timeWrapper.appendChild(starBtn);
    timeWrapper.appendChild(element('span', 'agenda-time', `⏰ ${ev.time}`));
    cardHeader.appendChild(timeWrapper);

    const badgesDiv = element('div');
    badgesDiv.style.display = 'flex';
    badgesDiv.style.gap = '4px';
    badgesDiv.style.alignItems = 'center';

    if (isTracked && ev.available && ev.streams && ev.streams.length > 0) {
        if (isSoon) {
            const probeBtn = element(
                'button',
                'probe-refresh-btn',
                isProbing ? '⏳ Probando...' : (probeData ? '⚡ Recomprobar' : '⚡ Comprobar')
            );
            probeBtn.title = 'Comprueba en segundo plano las señales vivas de este evento';
            probeBtn.onclick = (e) => {
                e.stopPropagation();
                probeMatchStreams(eventKey, ev.streams);
            };
            badgesDiv.appendChild(probeBtn);
        } else {
            const schedPill = element('span', 'agenda-badge badge-scheduled', '⭐ Auto T-15m');
            schedPill.title = 'Seguimiento activo: se comprobarán las señales automáticamente 15 minutos antes de la hora';
            badgesDiv.appendChild(schedPill);

            const manualBtn = element(
                'button',
                'probe-refresh-btn',
                isProbing ? '⏳ Probando...' : (probeData ? '⚡ Recomprobar' : '⚡ Probar ahora')
            );
            manualBtn.title = 'Comprobar señales ahora de forma manual';
            manualBtn.onclick = (e) => {
                e.stopPropagation();
                probeMatchStreams(eventKey, ev.streams);
            };
            badgesDiv.appendChild(manualBtn);
        }
    }

    if (ev.is_live) {
        badgesDiv.appendChild(element('span', 'agenda-badge badge-live', '⚡ En Directo'));
    } else if (ev.is_past) {
        badgesDiv.appendChild(element('span', 'agenda-badge badge-unavailable', 'Finalizado'));
    } else if (ev.is_upcoming) {
        badgesDiv.appendChild(element('span', 'agenda-badge badge-upcoming', '⏳ Próximamente'));
    }

    if (ev.available) {
        const label = `🟢 ${ev.streams_count} señal${ev.streams_count > 1 ? 'es' : ''}`;
        badgesDiv.appendChild(element('span', 'agenda-badge badge-available', label));
    } else {
        badgesDiv.appendChild(element('span', 'agenda-badge badge-unavailable', '⚪ Sin señal'));
    }

    cardHeader.appendChild(badgesDiv);
    card.appendChild(cardHeader);

    // Competition
    if (ev.competition) {
        const compDiv = element('div', 'agenda-competition');
        if (ev.competition_icon) {
            const icon = document.createElement('img');
            icon.src = ev.competition_icon;
            icon.className = 'agenda-comp-icon';
            icon.alt = '';
            compDiv.appendChild(icon);
        } else {
            compDiv.appendChild(element('span', '', '🏆'));
        }
        compDiv.appendChild(element('span', '', ev.competition));
        card.appendChild(compDiv);
    }

    // Event Title
    card.appendChild(element('div', 'agenda-event-title', ev.event));

    // TV Channels
    if (ev.channels && ev.channels.length > 0) {
        const tvDiv = element('div', 'agenda-tv-channels');
        ev.channels.forEach(ch => {
            tvDiv.appendChild(element('span', 'tv-tag', `📺 ${ch}`));
        });
        card.appendChild(tvDiv);
    }

    // Streams row
    if (ev.available && ev.streams && ev.streams.length > 0) {
        const streamsRow = element('div', 'agenda-streams-row');

        let sortedStreams = (ev.streams || []).slice();
        if (probeData) {
            sortedStreams.sort((a, b) => {
                const aLive = probeData[a.stream_id]?.alive ? 1 : 0;
                const bLive = probeData[b.stream_id]?.alive ? 1 : 0;
                return bLive - aLive;
            });
        }

        const primary = sortedStreams[0];
        const pLive = probeData && probeData[primary.stream_id]?.alive;
        const pDown = probeData && probeData[primary.stream_id]?.alive === false;
        const primaryLiveTag = pLive ? ' 🟢 UP' : (pDown ? ' ⚪' : '');

        const primaryBtn = element(
            'button',
            'stream-play-btn' + (pLive ? ' is-probed-live' : ''),
            `▶ Ver (${primary.quality} · ${primary.source_name}${primaryLiveTag})`
        );
        primaryBtn.onclick = () => playAgendaStream(primary.stream_id, primary.channel_name, sortedStreams, 0, ev.event);
        streamsRow.appendChild(primaryBtn);

        if (sortedStreams.length > 1) {
            sortedStreams.slice(1).forEach((st, idx) => {
                const sLive = probeData && probeData[st.stream_id]?.alive;
                const sDown = probeData && probeData[st.stream_id]?.alive === false;
                const optLiveTag = sLive ? ' 🟢 UP' : (sDown ? ' ⚪' : '');
                const optBtn = element(
                    'button',
                    'stream-opt-btn' + (sLive ? ' is-probed-live' : '') + (sDown ? ' is-probed-down' : ''),
                    `${st.quality} · ${st.source_name}${optLiveTag}`
                );
                optBtn.title = st.channel_name;
                optBtn.onclick = () => playAgendaStream(st.stream_id, st.channel_name, sortedStreams, idx + 1, ev.event);
                streamsRow.appendChild(optBtn);
            });
        }
        card.appendChild(streamsRow);
    } else {
        const hint = element('div', 'no-stream-hint', 'No hay canales sintonizables en tu catálogo para este evento.');
        card.appendChild(hint);
    }

    targetContainer.appendChild(card);
}

function playAgendaStream(streamId, channelName, matchStreams = [], queueIndex = 0, matchTitle = '') {
    if (!streamId) return;

    if (matchStreams && matchStreams.length > 0) {
        currentMatchStreamQueue = matchStreams;
        currentMatchQueueIndex = queueIndex;
        currentMatchTitle = matchTitle || channelName || 'Evento deportivo';
    } else {
        currentMatchStreamQueue = [];
        currentMatchQueueIndex = 0;
        currentMatchTitle = '';
    }

    if (matchFailoverTimer) {
        clearTimeout(matchFailoverTimer);
        matchFailoverTimer = null;
    }

    let ch = allChannels.find(c => c.id === streamId || c.stream_id === streamId);
    if (!ch) {
        ch = {
            id: streamId,
            name: channelName || currentMatchTitle || 'Evento deportivo',
            stream_id: streamId,
            type: 'acestream'
        };
    }
    playChannel(ch);
}

function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}
