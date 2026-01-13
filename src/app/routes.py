import os
import time
import json
import shutil
import requests
from flask import Blueprint, jsonify, send_from_directory, Response, request, current_app
from app.config import Config
from app.services.hls_manager import hls_manager
from app.services.channel_manager import channel_manager

main_bp = Blueprint('main', __name__)

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
        
        for ch in data:
            if "url" in ch and Config.ACEXY_IP in ch["url"]:
                 # Just refresh the IP part if it's already a full URL matching our config
                 target_url = get_acexy_url_for_client(request_host)
                 ch["url"] = ch["url"].replace(f"http://{Config.ACEXY_IP}:{Config.ACEXY_PORT}/ace/getstream", target_url)
            elif "url" in ch:
                 # Re-generate it safely
                ch["url"] = get_acexy_url_for_client(request_host, ch['id'])

        return jsonify(data)
    return jsonify([]), 500

@main_bp.route('/api/version')
def get_version():
    try:
        version_path = os.path.join(current_app.root_path, 'version.txt')
        with open(version_path, 'r') as f:
            return jsonify({"version": f.read().strip()})
    except Exception:
        # Fallback to check if it's in the parent directory (in case of different cwd)
        try:
             with open('version.txt', 'r') as f:
                return jsonify({"version": f.read().strip()})
        except Exception:
             return jsonify({"version": "dev"})

@main_bp.route('/playlist.m3u')
def get_playlist():
    if not os.path.exists(Config.JSON_FILE):
        channel_manager.update_channels()
    
    if os.path.exists(Config.JSON_FILE):
        try:
            with open(Config.JSON_FILE, 'r') as f:
                channels = json.load(f)
            
            m3u_lines = ["#EXTM3U"]
            
            for ch in channels:
                logo_attr = f' tvg-logo="{ch.get("logo", "")}"' if ch.get("logo") else ""
                group_attr = f' group-title="{ch.get("group", "")}"' if ch.get("group") else ""
                
                info_line = f'#EXTINF:-1{logo_attr}{group_attr},{ch["name"]}'
                
                stream_url = get_acexy_url_for_client(request.host, ch["id"])
                
                m3u_lines.append(info_line)
                m3u_lines.append(stream_url)
                
            return Response("\n".join(m3u_lines), mimetype='audio/x-mpegurl')
        except Exception as e:
            current_app.logger.error(f"Error generating dynamic playlist: {e}")
            return "Error generating playlist", 500

    return "No channels available", 404

@main_bp.route('/api/hls/start/<ace_id>')
def start_hls(ace_id):
    success = hls_manager.start_stream(ace_id)
    if success:
        m3u8_path = os.path.join(Config.HLS_DIR, ace_id, "index.m3u8")
        retries = 10
        while retries > 0:
            if os.path.exists(m3u8_path) and os.path.getsize(m3u8_path) > 0:
                return jsonify({"status": "ok", "url": f"/hls/{ace_id}/index.m3u8"})
            time.sleep(1)
            retries -= 1
        return jsonify({"status": "ok", "url": f"/hls/{ace_id}/index.m3u8", "note": "Stream starting, playlist may not be ready yet"})
    return jsonify({"status": "error"}), 500

@main_bp.route('/api/hls/stop/<ace_id>')
def stop_hls(ace_id):
    hls_manager.stop_stream(ace_id)
    return jsonify({"status": "stopped"})

@main_bp.route('/hls/<ace_id>/<filename>')
def serve_hls(ace_id, filename):
    hls_manager.update_activity(ace_id)
    return send_from_directory(os.path.join(Config.HLS_DIR, ace_id), filename)
