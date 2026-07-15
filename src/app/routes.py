import os
import time
import json
import shutil
import requests
import psutil
from urllib.parse import parse_qs, urlparse
from flask import Blueprint, jsonify, send_from_directory, Response, request, current_app
from app.config import Config
from app.services.hls_manager import hls_manager
from app.services.channel_manager import channel_manager
from app.services.stats_manager import stats_manager
from app import utils

main_bp = Blueprint('main', __name__)

HLS_CONTENT_TYPE_MARKERS = ('mpegurl', 'application/x-mpegurl')
MAX_UPSTREAM_MANIFEST_BYTES = 1024 * 1024

@main_bp.route('/dashboard')
def dashboard():
    return current_app.send_static_file('dashboard.html')

@main_bp.route('/api/system/stats')
def system_stats():
    # System Metrics
    cpu_percent = psutil.cpu_percent(interval=None)
    ram = psutil.virtual_memory()
    disk = shutil.disk_usage(Config.HLS_DIR)
    
    # Active Streams
    streams = hls_manager.get_active_streams_info()
    
    return jsonify({
        "status": "ok",
        "system": {
            "cpu": cpu_percent,
            "ram": {
                "percent": ram.percent,
                "used_mb": round(ram.used / 1024 / 1024),
                "total_mb": round(ram.total / 1024 / 1024)
            },
            "disk": {
                "percent": round((disk.used / disk.total) * 100, 1),
                "free_gb": [round(disk.free / 1024 / 1024 / 1024, 2)] # List trick? No just float 
            }
        },
        "streams": streams
    })

@main_bp.route('/api/system/logs')
def system_logs():
    log_file = os.path.join(Config.DATA_DIR, 'app.log')
    if not os.path.exists(log_file):
        return "No logs found.", 200
    
    try:
        # Read last 50 lines
        # Simple implementation for now
        with open(log_file, 'r') as f:
            lines = f.readlines()
            last_lines = lines[-50:]
            return "".join(last_lines)
    except Exception as e:
        return f"Error reading logs: {e}", 500

from app.services.settings_manager import settings_manager

@main_bp.route('/api/settings', methods=['GET'])
def get_settings():
    return jsonify(settings_manager.get_all())

@main_bp.route('/api/settings', methods=['POST'])
def update_settings():
    new_settings = request.json
    if not new_settings:
        return jsonify({"status": "error", "message": "No data provided"}), 400
    
    if settings_manager.save(new_settings):
        # Update Config from persistence? 
        # Actually Config class is static, but dynamic uses read directly from settings_manager.
        return jsonify({"status": "ok", "settings": settings_manager.get_all()})
    else:
        return jsonify({"status": "error", "message": "Failed to save settings"}), 500

@main_bp.route('/')
def index():
    return current_app.send_static_file('index.html')

@main_bp.route('/health')
def health_check():
    health = {
        "status": "ok",
        "timestamp": time.time(),
        "components": {}
    }
    
    # 1. Disk Space
    try:
        total, used, free = shutil.disk_usage(Config.HLS_DIR)
        health["components"]["disk"] = {
            "status": "ok" if free > 1024 * 1024 * 100 else "warning", # 100MB warning
            "free_mb": free // (1024 * 1024),
            "total_mb": total // (1024 * 1024)
        }
    except Exception as e:
         health["components"]["disk"] = {"status": "error", "error": str(e)}

    # 2. AceXY Connection (Internal)
    try:
        acexy_host = Config.ACEXY_IP
        if acexy_host in ['127.0.0.1', 'localhost', '0.0.0.0']:
            acexy_host = 'acexy' # Use docker service name if local
            
        acexy_url = f"http://{acexy_host}:{Config.ACEXY_PORT}/"
        # We accept any response, even 404, as proof of life
        resp = requests.get(acexy_url, timeout=2)
        health["components"]["acexy"] = {"status": "ok", "code": resp.status_code}
    except Exception as e:
        health["components"]["acexy"] = {"status": "error", "error": str(e)}
        # We don't mark global status as error because maybe acexy is just starting up? 
        # But failing to connect is bad.
        health["status"] = "degraded"

    # 3. FFMPEG Processes
    health["components"]["ffmpeg"] = {
        "active_streams": len(hls_manager.processes)
    }

    from app.services.refresh_scheduler import playlist_refresh_scheduler
    health["components"]["playlist_refresh"] = playlist_refresh_scheduler.status()

    status_code = 200 if health["status"] == "ok" else 500
    return jsonify(health), status_code

@main_bp.route('/manifest.json')
def manifest():
    return current_app.send_static_file('manifest.json')

@main_bp.route('/sw.js')
def service_worker():
    response = current_app.send_static_file('sw.js')
    response.headers['Content-Type'] = 'application/javascript'
    return response

@main_bp.after_request
def add_header(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

from app.utils import get_acexy_url_for_client

@main_bp.route('/api/channels')
def get_channels():
    # If cache is very old or missing, force update? 
    # With APScheduler, this should presumably be up to date.
    # But if it's the very first run, we might want to check.
    # Check if cache exists and is valid
    should_update = True
    if os.path.exists(Config.JSON_FILE):
        mtime = os.path.getmtime(Config.JSON_FILE)
        if (time.time() - mtime) < Config.CACHE_DURATION:
            should_update = False

    if should_update:
         channel_manager.update_channels()

    if os.path.exists(Config.JSON_FILE):
        with open(Config.JSON_FILE, 'r') as f:
            data = json.load(f)
            
        request_host = request.host
        
        # Load stats once
        stats = stats_manager.get_stats()
        
        for ch in data:
            # Inject stats if avail
            if ch["id"] in stats:
                ch["stats"] = stats[ch["id"]]

            if "url" in ch and Config.ACEXY_IP in ch["url"]:
                 # Just refresh the IP part if it's already a full URL matching our config
                 target_url = get_acexy_url_for_client(request_host)
                 ch["url"] = ch["url"].replace(f"http://{Config.ACEXY_IP}:{Config.ACEXY_PORT}/ace/getstream", target_url)
            elif "url" in ch:
                 # Re-generate it safely
                ch["url"] = get_acexy_url_for_client(request_host, ch['id'])

        return jsonify(data)
    return jsonify([]), 500

from app.services.source_manager import source_manager

@main_bp.route('/api/sources', methods=['GET'])
def get_sources():
    return jsonify(source_manager.get_sources())

@main_bp.route('/api/sources', methods=['POST'])
def add_source():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({"error": "Missing URL"}), 400
    
    if source_manager.add_source(url):
        # Auto-refresh channels on change
        try:
            channel_manager.update_channels()
            return jsonify({"status": "added", "url": url, "message": "Source added and channels updated"})
        except Exception as e:
            return jsonify({"status": "added_but_failed_refresh", "url": url, "error": str(e)}), 200
            
    return jsonify({"error": "Duplicate source"}), 409

@main_bp.route('/api/sources', methods=['DELETE'])
def delete_source():
    data = request.get_json()
    url = data.get('url')
    if not url:
        return jsonify({"error": "Missing URL"}), 400
    
    if source_manager.delete_source(url):
        # Auto-refresh channels on change
        try:
            channel_manager.update_channels()
            return jsonify({"status": "deleted", "url": url, "message": "Source deleted and channels updated"})
        except Exception as e:
            return jsonify({"status": "deleted_but_failed_refresh", "url": url, "error": str(e)}), 200

    return jsonify({"error": "Source not found"}), 404

@main_bp.route('/api/sources/refresh', methods=['POST'])
def refresh_sources():
    try:
        channel_manager.update_channels()
        return jsonify({"status": "ok", "message": "Channels refreshed"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@main_bp.route('/api/sources/refresh/status')
def refresh_sources_status():
    from app.services.refresh_scheduler import playlist_refresh_scheduler

    return jsonify(playlist_refresh_scheduler.status())

@main_bp.route('/api/stats/feedback', methods=['POST'])
def submit_feedback():
    data = request.get_json()
    ace_id = data.get('id')
    vote = data.get('vote') # 'like' or 'dislike'
    
    if not ace_id or vote not in ['like', 'dislike']:
        return jsonify({"error": "Invalid data"}), 400
        
    stats_manager.update_user_feedback(ace_id, vote)
    return jsonify({"status": "ok", "vote": vote})

@main_bp.route('/api/orchestrator/status')
def orchestrator_status():
    from app.services.orchestrator import OrchestratorService
    service = OrchestratorService()
    data = service.get_status()
    return jsonify(data)


@main_bp.route('/api/orchestrator/streams')
def orchestrator_streams():
    from app.services.orchestrator import OrchestratorService
    service = OrchestratorService()
    data = service.get_streams()
    return jsonify(data)

@main_bp.route('/api/orchestrator/overview')
def orchestrator_overview():
    from app.services.orchestrator import OrchestratorService

    service = OrchestratorService()
    return jsonify(service.get_overview())

@main_bp.route('/api/orchestrator/metrics')
def orchestrator_metrics():
    from app.services.orchestrator import OrchestratorService

    service = OrchestratorService()
    window_seconds = request.args.get('window_seconds', 900, type=int)
    return jsonify(service.get_dashboard_metrics(window_seconds))

@main_bp.route('/api/orchestrator/config')
def orchestrator_config():
    from app.services.orchestrator import OrchestratorService

    service = OrchestratorService()
    return jsonify(service.connection_info())

def _normalize_hls_profile(profile):
    if Config.ENABLE_TRANSCODE and profile not in ['original', '720p', '480p', 'max_compat']:
        return 'original'
    if not Config.ENABLE_TRANSCODE:
        return 'original'
    return profile

def _manifest_has_segment(manifest_path):
    if not os.path.exists(manifest_path):
        return False

    stream_dir = os.path.dirname(manifest_path)
    try:
        with open(manifest_path, 'r') as f:
            lines = [line.strip() for line in f.readlines()]
    except OSError:
        return False

    for line in lines:
        if not line or line.startswith('#'):
            continue
        if line.startswith(('http://', 'https://')):
            return True
        segment_path = os.path.join(stream_dir, line.split('?')[0])
        if os.path.exists(segment_path) and os.path.getsize(segment_path) > 0:
            return True
    return False

def _wait_for_ready_manifest(effective_id, timeout=45):
    manifest = os.path.join(Config.HLS_DIR, effective_id, 'index.m3u8')
    deadline = time.time() + timeout

    while time.time() < deadline:
        # Preparing a slow stream is still activity. Without this refresh the
        # inactivity monitor can stop FFmpeg before this request completes.
        hls_manager.update_activity(effective_id)

        if _manifest_has_segment(manifest):
            return True

        proc = hls_manager.processes.get(effective_id)
        if proc and proc.poll() is not None:
            return False

        time.sleep(0.5)

    return False

def _is_hls_response(content_type, payload):
    content_type = (content_type or '').lower()
    return any(marker in content_type for marker in HLS_CONTENT_TYPE_MARKERS) or b'#EXTM3U' in payload

def _hls_manifest_has_media(payload):
    text = payload.decode('utf-8', 'replace')
    return any(
        line.strip() and not line.strip().startswith('#')
        for line in text.splitlines()
    )

def _probe_upstream_media(ace_id):
    """Return ``hls``, ``stream`` or ``None`` for the AceXY response."""
    resp = None
    try:
        resp = requests.get(
            _internal_acexy_stream_url(ace_id),
            timeout=(3, 5),
            stream=True
        )
        resp.raise_for_status()
        chunk = next(resp.iter_content(4096), b'')
    except requests.RequestException:
        return None
    finally:
        if resp is not None:
            resp.close()

    if not chunk:
        return None

    if _is_hls_response(resp.headers.get('content-type'), chunk):
        return 'hls' if _hls_manifest_has_media(chunk) else None

    return 'stream'

def _upstream_has_media(ace_id):
    return _probe_upstream_media(ace_id) is not None

def _wait_for_upstream_media(ace_id, timeout=30):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _upstream_has_media(ace_id):
            return True
        time.sleep(2)
    return False

def _internal_acexy_stream_url(ace_id):
    internal_host = utils.get_acexy_host_for_server()
    return f"http://{internal_host}:{Config.ACEXY_PORT}/ace/getstream?id={ace_id}"

def _internal_acexy_segment_url(ace_id, seq):
    internal_host = utils.get_acexy_host_for_server()
    return f"http://{internal_host}:{Config.ACEXY_PORT}/ace/hls/segment.ts?stream={ace_id}&seq={seq}"

def _rewrite_upstream_manifest(ace_id, manifest_text):
    rewritten = []
    for line in manifest_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            rewritten.append(line)
            continue

        seq = None
        if stripped.startswith(('http://', 'https://')):
            query = parse_qs(urlparse(stripped).query)
            seq_values = query.get('seq')
            if seq_values:
                seq = seq_values[0]
        elif 'seq=' in stripped:
            query = parse_qs(urlparse(stripped).query)
            seq_values = query.get('seq')
            if seq_values:
                seq = seq_values[0]

        if seq is not None:
            rewritten.append(f"/proxy/hls/{ace_id}/segment.ts?seq={seq}")
        else:
            rewritten.append(line)

    return "\n".join(rewritten) + "\n"

def _start_hls_with_retries(
    ace_id,
    profile,
    force=False,
    attempts=3,
    wait_timeout=45,
    upstream_ready=False
):
    last_effective_id = None

    for attempt in range(1, attempts + 1):
        media_ready = upstream_ready if attempt == 1 else False
        if not media_ready and not _wait_for_upstream_media(ace_id, timeout=30):
            if attempt < attempts:
                time.sleep(min(attempt, 3))
                continue
            break

        restart = force or attempt > 1
        success, effective_id = hls_manager.start_stream(ace_id, profile, force=restart)
        last_effective_id = effective_id

        if success and _wait_for_ready_manifest(effective_id, wait_timeout):
            return {
                "status": "ok",
                "url": f"/hls/{effective_id}/index.m3u8",
                "attempts": attempt,
                "retryable": False,
                "effective_id": effective_id
            }

        hls_manager.stop_stream(effective_id)
        if attempt < attempts:
            time.sleep(min(attempt, 3))

    return {
        "status": "timeout",
        "message": "El motor AceStream no entregó segmentos reproducibles a tiempo.",
        "attempts": attempts,
        "retryable": True,
        "effective_id": last_effective_id
    }

@main_bp.route('/api/hls/start/<ace_id>')
def start_hls(ace_id):
    profile = _normalize_hls_profile(request.args.get('profile', 'original'))
    force = request.args.get('force') == '1'
    upstream_kind = _probe_upstream_media(ace_id)

    if profile == 'original' and upstream_kind == 'hls':
        return jsonify({
            "status": "ok",
            "url": f"/proxy/hls/{ace_id}/index.m3u8",
            "attempts": 1,
            "retryable": False,
            "effective_id": ace_id,
            "direct": True
        })

    result = _start_hls_with_retries(
        ace_id,
        profile,
        force=force,
        upstream_ready=upstream_kind is not None
    )
    if result["status"] == "ok":
        return jsonify(result)
    return jsonify(result), 504

@main_bp.route('/proxy/hls/<ace_id>/index.m3u8')
def proxy_upstream_manifest(ace_id):
    resp = None
    try:
        resp = requests.get(
            _internal_acexy_stream_url(ace_id),
            timeout=(3, 10),
            stream=True
        )
        resp.raise_for_status()
        chunks = []
        total_size = 0

        for chunk in resp.iter_content(4096):
            if not chunk:
                continue

            if not chunks and not _is_hls_response(resp.headers.get('content-type'), chunk):
                return "AceXY returned a continuous stream instead of an HLS manifest", 502

            total_size += len(chunk)
            if total_size > MAX_UPSTREAM_MANIFEST_BYTES:
                return "Upstream HLS manifest is too large", 502
            chunks.append(chunk)

        manifest_data = b''.join(chunks)
        if not manifest_data or not _is_hls_response(resp.headers.get('content-type'), manifest_data):
            return "Invalid upstream HLS manifest", 502
    except requests.RequestException as e:
        return str(e), 502
    finally:
        if resp is not None:
            resp.close()

    response = Response(
        _rewrite_upstream_manifest(ace_id, manifest_data.decode('utf-8', 'replace')),
        mimetype='application/vnd.apple.mpegurl'
    )
    response.headers["Cache-Control"] = "no-cache"
    return response

@main_bp.route('/proxy/hls/<ace_id>/segment.ts')
def proxy_upstream_segment(ace_id):
    seq = request.args.get('seq')
    if not seq:
        return "Missing seq", 400

    try:
        upstream = requests.get(_internal_acexy_segment_url(ace_id, seq), timeout=15, stream=True)
        upstream.raise_for_status()
    except requests.RequestException as e:
        return str(e), 502

    def generate():
        try:
            for chunk in upstream.iter_content(chunk_size=1024 * 256):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    response = Response(generate(), mimetype='video/mp2t')
    response.headers["Cache-Control"] = "max-age=30"
    return response


@main_bp.route('/hls/<path:filename>')
def serve_hls(filename):
    # filename might be "ace_id/index.m3u8" or "ace_id/segment.ts"
    # or "ace_id_720p/index.m3u8"
    
    parts = filename.split('/')
    if len(parts) > 0:
        stream_id = parts[0]
        hls_manager.update_activity(stream_id)
        
    response = send_from_directory(Config.HLS_DIR, filename)
    
    # Explicitly set correct MIME types to avoid browser confusion
    if filename.endswith('.m3u8'):
        response.mimetype = 'application/vnd.apple.mpegurl'
    elif filename.endswith('.ts'):
        response.mimetype = 'video/mp2t'
    elif filename.endswith('.m4s'):
        response.mimetype = 'video/iso.segment'
    elif filename.endswith('.mp4'):
        response.mimetype = 'video/mp4'
        
    return response

@main_bp.route('/api/version')
def version():
    try:
        with open('app/version.txt', 'r') as f:
            v = f.read().strip()
    except:
        v = "unknown"
    return jsonify({
        "version": v, 
        "transcoding": Config.ENABLE_TRANSCODE
    })


@main_bp.route('/api/playlist.m3u')
@main_bp.route('/playlist.m3u')
def get_playlist():
    profile = request.args.get('profile', None) # None = Original
    
    # Only reset 720p/480p if transcoding is disabled. 
    # 'direct' (AceStream links) and 'original' (Copy) are always allowed.
    if not Config.ENABLE_TRANSCODE and profile in ['720p', '480p', 'max_compat']:
        profile = None

    # Force update if empty
    if not os.path.exists(Config.JSON_FILE):
        channel_manager.update_channels()

    host = request.headers.get('Host')
    m3u_content = ["#EXTM3U"]
    
    try:
        with open(Config.JSON_FILE, 'r') as f:
            channels = json.load(f)
            
        for ch in channels:
            # Append ID suffix for uniqueness and UI matching
            display_name = f"{ch['name']} [{ch['id'][-4:]}]"
            m3u_content.append(f'#EXTINF:-1 tvg-id="{ch["id"]}" tvg-logo="{ch.get("logo", "")}" group-title="{ch.get("group", "")}",{display_name}')
            
            # Helper to generate link
            def gen_link(p):
                if p == 'direct':
                    # Direct AceStream Link (HTTP to AceXY)
                    # Use utils to determine correct public IP/Port based on request host
                    return utils.get_acexy_url_for_client(host, ch['id'])
                    
                # HLS variants
                suffix = f"?profile={p}" if p and p != 'original' else ""
                return f"http://{host}/stream/{ch['id']}.m3u8{suffix}"

            m3u_content.append(gen_link(profile))

    except Exception as e:
        return str(e), 500

    response = Response("\n".join(m3u_content), mimetype='audio/x-mpegurl')
    response.headers["Content-Disposition"] = "attachment; filename=playlist.m3u"
    return response

@main_bp.route('/api/playlist/all.m3u')
def get_playlist_all():
    # Returns playlist with ALL variants (Original, 720p, 480p, Compat)
    if not Config.ENABLE_TRANSCODE: 
        return get_playlist()

    if not os.path.exists(Config.JSON_FILE):
        channel_manager.update_channels()

    host = request.headers.get('Host')
    m3u_content = ["#EXTM3U"]
    
    try:
        with open(Config.JSON_FILE, 'r') as f:
            channels = json.load(f)
            
        for ch in channels:
            logo = ch.get("logo", "")
            group = ch.get("group", "")
            name = ch["name"]
            cid = ch["id"]
            
            # Append ID suffix for uniqueness
            display_name = f"{name} [{cid[-4:]}]"
            
            # Original
            m3u_content.append(f'#EXTINF:-1 tvg-id="{cid}" tvg-logo="{logo}" group-title="{group}",{display_name}')
            m3u_content.append(f"http://{host}/stream/{cid}.m3u8")

            # Compat (Recode)
            m3u_content.append(f'#EXTINF:-1 tvg-id="{cid}" tvg-logo="{logo}" group-title="{group}",{display_name} [Compat]')
            m3u_content.append(f"http://{host}/stream/{cid}.m3u8?profile=max_compat")
            
            # 720p
            m3u_content.append(f'#EXTINF:-1 tvg-id="{cid}" tvg-logo="{logo}" group-title="{group}",{display_name} [720p]')
            m3u_content.append(f"http://{host}/stream/{cid}.m3u8?profile=720p")

            # 480p
            m3u_content.append(f'#EXTINF:-1 tvg-id="{cid}" tvg-logo="{logo}" group-title="{group}",{display_name} [480p]')
            m3u_content.append(f"http://{host}/stream/{cid}.m3u8?profile=480p")

    except Exception as e:
        return str(e), 500

    response = Response("\n".join(m3u_content), mimetype='audio/x-mpegurl')
    response.headers["Content-Disposition"] = "attachment; filename=playlist_all.m3u"
    return response


@main_bp.route('/stream/<ace_id>.m3u8')
def auto_start_manifest(ace_id):
    # Wrapper to auto-start stream and redirect to real HLS
    profile = _normalize_hls_profile(request.args.get('profile', 'original'))
    upstream_kind = _probe_upstream_media(ace_id)
    if profile == 'original' and upstream_kind == 'hls':
        return current_app.redirect(f"/proxy/hls/{ace_id}/index.m3u8")

    result = _start_hls_with_retries(
        ace_id,
        profile,
        attempts=3,
        wait_timeout=30,
        upstream_ready=upstream_kind is not None
    )
    if result["status"] == "ok":
        return current_app.redirect(result["url"])
    return result.get("message", "Stream timeout"), 504

@main_bp.route('/api/hls/stop/<ace_id>')
def stop_hls(ace_id):
    hls_manager.stop_stream(ace_id)
    return jsonify({"status": "stopped"})
