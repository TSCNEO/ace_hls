"""Sports Agenda (EPG) Service for AceHLS.

Scrapes sports events from futbolenlatv.es/deporte, parses multi-day schedules,
normalizes channel identities and matches them against active AceStream channels.
"""

from __future__ import annotations

import datetime
import html
import json
import logging
import os
import re
import threading
import time
import urllib.error
import urllib.request
from typing import Any

from app.config import Config
from app.services.storage import atomic_write_json

logger = logging.getLogger(__name__)

# Default channel equivalence dictionary (TV Guide Title -> Canonical Target Names)
DEFAULT_EQUIVALENCIAS: dict[str, list[str]] = {
    "La 1 TVE": ["La 1 TVE", "La 1 TVE 4K"],
    "La 2 TVE": ["La 2 TVE"],
    "Teledeporte": ["Teledeporte"],
    "Eurosport 1": ["Eurosport 1"],
    "Eurosport 2": ["Eurosport 2"],
    "M+ LALIGA (M54 O110)": ["M+ LaLiga", "SKY Sports LaLiga"],
    "M+ LALIGA 2 (M57 O112)": ["M+ LALIGA 2"],
    "M+ LALIGA 3 (M167 O270)": ["M+ LALIGA 3"],
    "M+ LALIGA 4 (M168 O417)": ["M+ LALIGA 4"],
    "M+ LALIGA 5 (M169 O418)": ["M+ LALIGA 5"],
    "M+ LALIGA 6 (M61 O419)": ["M+ LALIGA 6"],
    "LALIGA TV Hypermotion (M56 O120)": ["LaLiga TV Hypermotion"],
    "LALIGA TV Hypermotion 2 (M59 O121)": ["LaLiga TV Hypermotion 2"],
    "LALIGA TV Hypermotion 2 (M59 O120)": ["LaLiga TV Hypermotion 2"],
    "LALIGA TV Hypermotion 3 (M178 O290)": ["LaLiga TV Hypermotion 3"],
    "M+ Vamos (8 y 50)": ["M+ Vamos"],
    "M+ Vamos 2 (51)": ["M+ Vamos 2"],
    "M+ Vamos 3 (53)": ["M+ Vamos 3"],
    "M+ Ellas Vamos (66)": ["M+ Ellas Vamos"],
    "M+ Deportes (63)": ["M+ Deportes"],
    "M+ Deportes 2 (64)": ["M+ Deportes 2"],
    "M+ Deportes 3 (65)": ["M+ Deportes 3"],
    "M+ Deportes 4 (66)": ["M+ Deportes 4"],
    "M+ Deportes 4 (191)": ["M+ Deportes 4"],
    "M+ Deportes 5 (192)": ["M+ Deportes 5"],
    "M+ Deportes 6 (193)": ["M+ Deportes 6"],
    "M+ Deportes 7 (194)": ["M+ Deportes 7"],
    "M+ Deportes 8 (M195)": ["M+ Deportes 8"],
    "M+ Liga de Campeones (M60 O115)": ["M+ Liga de Campeones"],
    "M+ Liga de Campeones HDR (M442 O116)": ["M+ Liga de Campeones"],
    "M+ Liga de Campeones 2 (M61 O117)": ["M+ Liga de Campeones 2"],
    "M+ Liga de Campeones 3 (M62 O118)": ["M+ Liga de Campeones 3"],
    "M+ Liga de Campeones 4 (M180 O119)": ["M+ Liga de Campeones 4"],
    "M+ Liga de Campeones 5 (M181 O433)": ["M+ Liga de Campeones 5"],
    "M+ Liga de Campeones 6 (M182 O434)": ["M+ Liga de Campeones 6"],
    "M+ Liga de Campeones 7 (M183 O435)": ["M+ Liga de Campeones 7"],
    "Movistar Plus+ (M7)": ["MOVISTAR PLUS"],
    "LaLiga TV M1": ["LaLiga TV M1"],
    "LaLiga TV M2": ["LaLiga TV M2"],
    "LaLiga TV M3": ["LaLiga TV M3"],
    "LaLiga TV M4": ["LaLiga TV M4"],
    "LaLiga TV M5": ["LaLiga TV M5"],
    "LaLiga TV M6": ["LaLiga TV M6"],
    "LaLiga TV M7": ["LaLiga TV M7"],
    "LaLiga TV M8": ["LaLiga TV M8"],
    "LaLiga TV M9": ["LaLiga TV M9"],
    "LaLiga TV M10": ["LaLiga TV M10"],
    "Esport3 (Cataluña)": ["Esport3"],
    "RFEF.es": ["RFEF TV"],
    "Primera Federación (M52 O125)": ["RFEF TV"],
    "Primera Federación (M53 O125)": ["RFEF TV"],
    "Movistar Golf (M67)": ["M+ Golf"],
    "Movistar Golf (M68)": ["M+ Golf"],
    "Movistar Golf 2 (M68)": ["M+ Golf 2"],
    "Movistar Golf 2 (M69)": ["M+ Golf 2"],
    "DAZN 1 (M71 O113)": ["DAZN 1"],
    "DAZN 1 (M71)": ["DAZN 1"],
    "DAZN 1 (M70 O113)": ["DAZN 1"],
    "DAZN 1 (M72)": ["DAZN 1"],
    "DAZN 2 (M72)": ["DAZN 2"],
    "DAZN 2 (M71 O114)": ["DAZN 2"],
    "DAZN 2 (M72 O114)": ["DAZN 2"],
    "DAZN 2 (M73)": ["DAZN 2"],
    "DAZN 3 (M196)": ["DAZN 3"],
    "DAZN 4 (M197)": ["DAZN 4"],
    "DAZN F1 (M69)": ["DAZN F1"],
    "DAZN F1 (M69 O104)": ["DAZN F1"],
    "DAZN F1 (M70 O104)": ["DAZN F1"],
    "DAZN LaLiga (M55 O113)": ["DAZN LaLiga"],
    "DAZN LaLiga 2 (M58 O274)": ["DAZN LaLiga 2"],
    "DAZN LaLiga 2 (M58 O114)": ["DAZN LaLiga 2"],
    "DAZN LaLiga 4 (M174 O421)": ["DAZN LaLiga 4"],
    "DAZN LaLiga 5 (M175 O422)": ["DAZN LaLiga 5"],
    "DAZN Baloncesto (M73 O126)": ["DAZN Baloncesto"],
    "DAZN Baloncesto (M74 O126)": ["DAZN Baloncesto"],
    "DAZN Baloncesto (M87 O126)": ["DAZN Baloncesto"],
    "DAZN Baloncesto 2 (M74 O127)": ["DAZN Baloncesto 2"],
    "DAZN Baloncesto 2 (M75 O127)": ["DAZN Baloncesto 2"],
    "DAZN Baloncesto 3 (M75 O128)": ["DAZN Baloncesto 3"],
    "DAZN Baloncesto 3 (M76 O128)": ["DAZN Baloncesto 3"],
    "M+ Baloncesto (M66)": ["M+ Baloncesto"],
    "M+ Baloncesto 2 (M67)": ["M+ Baloncesto 2"],
    "M+ Baloncesto 3 (M194)": ["M+ Baloncesto 3"],
    "DAZN MotoGP (M70 O105)": ["Dazn MotoGP"],
    "DAZN MotoGP (M71 O105)": ["Dazn MotoGP", "Sky Sport MotoGP"],
    "Telecinco": ["Telecinco"],
    "Cuatro": ["Cuatro"],
    "Tennis Channel": ["Tennis Channel"],
    "TV5MONDE": ["TV5Monde Europe"],
    "La Otra (Madrid)": ["La Otra"],
    "TV3 (Cataluña)": ["TV3 CAT"],
    "Tennis Channel - Orange TV (131)": ["Tennis Channel"],
    "GOL (Síguelo en directo)": ["Gol TV"],
    "NBA League Pass": ["NBA League Pass", "NBA ESPN"],
    "Real Madrid TV": ["Real Madrid TV"],
    "M+ FanZone": ["M+ FanZone"],
    "DAZN Mundial 2 (M58 O114)": ["DAZN Mundial 2"],
    "DAZN Mundial 3 (M173 O420)": ["DAZN Mundial 3"],
    "Aragón Deporte": ["Aragón Deporte"],
}

# Channels that should not be searched in streaming catalog (broadcasters without linear AceStream)
EXCLUDED_CHANNELS: set[str] = {
    "antel tv internacional",
    "lpf play",
    "zapping internacional",
    "wta tv",
    "fanseat",
    "ehf tv",
    "rtve play",
    "atp tennis tv",
    "movistar+",
    "eurovision sports tv",
    "feb tv",
    "as.com",
    "laliga+ plus",
    "hbo max",
    "beisbolplay",
    "fifa+",
    "nwsl+",
    "red bull tv",
    "apple tv",
    "rcn nuestra tele",
    "tv5monde",
    "tvg2 (galicia)",
    "tvg (galicia)",
    "uefa tv",
    "lacronicadeportes.es",
    "aragón tv",
    "alhaurín tv",
    "sevilla fc +",
    "rtv marbella",
    "cmmplay (castilla-lm)",
    "tv melilla",
    "mediaset infinity",
    "be mad",
    "fanplay tv",
    "vinxtv",
    "plaiz",
}

GENERIC_FILTERS: list[str] = [
    "(ver en directo)",
    "(síguelo en directo)",
    "(acceder)",
    "youtube",
    "facebook",
    "onefootball",
    "bar",
    "gratis",
    "canal deporte tv",
    "etbk",
    "app",
    "twitter",
    "videopass",
    "twitch",
    "xarxa+",
    "web",
    "play",
]


def extract_stream_quality(name: str) -> str:
    """Extract standard resolution tag from channel name."""
    n = name.lower()
    if "4k" in n or "uhd" in n:
        return "4K"
    if "1080p" in n or "fhd" in n:
        return "1080p"
    if "720p" in n or "hd" in n:
        return "720p"
    return "SD"


def canonical_tokens(name: str) -> list[str]:
    """Tokenize channel name for deterministic semantic comparison."""
    n = name.lower()
    n = re.sub(r"\bm\+|\bm\.\b", "movistar ", n)
    n = re.sub(r"\blaliga\b", "la liga", n)
    n = re.sub(r"-->.*$", "", n)
    n = re.sub(r"\([^\)]*\)", "", n)
    n = re.sub(r"\b(1080p|720p|4k|uhd|fhd|hd|sd|hdr)\b", "", n)
    n = re.sub(r"[\*\+🔹★▲\-_]+", " ", n)
    # Strip standalone hex hashes (3-6 chars)
    n = re.sub(r"\b[0-9a-f]{3,6}\b", "", n)
    tokens = [t for t in n.split() if t]
    return tokens


def _clean_html_text(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return " ".join(s.split()).strip()


class AgendaService:
    def __init__(self, data_dir: str | None = None) -> None:
        self.data_dir = data_dir or Config.DATA_DIR
        self.cache_file = os.path.join(self.data_dir, "agenda_cache.json")
        self.equiv_file = os.path.join(self.data_dir, "equivalencias_canales.json")
        self.default_url = os.environ.get("AGENDA_URL", "https://www.futbolenlatv.es/deporte")
        self.cache_ttl = int(os.environ.get("AGENDA_CACHE_TTL", 1800))
        self._lock = threading.Lock()
        self._memory_cache: dict[str, Any] | None = None
        self._memory_cache_time: float = 0.0

    def load_equivalencias(self) -> dict[str, list[str]]:
        """Load equivalencias with user custom overrides if present."""
        equivs = dict(DEFAULT_EQUIVALENCIAS)
        if os.path.exists(self.equiv_file):
            try:
                with open(self.equiv_file, "r", encoding="utf-8") as f:
                    custom = json.load(f)
                if isinstance(custom, dict):
                    equivs.update(custom)
            except Exception as exc:
                logger.warning("Failed reading custom equivalencias_canales.json: %s", exc)
        return equivs

    def is_channel_excluded(self, channel_title: str) -> bool:
        """Check whether a channel should be ignored based on blocklists."""
        c_low = channel_title.strip().lower()
        if c_low in EXCLUDED_CHANNELS:
            return True
        for gen in GENERIC_FILTERS:
            if gen in c_low:
                return True
        return False

    def match_channel_to_catalog(
        self,
        tv_channel_name: str,
        catalog_channels: list[dict[str, Any]],
        equivalencias: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        """Match TV guide channel against current AceHLS catalog with multi-stream discovery."""
        targets = equivalencias.get(tv_channel_name, [tv_channel_name])
        matches: list[dict[str, Any]] = []
        seen_stream_ids: set[str] = set()

        quality_order = {"4K": 4, "1080p": 3, "720p": 2, "SD": 1}

        for target in targets:
            t_tokens = canonical_tokens(target)
            if not t_tokens:
                continue
            t_nums = [tok for tok in t_tokens if tok.isdigit()]
            non_num_t = [tok for tok in t_tokens if not tok.isdigit()]

            for ch in catalog_channels:
                c_tokens = canonical_tokens(ch.get("name", ""))
                c_set = set(c_tokens)
                c_nums = [tok for tok in c_tokens if tok.isdigit()]

                # Strict number / dial boundary check
                if t_nums != c_nums:
                    continue

                if all(tok in c_set for tok in non_num_t):
                    channel_id = str(ch.get("id") or ch.get("stream_id") or "")
                    sid = channel_id or str(ch.get("name") or "")
                    if not sid or sid in seen_stream_ids:
                        continue
                    seen_stream_ids.add(sid)

                    q = extract_stream_quality(ch.get("name", ""))
                    matches.append({
                        "channel_name": ch.get("name"),
                        "stream_id": channel_id,
                        "source_name": ch.get("source_name") or "AceHLS",
                        "source_id": ch.get("source_id"),
                        "identifier_type": ch.get("identifier_type", "id"),
                        "quality": q,
                        "quality_score": quality_order.get(q, 0),
                        "type": ch.get("type", "acestream"),
                    })

        # Sort streams by quality descending (1080p before 720p before SD)
        matches.sort(key=lambda item: item["quality_score"], reverse=True)
        return matches

    def parse_agenda_html(self, html_content: str) -> list[dict[str, Any]]:
        """Parse raw HTML from futbolenlatv.es into structured daily events."""
        days: list[dict[str, Any]] = []
        table_pattern = re.compile(r'<table[^>]*class="[^"]*tablaPrincipal[^"]*"[^>]*>(.*?)</table>', re.DOTALL)

        for table_match in table_pattern.finditer(html_content):
            table_html = table_match.group(1)

            cabecera_m = re.search(r'<tr[^>]*class="[^"]*cabeceraTabla[^"]*"[^>]*>(.*?)</tr>', table_html, re.DOTALL)
            date_str = ""
            day_title = ""
            if cabecera_m:
                raw_title = _clean_html_text(cabecera_m.group(1))
                day_title = raw_title
                date_match = re.search(r"(\d{2}/\d{2}/\d{4})", raw_title)
                if date_match:
                    date_str = date_match.group(1)

            events: list[dict[str, Any]] = []
            rows = re.findall(r"<tr\b[^>]*>(.*?)</tr>", table_html, re.DOTALL)

            for r in rows:
                if "cabeceraTabla" in r:
                    continue

                hora_m = re.search(r'class="[^"]*hora[^"]*"[^>]*>(.*?)</td>', r, re.DOTALL)
                hora = _clean_html_text(hora_m.group(1)) if hora_m else ""
                if not hora:
                    continue

                comp_m = re.search(r'class="[^"]*ajusteDoslineas[^"]*"[^>]*title="([^"]+)"', r)
                comp_label_m = re.search(r'class="[^"]*detalles[^"]*"[^>]*label[^>]*title="([^"]+)"', r)
                comp_img_m = re.search(r'class="[^"]*(?:contenedorImgCompeticion|detalles)[^"]*"[^>]*<img[^>]*src="([^"]+)"', r)

                comp_parts = []
                if comp_label_m:
                    comp_parts.append(_clean_html_text(comp_label_m.group(1)))
                if comp_m:
                    comp_parts.append(_clean_html_text(comp_m.group(1)))
                elif not comp_parts:
                    cont_m = re.search(r'class="[^"]*ajusteDoslineas[^"]*"[^>]*>(.*?)</div>', r, re.DOTALL)
                    if cont_m:
                        comp_parts.append(_clean_html_text(cont_m.group(1)))

                competicion = " | ".join(p for p in comp_parts if p)
                comp_icon = comp_img_m.group(1) if comp_img_m else ""

                evento = ""
                local_img = ""
                vis_img = ""
                evento_unico_m = re.search(r'class="[^"]*eventoUnico[^"]*"[^>]*>(.*?)</td>', r, re.DOTALL)
                if evento_unico_m:
                    evento = _clean_html_text(evento_unico_m.group(1))
                else:
                    loc_m = re.search(r'class="[^"]*local[^"]*"[^>]*>.*?title="([^"]+)"', r, re.DOTALL)
                    vis_m = re.search(r'class="[^"]*visitante[^"]*"[^>]*>.*?title="([^"]+)"', r, re.DOTALL)
                    loc_img_m = re.search(r'class="[^"]*local[^"]*"[^>]*><img[^>]*src="([^"]+)"', r, re.DOTALL)
                    vis_img_m = re.search(r'class="[^"]*visitante[^"]*"[^>]*><img[^>]*src="([^"]+)"', r, re.DOTALL)

                    loc = _clean_html_text(loc_m.group(1)) if loc_m else ""
                    vis = _clean_html_text(vis_m.group(1)) if vis_m else ""
                    local_img = loc_img_m.group(1) if loc_img_m else ""
                    vis_img = vis_img_m.group(1) if vis_img_m else ""

                    if loc and vis:
                        evento = f"{loc} - {vis}"
                    else:
                        evento = loc or vis

                canales_raw = re.findall(r'<li[^>]*title="([^"]+)"', r)
                canales: list[str] = []
                for c in canales_raw:
                    idx = c.rfind(")")
                    cleaned = c[: idx + 1].strip() if idx != -1 else c.strip()
                    if cleaned and not self.is_channel_excluded(cleaned) and cleaned not in canales:
                        canales.append(cleaned)

                if hora and evento and canales:
                    events.append({
                        "time": hora,
                        "event": evento,
                        "competition": competicion,
                        "competition_icon": comp_icon,
                        "local_icon": local_img,
                        "visitante_icon": vis_img,
                        "channels": canales,
                    })

            days.append({
                "date": date_str,
                "title": day_title,
                "events_count": len(events),
                "events": events,
            })

        return days

    def _calculate_live_status(self, event_date_str: str, event_time_str: str) -> tuple[bool, bool]:
        """Determine if an event is currently live or upcoming within 30 min.
        
        Uses local server time (Europe/Madrid / CEST).
        Returns (is_live, is_upcoming).
        """
        try:
            now = datetime.datetime.now()
            day, month, year = [int(x) for x in event_date_str.split("/")]
            hour, minute = [int(x) for x in event_time_str.split(":")]
            event_dt = datetime.datetime(year, month, day, hour, minute)

            diff = (event_dt - now).total_seconds()

            # Live: Started between 0 and 135 minutes ago, or starts in next 5 minutes
            is_live = -8100 <= diff <= 300
            # Upcoming: Starts in next 30 minutes
            is_upcoming = 300 < diff <= 1800
            return is_live, is_upcoming
        except Exception:
            return False, False

    def fetch_raw_agenda(self) -> str:
        """Fetch fresh HTML from the sports guide."""
        req = urllib.request.Request(
            self.default_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
            },
        )
        with urllib.request.urlopen(req, timeout=12) as response:
            return response.read().decode("utf-8", errors="replace")

    def get_agenda(
        self,
        catalog_channels: list[dict[str, Any]] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        """Return parsed sports agenda crossed with currently available AceHLS channels."""
        now = time.time()

        with self._lock:
            cached_payload: dict[str, Any] | None = None

            # 1. Check memory cache
            if not force_refresh and self._memory_cache and (now - self._memory_cache_time) < self.cache_ttl:
                cached_payload = self._memory_cache

            # 2. Check disk cache
            if not cached_payload and not force_refresh and os.path.exists(self.cache_file):
                try:
                    mtime = os.path.getmtime(self.cache_file)
                    if (now - mtime) < self.cache_ttl:
                        with open(self.cache_file, "r", encoding="utf-8") as f:
                            cached_payload = json.load(f)
                            self._memory_cache = cached_payload
                            self._memory_cache_time = mtime
                except Exception as exc:
                    logger.warning("Error reading disk agenda cache: %s", exc)

            # 3. If no cache or force refresh, fetch and parse
            if not cached_payload:
                try:
                    raw_html = self.fetch_raw_agenda()
                    parsed_days = self.parse_agenda_html(raw_html)
                    cached_payload = {
                        "updated_at": datetime.datetime.now().isoformat(),
                        "days": parsed_days,
                    }
                    # Save raw parsed agenda
                    atomic_write_json(self.cache_file, cached_payload)
                    self._memory_cache = cached_payload
                    self._memory_cache_time = now
                except Exception as exc:
                    logger.error("Failed fetching sports agenda: %s", exc)
                    # Fallback to existing stale cache if network fails
                    if self._memory_cache:
                        cached_payload = self._memory_cache
                    elif os.path.exists(self.cache_file):
                        with open(self.cache_file, "r", encoding="utf-8") as f:
                            cached_payload = json.load(f)
                    else:
                        return {
                            "error": str(exc),
                            "updated_at": None,
                            "days": [],
                            "total_events": 0,
                            "available_events": 0,
                        }

        if not cached_payload:
            cached_payload = {}

        # 4. Cross with channels catalog (dynamic on each request)
        equivalencias = self.load_equivalencias()
        catalog = catalog_channels if catalog_channels is not None else self._load_default_channels()

        total_events = 0
        available_events = 0
        enriched_days = []

        days_list: list[dict[str, Any]] = cached_payload.get("days", [])
        for day in days_list:
            date_str = day.get("date", "")
            enriched_events = []

            for ev in day.get("events", []):
                total_events += 1
                ev_time = ev.get("time", "")
                is_live, is_upcoming = self._calculate_live_status(date_str, ev_time)

                matched_streams: list[dict[str, Any]] = []
                for ch_name in ev.get("channels", []):
                    m = self.match_channel_to_catalog(ch_name, catalog, equivalencias)
                    matched_streams.extend(m)

                # Deduplicate streams by stream_id
                unique_streams: list[dict[str, Any]] = []
                seen_ids: set[str] = set()
                for st in matched_streams:
                    sid = str(st.get("stream_id") or st.get("channel_name") or "")
                    if sid and sid not in seen_ids:
                        seen_ids.add(sid)
                        unique_streams.append(st)

                has_streams = len(unique_streams) > 0
                if has_streams:
                    available_events += 1

                enriched_events.append({
                    **ev,
                    "is_live": is_live,
                    "is_upcoming": is_upcoming,
                    "available": has_streams,
                    "streams_count": len(unique_streams),
                    "primary_stream_id": unique_streams[0]["stream_id"] if has_streams else None,
                    "streams": unique_streams,
                })

            enriched_days.append({
                **day,
                "events_count": len(enriched_events),
                "events": enriched_events,
            })

        return {
            "updated_at": cached_payload.get("updated_at"),
            "total_events": total_events,
            "available_events": available_events,
            "days": enriched_days,
        }

    def get_live_events(self, catalog_channels: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
        """Return only active events that are currently live."""
        agenda = self.get_agenda(catalog_channels=catalog_channels)
        live_list = []
        for day in agenda.get("days", []):
            for ev in day.get("events", []):
                if ev.get("is_live"):
                    live_list.append(ev)
        return live_list

    def generate_agenda_m3u(
        self,
        host: str,
        profile: str = "original",
        catalog_channels: list[dict[str, Any]] | None = None,
        live_only: bool = False,
    ) -> str:
        """Generate dynamic M3U playlist from current sports agenda with multi-origin signals."""
        agenda = self.get_agenda(catalog_channels=catalog_channels)
        lines = ["#EXTM3U"]

        profiles_to_render = (
            ["direct", "original", "max_compat", "720p"]
            if profile == "all"
            else [profile]
        )

        for day in agenda.get("days", []):
            date_str = day.get("date", "")
            day_title = day.get("title") or date_str or "Eventos"
            day_label = (
                "Hoy"
                if "hoy" in day_title.lower()
                else ("Mañana" if "mañana" in day_title.lower() else date_str)
            )

            for ev in day.get("events", []):
                if live_only and not ev.get("is_live"):
                    continue
                if not ev.get("available") or not ev.get("streams"):
                    continue

                event_title = ev.get("event", "Evento deportivo")
                time_str = ev.get("time", "")
                is_live = ev.get("is_live", False)
                comp = ev.get("competition", "")
                logo = ev.get("competition_icon") or ev.get("local_icon") or ""

                live_tag = "[⚡ VIVO] " if is_live else ""

                for st in ev["streams"]:
                    sid = st.get("stream_id")
                    if not sid:
                        continue
                    q = st.get("quality", "SD")
                    src = st.get("source_name", "AceHLS")
                    ident_type = st.get("identifier_type", "id")

                    for p in profiles_to_render:
                        if profile == "all":
                            surface_name = {
                                "direct": "Directo",
                                "original": "HLS Original",
                                "max_compat": "HLS Compatible",
                                "720p": "HLS 720p",
                                "480p": "HLS 480p",
                            }.get(p, p)
                            group = f"⚽ {day_label} · {surface_name}"
                        else:
                            group = (
                                f"⚽ {day_label} - {comp}"
                                if comp
                                else f"⚽ {day_label}"
                            )

                        display_name = f"{live_tag}[{time_str}] {event_title} ({q} · {src})"

                        if p == "direct":
                            from app import utils
                            link = utils.get_stream_url_for_client(host, sid, ident_type)
                        else:
                            type_suffix = (
                                "&identifier_type=infohash"
                                if ident_type == "infohash"
                                else ""
                            )
                            suffix = (
                                f"?profile={p}{type_suffix}"
                                if p and p != "original"
                                else (
                                    f"?identifier_type=infohash"
                                    if ident_type == "infohash"
                                    else ""
                                )
                            )
                            link = f"http://{host}/stream/{sid}.m3u8{suffix}"

                        safe_title = str(display_name).replace("\r", " ").replace("\n", " ")
                        safe_group = str(group).replace('"', "'").replace("\r", " ").replace("\n", " ")
                        safe_logo = str(logo).replace('"', "'").replace("\r", " ").replace("\n", " ")

                        lines.append(
                            f'#EXTINF:-1 tvg-id="{sid}" tvg-name="{safe_title}" tvg-logo="{safe_logo}" group-title="{safe_group}",{safe_title}'
                        )
                        lines.append(link)

        return "\n".join(lines)

    def _load_default_channels(self) -> list[dict[str, Any]]:
        """Load global channel catalog from channels.json."""
        ch_file = os.path.join(self.data_dir, "channels.json")
        if os.path.exists(ch_file):
            try:
                with open(ch_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return []


agenda_service = AgendaService()
