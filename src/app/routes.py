import os
import time
import json
from flask import Blueprint, jsonify, send_from_directory, Response, request, current_app
from app.config import Config
from app.services.hls_manager import hls_manager
from app.services.channel_manager import channel_manager

main_bp = Blueprint('main', __name__)

@main_bp.route('/')
def index():
    return current_app.send_static_file('index.html')

@main_bp.route('/api/channels')
def get_channels():
    # If cache is very old or missing, force update? 
    # With APScheduler, this should presumably be up to date.
    # But if it's the very first run, we might want to check.
    if not os.path.exists(Config.JSON_FILE):
         channel_manager.update_channels()

    if os.path.exists(Config.JSON_FILE):
        with open(Config.JSON_FILE, 'r') as f:
            data = json.load(f)
            
        # Dynamic URL replacement logic
        host_ip = request.host.split(':')[0]
        
        target_ip = Config.ACEXY_IP
        if Config.ACEXY_IP in ['127.0.0.1', 'localhost', '0.0.0.0', 'acexy', 'acestream']:
            target_ip = host_ip

        for ch in data:
            if "url" in ch and Config.ACEXY_IP in ch["url"]:
                 ch["url"] = ch["url"].replace(Config.ACEXY_IP, target_ip)
            elif "url" in ch:
                ch["url"] = f"http://{target_ip}:{Config.ACEXY_PORT}/ace/getstream?id={ch['id']}"

        return jsonify(data)
    return jsonify([]), 500

@main_bp.route('/api/version')
def get_version():
    try:
        version_path = os.path.join(current_app.root_path, 'version.txt')
        with open(version_path, 'r') as f:
            return jsonify({"version": f.read().strip()})
    except:
        # Fallback to check if it's in the parent directory (in case of different cwd)
        try:
             with open('version.txt', 'r') as f:
                return jsonify({"version": f.read().strip()})
        except:
             return jsonify({"version": "dev"})

@main_bp.route('/playlist.m3u')
def get_playlist():
    if not os.path.exists(Config.JSON_FILE):
        channel_manager.update_channels()
    
    if os.path.exists(Config.JSON_FILE):
        try:
            with open(Config.JSON_FILE, 'r') as f:
                channels = json.load(f)
            
            host_ip = request.host.split(':')[0]
            
            target_ip = Config.ACEXY_IP
            if Config.ACEXY_IP in ['127.0.0.1', 'localhost', '0.0.0.0', 'acexy', 'acestream']:
                target_ip = host_ip
                
            m3u_lines = ["#EXTM3U"]
            
            for ch in channels:
                logo_attr = f' tvg-logo="{ch.get("logo", "")}"' if ch.get("logo") else ""
                group_attr = f' group-title="{ch.get("group", "")}"' if ch.get("group") else ""
                
                info_line = f'#EXTINF:-1{logo_attr}{group_attr},{ch["name"]}'
                
                ace_id = ch["id"]
                stream_url = f"http://{target_ip}:{Config.ACEXY_PORT}/ace/getstream?id={ace_id}"
                
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
