let allChannels = [];
let categories = new Set();
let currentStreamUrl = "";
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

        card.innerHTML = `${starBtn}${logo}<div class="channel-name">${ch.name}</div>`;
        grid.appendChild(card);
    });
}

function isIOS() {
    return [
        'iPad Simulator', 'iPhone Simulator', 'iPod Simulator', 'iPad', 'iPhone', 'iPod'
    ].includes(navigator.platform) || (navigator.userAgent.includes("Mac") && "ontouchend" in document);
}

let loadTimeout;

async function playChannel(channel) {
    const modal = document.getElementById('player-modal');
    const errorDiv = document.getElementById('player-error');
    errorDiv.style.display = 'none'; // Reset error

    document.getElementById('player-title').textContent = channel.name;

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

    modal.style.display = 'flex';

    try {
        // Request stream start
        const res = await fetch(`/api/hls/start/${channel.id}`);
        const data = await res.json();

        if (data.status === 'ok') {
            console.log("Loading stream:", data.url);
            currentStreamUrl = data.url; // Save for native player
            player.src = { src: data.url, type: 'application/x-mpegurl' };
            player.muted = true;
            player.autoplay = true;
            player.play();

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

document.addEventListener('DOMContentLoaded', loadChannels);
