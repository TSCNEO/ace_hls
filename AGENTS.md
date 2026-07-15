schema_version: 1
document_type: llm_project_architecture
project:
  name: ace-hls-viewer
  purpose: bridge AceStream HTTP streams to Web/HLS clients and exported IPTV playlists
  runtime:
    language: python-3.11
    web: flask
    server: gunicorn
    media: ffmpeg
    packaging: docker
  version_source: src/app/version.txt
entrypoints:
  container: Dockerfile
  wsgi: src/wsgi.py
  app_factory: src/app/__init__.py:create_app
components:
  backend:
    routes:
      file: src/app/routes.py
      responsibilities: [http_api, static_views, hls_delivery, upstream_hls_proxy]
    config:
      file: src/app/config.py
      source: environment
    services:
      channel_manager:
        file: src/app/services/channel_manager.py
        responsibilities: [download_m3u, parse_acestream_ids, deduplicate, atomic_cache_write, cross_process_single_flight]
      refresh_scheduler:
        file: src/app/services/refresh_scheduler.py
        interval_env: PLAYLIST_REFRESH_INTERVAL
        default_interval_s: 900
        startup: immediate_due_check
      source_manager:
        file: src/app/services/source_manager.py
        persistence: sources.json
      settings_manager:
        file: src/app/services/settings_manager.py
        persistence: settings.json
      stats_manager:
        file: src/app/services/stats_manager.py
        persistence: stats.json
      hls_manager:
        file: src/app/services/hls_manager.py
        responsibilities: [ffmpeg_process_lifecycle, hls_generation, idle_cleanup, ffprobe_metadata]
      orchestrator:
        file: src/app/services/orchestrator.py
        api_default: /api/v1
        upstream_contract: https://github.com/krinkuto11/acestream-orchestrator/blob/main/docs/API.md
  frontend:
    index: src/app/static/index.html
    player_logic: src/app/static/script.js
    dashboard: src/app/static/dashboard.html
    service_worker: src/app/static/sw.js
    hls_library: src/app/static/vendor/hls.min.js
external_services:
  acexy_or_orchestrator_proxy:
    config: [ACEXY_IP, ACEXY_PORT]
    stream_endpoint: /ace/getstream?id={ace_id}
    payloads: [video/mp2t_continuous, hls_manifest]
  orchestrator_management:
    config: [ORCHESTRATOR_URL, ORCHESTRATOR_API_PREFIX, ORCHESTRATOR_API_TOKEN, ORCHESTRATOR_TIMEOUT]
    default_prefix: /api/v1
    endpoints:
      engines: /engines
      streams: /streams?status=started
      overview: /orchestrator/status
      metrics: /metrics/dashboard?window_seconds={seconds}
persistence:
  root: DATA_DIR
  container_default: /app/data
  files:
    channels.json: normalized_channel_cache
    ace_hls.m3u: generated_direct_playlist
    sources.json: source_registry
    settings.json: web_settings
    stats.json: channel_health_and_media_metadata
    app.log: application_log
    hls/: ephemeral_manifests_segments_ffmpeg_logs
http_api:
  channels: /api/channels
  playlists: [/playlist.m3u, /api/playlist/all.m3u]
  sources: [/api/sources, /api/sources/refresh, /api/sources/refresh/status]
  hls_start: /api/hls/start/{ace_id}
  hls_files: /hls/{stream_id}/{filename}
  orchestrator: [/api/orchestrator/status, /api/orchestrator/streams, /api/orchestrator/overview, /api/orchestrator/metrics, /api/orchestrator/config]
  health: /health
flows:
  playlist_refresh:
    sequence: [scheduler_due_check, cross_process_lock, fetch_all_sources, parse_deduplicate, atomic_replace]
    failure_policy: preserve_previous_cache_if_all_sources_fail
  browser_playback:
    sequence: [probe_upstream_type, ffmpeg_for_mpegts_or_proxy_for_real_hls, wait_for_playable_manifest, hls_js_attach]
  exported_playlist:
    sequence: [read_channels_cache, generate_client_urls, external_player_requests_stream]
invariants:
  - increment src/app/version.txt for every release commit
  - keep index.html asset query versions and sw.js cache name equal to app version
  - never treat continuous video/mp2t as an HLS manifest
  - preserve persisted data and unrelated worktree changes
  - use atomic replacement for generated shared files
  - orchestrator read failures return structured JSON and never raise Flask 500
  - orchestrator secrets never appear in API responses or logs
validation:
  unit: PYTHONPATH=src python -m pytest -q
  syntax_python: python -m compileall -q src tests
  syntax_javascript: node --check src/app/static/script.js
  docker: docker build -t ace-hls-viewer:test .
release:
  script: push_docker.sh
  images: [tscneo/ace-hls-viewer:{version}, tscneo/ace-hls-viewer:latest]
