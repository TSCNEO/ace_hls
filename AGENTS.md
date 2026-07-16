schema_version: 3
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
        responsibilities: [refresh_sources, merge_custom_first, deduplicate_by_identifier, source_id_cache_fallback, atomic_outputs]
      source_validator:
        file: src/app/services/source_validator.py
        responsibilities: [bounded_download, m3u_and_acestream_api_parse, identifier_normalization]
      refresh_scheduler:
        file: src/app/services/refresh_scheduler.py
        interval_env: PLAYLIST_REFRESH_INTERVAL
        default_interval_s: 900
        startup: immediate_due_check
      source_manager:
        file: src/app/services/source_manager.py
        persistence: sources.json_schema_v2
        migration: legacy_array_to_v2_with_single_backup
      custom_channel_manager:
        file: src/app/services/custom_channel_manager.py
        persistence: custom_channels.json_schema_v1
      settings_manager:
        file: src/app/services/settings_manager.py
        persistence: settings.json
      stats_manager:
        file: src/app/services/stats_manager.py
        persistence: stats.json
      hls_manager:
        file: src/app/services/hls_manager.py
        responsibilities: [ffmpeg_process_lifecycle, unique_upstream_client_identity, healthy_session_reuse, hls_generation, idle_cleanup, local_output_ffprobe_metadata]
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
documentation:
  overview: README.md
  configuration: docs/configuration.md
  api: docs/api.md
  sources_v2: docs/sources-v2.md
  releases: CHANGELOG.md
external_services:
  orchestrator_proxy:
    config: [STREAM_BACKEND, STREAM_PROXY_HOST, STREAM_PROXY_PORT, STREAM_PUBLIC_PORT, STREAM_PUBLIC_ENDPOINT]
    compose_image: ghcr.io/krinkuto11/acestream-orchestrator:v2.1.0.3
    stream_endpoint: /ace/getstream?id={id_or_content_id}|infohash={infohash}
    payloads: [video/mp2t_continuous, hls_manifest]
    panel: /panel
    persistent_volume: orchestrator_data:/app/app/config
    docker_access: /var/run/docker.sock
  acexy_legacy:
    compose_files: [docker-compose.acexy.yml, release/docker-compose.acexy.yml]
    image: ghcr.io/javinator9889/acexy:0.2.2
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
    source_cache/: last_valid_normalized_channels_per_source
    ace_hls.m3u: generated_direct_playlist
    sources.json: source_registry
    sources.v1.backup.json: one_time_legacy_backup
    custom_channels.json: custom_channel_registry
    settings.json: web_settings
    stats.json: channel_health_and_media_metadata
    app.log: application_log
    hls/: ephemeral_manifests_segments_ffmpeg_logs
http_api:
  channels: /api/channels
  settings: /api/settings
  system: [/health, /api/version, /api/system/stats, /api/system/logs]
  playlists: [/playlist.m3u, /api/playlist/all.m3u]
  sources: [/api/sources, /api/sources/{source_id}, /api/sources/{source_id}/validate, /api/sources/refresh, /api/sources/refresh/status]
  custom_channels: [/api/custom-channels, /api/custom-channels/{channel_id}]
  hls_start: /api/hls/start/{ace_id}
  hls_stop: /api/hls/stop/{ace_id}
  hls_files: /hls/{stream_id}/{filename}
  orchestrator: [/api/orchestrator/status, /api/orchestrator/streams, /api/orchestrator/overview, /api/orchestrator/metrics, /api/orchestrator/config]
  health: /health
flows:
  playlist_refresh:
    sequence: [scheduler_due_check, cross_process_lock, fetch_enabled_sources, validate_shared_parser, update_or_reuse_source_id_snapshot, prepend_custom_channels, deduplicate, atomic_replace]
    failure_policy: reuse_last_valid_snapshot_for_each_failed_source
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
  - never overwrite an unknown future persistence schema
  - disabled sources never fetch or contribute channels
  - render remote metadata with DOM text properties, never HTML interpolation
  - orchestrator read failures return structured JSON and never raise Flask 500
  - orchestrator secrets never appear in API responses or logs
  - management bearer tokens never appear in playback URLs
  - STREAM_* takes precedence over ACEXY_* aliases
validation:
  unit: PYTHONPATH=src .venv/bin/python -m pytest -q
  syntax_python: .venv/bin/python -m compileall -q src tests
  syntax_javascript: node --check src/app/static/script.js
  documentation: PYTHONPATH=src .venv/bin/python -m pytest -q tests/test_documentation.py
  docker: docker build -t ace-hls-viewer:test .
release:
  script: push_docker.sh
  versioned_image: tscneo/ace-hls-viewer:{version_without_v}
  platforms: [linux/amd64, linux/arm64]
  latest_allowed_for_release: true
  compose_image_env: ACE_HLS_IMAGE
  development_branch: codex/v2.6.0-orchestrator
  development_tag: tscneo/ace-hls-viewer:2.6.0-dev
