let allChannels = [];
let categories = new Set();
let currentStreamUrl = "";
let currentAceId = null;
const player = document.querySelector('media-player');

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
        // Version
        fetch('/api/version').then(r => r.json()).then(d => document.getElementById('version-display').textContent = d.version).catch(e => { });

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

function filterChannels() {
    const search = document.getElementById('searchInput').value.toLowerCase();
    const cat = document.getElementById('categorySelect').value;

    const filtered = allChannels.filter(ch => {
        const matchesSearch = ch.name.toLowerCase().includes(search);
        if (!matchesSearch) return false;

        if (cat === 'all') return true;
        if (cat === 'favorites') return favorites.has(ch.id);
        return ch.group === cat;
    });

    // Sort: Favorites first, then alphabetical
    filtered.sort((a, b) => {
        const favA = favorites.has(a.id);
        const favB = favorites.has(b.id);
        if (favA && !favB) return -1;
        if (!favA && favB) return 1;
        return a.name.localeCompare(b.name);
    });

    const grid = document.getElementById('channel-grid');
    grid.innerHTML = '';
    if (filtered.length === 0) {
        grid.innerHTML = '<div style="grid-column:1/-1;text-align:center;">No hay resultados</div>';
        return;
    }

    filtered.forEach(ch => {
        const card = document.createElement('div');
        card.className = 'channel-card';
        card.onclick = () => playChannel(ch);

        const isFav = favorites.has(ch.id);
        const starBtn = `<button class="star-btn ${isFav ? 'active' : ''}" onclick="toggleFavorite(event, '${ch.id}')">${isFav ? '★' : '☆'}</button>`;

        const logo = ch.logo ? `<img src="${ch.logo}" class="channel-logo" loading="lazy" decoding="async" onerror="this.onerror=null; this.src='data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHZpZXdCb3g9IjAgMCAyNCAyNCI+PHBhdGggZmlsbD0iIzU1NSIgZD0iTTIxIDNIM2MtMS4xIDAtMiAuOS0yIDJ2MTJjMCAxLjEuOSAyIDIgMmg1bDIgM2g0bDItM2g1YzEuMSAwIDItLjkgMi0yVjVjMC0xLjEtLjktMi0yLTJ6bTAgMTRIM1Y1aDE4djEyem0tNS02bC03IDRWM2zNyA0eiIvPjwvc3ZnPg=='">` : '<div style="font-size:2rem;">📺</div>';

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
                if (t.fps && t.fps > 30) res += `${t.fps}`;

                let codec = t.acodec ? t.acodec.toUpperCase() : '';
                if (codec === 'AC3' || codec === 'EAC3') codec = '🔊 ' + codec;
                else codec = '';

                if (res || codec) {
                    techBadge = `<div class="tech-badge">${res} ${codec}</div>`;
                }
            }


        }

        card.innerHTML = `
            ${starBtn}
            ${statusDot}
            ${logo}
            <div class="channel-name">${ch.name}</div>
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

async function playChannel(channel) {
    const modal = document.getElementById('player-modal');
    const errorDiv = document.getElementById('player-error');
    errorDiv.style.display = 'none'; // Reset error

    document.getElementById('player-title').textContent = channel.name;

    // Reset Tech Info
    document.getElementById('player-tech-info').innerHTML = '';

    // Setup VLC Link
    const vlcLink = document.getElementById('vlc-link');
    if (vlcLink) {
        // If channel.url is missing (manual entries), try to guess or use ID
        let vlcUrl = channel.url;
        vlcLink.setAttribute('data-url', vlcUrl); // Store for copy
        vlcLink.href = vlcUrl || '#';
        vlcLink.textContent = "🔗 Copiar Enlace VLC (Directo)";
    }

    // Setup iOS Button
    const iosBtn = document.getElementById('ios-btn');
    if (isIOS() || true) {
        iosBtn.style.display = 'inline-block';
    }

    // Capture ID for feedback
    currentAceId = channel.id;

    // Reset Feedback Buttons
    const likeBtn = document.getElementById('btn-like');
    const dislikeBtn = document.getElementById('btn-dislike');
    if (likeBtn) likeBtn.classList.remove('active-like');
    if (dislikeBtn) dislikeBtn.classList.remove('active-dislike');

    // Populate Tech Info in Player
    const techDiv = document.getElementById('player-tech-info');
    techDiv.innerHTML = '';
    if (channel.stats && channel.stats.tech_info) {
        const t = channel.stats.tech_info;
        let res = '';
        if (t.height) res = t.height >= 720 ? `${t.height}p` : 'SD';
        if (t.fps && t.fps > 30) res += `${t.fps}`;

        let codec = t.acodec ? t.acodec.toUpperCase() : '';
        if (codec === 'AC3' || codec === 'EAC3') codec = '🔊 ' + codec;
        else codec = '';

        if (res || codec) {
            techDiv.innerHTML = `<span class="tech-badge" style="font-size:0.9rem; padding:4px 8px;">${res} ${codec}</span>`;
        }
    }

    modal.style.display = 'flex';

    // Start Polling for Stats (Tech Info)
    if (statsInterval) clearInterval(statsInterval);
    statsInterval = setInterval(() => pollStats(channel.id), 5000);

    try {
        // Request stream start
        const res = await fetch(`/api/hls/start/${channel.id}`);
        const data = await res.json();

        if (data.status === 'ok') {
            console.log("Loading stream:", data.url);
            currentStreamUrl = data.url; // Save for native player
            player.src = { src: data.url, type: 'application/x-mpegurl' };
            player.muted = true;
            player.playsInline = true;
            player.autoplay = true;

            const playPromise = player.play();
            if (playPromise !== undefined) {
                playPromise.catch(error => {
                    console.log("Autoplay prevented:", error);
                    // Show a "Play" overlay or similar if we were fancy, 
                    // but for now the user can just click the controls.
                });
            }

            // Start Timeout Timer (20 seconds)
            if (loadTimeout) clearTimeout(loadTimeout);
            loadTimeout = setTimeout(() => {
                // Check if playing (currentTime is still near zero)
                if (player.currentTime < 1) {
                    console.warn("Stream timeout - No sources.");
                    errorDiv.style.display = 'flex';
                    player.pause();
                }
            }, 20000);

            // Clear timeout if it starts playing
            player.addEventListener('playing', () => {
                if (loadTimeout) clearTimeout(loadTimeout);
                errorDiv.style.display = 'none';
            }, { once: true });

        } else {
            alert("Error servidor: " + data.status);
            closePlayer();
        }
    } catch (e) {
        console.error(e);
        alert("Error de conexión con el backend");
        closePlayer();
    }
}

function playNativeIOS() {
    if (!currentStreamUrl) return alert("Espera a que cargue el stream...");
    // Force full URL location
    const fullUrl = window.location.origin + currentStreamUrl;
    window.location.href = fullUrl;
}

function closePlayer() {
    player.pause();
    player.src = ''; // Unload
    currentStreamUrl = "";
    document.getElementById('player-modal').style.display = 'none';
    if (loadTimeout) clearTimeout(loadTimeout);
    if (statsInterval) clearInterval(statsInterval);
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

    // Robust Copy
    const copyText = (text) => {
        if (navigator.clipboard && navigator.clipboard.writeText) {
            return navigator.clipboard.writeText(text);
        } else {
            const textArea = document.createElement("textarea");
            textArea.value = text;
            textArea.style.position = "fixed"; // Avoid scrolling
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

// Register Service Worker for PWA
if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
        navigator.serviceWorker.register('/sw.js').then(registration => {
            console.log('SW Registered:', registration);
        }).catch(error => {
            console.log('SW Registration failed:', error);
        });
    });
}

// Settings Logic
function openSettings() {
    document.getElementById('settings-modal').style.display = 'flex';
    loadSources();
}

function closeSettings() {
    document.getElementById('settings-modal').style.display = 'none';
}

// Close settings on click outside
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
    console.log("Feedback clicked:", vote, "for ID:", currentAceId);
    if (!currentAceId) {
        console.error("No active AceID for feedback");
        return;
    }

    // UI Feedback immediately
    const likeBtn = document.getElementById('btn-like');
    const dislikeBtn = document.getElementById('btn-dislike');

    likeBtn.classList.remove('active-like');
    dislikeBtn.classList.remove('active-dislike');

    if (vote === 'like') likeBtn.classList.add('active-like');
    if (vote === 'dislike') dislikeBtn.classList.add('active-dislike');

    try {
        await fetch('/api/stats/feedback', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ id: currentAceId, vote: vote })
        });

        // Optimistic UI Update
        const ch = allChannels.find(c => c.id === currentAceId);
        if (ch) {
            if (!ch.stats) ch.stats = { success_count: 0, last_ok: Math.floor(Date.now() / 1000) };
            if (!ch.stats.diff_votes) ch.stats.diff_votes = 0;

            if (vote === 'like') ch.stats.diff_votes++;
            else ch.stats.diff_votes--;

            filterChannels(); // Re-render grid immediately
        }

    } catch (e) {
        console.error("Feedback error", e);
    }
}

function updatePlayerTechBadge(t) {
    const techDiv = document.getElementById('player-tech-info');
    let res = '';
    if (t.height) res = t.height >= 720 ? `${t.height}p` : 'SD';
    if (t.fps && t.fps > 30) res += `${t.fps}`;

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

document.addEventListener('DOMContentLoaded', loadChannels);
