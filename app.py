#!/usr/bin/env python3
"""Serveur local de mesure ferroviaire : aucune dépendance pip."""
from __future__ import annotations
import argparse
import json
import re
import threading
import webbrowser
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import railway

ROOT = Path(__file__).resolve().parent
WEB = ROOT / 'web'
CACHE = ROOT / 'cache'
MAX_AGE_SECONDS = 24 * 3600


def route_payload(relation_id: int) -> dict:
    CACHE.mkdir(exist_ok=True)
    target = CACHE / f'osm_{relation_id}.json'
    if target.exists() and datetime.now().timestamp() - target.stat().st_mtime < MAX_AGE_SECONDS:
        return json.loads(target.read_text(encoding='utf-8'))
    xml = railway.fetch_route_tree(relation_id)
    route = railway.parse_route(xml, relation_id)
    ways = []
    for ref, ids in route['line_ways'].items():
        coords = [list(route['nodes'][nid]) for nid in ids]
        ways.append({'id': ref, 'ids': ids, 'coordinates': coords})
    result = {
        'relation_id': relation_id,
        'name': route['name'],
        'source': 'OpenStreetMap',
        'fetched_at': datetime.now(timezone.utc).isoformat(),
        'ways': ways,
        'stations': route['stations'],
        'switches': route['switches'],
    }
    tmp = target.with_suffix('.tmp')
    tmp.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    tmp.replace(target)
    return result


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        request = urlparse(self.path)
        if request.path == '/api/route':
            raw = parse_qs(request.query).get('id', [''])[0]
            if not re.fullmatch(r'[1-9]\d{0,11}', raw):
                return self.send_json({'error': 'Identifiant de relation OSM invalide.'}, 400)
            try:
                return self.send_json(route_payload(int(raw)))
            except Exception as exc:
                return self.send_json({'error': str(exc)}, 502)
        if request.path in ('/', '/index.html', '/style.css', '/app.js'):
            filename = 'index.html' if request.path == '/' else request.path.lstrip('/')
            path = WEB / filename
            data = path.read_bytes()
            content_type = 'text/html; charset=utf-8' if filename.endswith('.html') else ('text/css; charset=utf-8' if filename.endswith('.css') else 'text/javascript; charset=utf-8')
            self.send_response(200)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            return self.wfile.write(data)
        if request.path == '/health':
            return self.send_json({'ok': True})
        self.send_error(404, 'Not found')

    def send_json(self, payload, status=200):
        data = json.dumps(payload, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        print('[HTTP] ' + fmt % args)


def main():
    parser = argparse.ArgumentParser(description='Mesurer des distances le long des voies OSM en feet.')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    url = f'http://127.0.0.1:{args.port}/'
    print('\n  Houston Track Measure — ' + url)
    print('  Ctrl+C pour arrêter. Internet nécessaire pour OSM / cartes.\n')
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nArrêt du serveur.')
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
