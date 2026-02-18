import json
import os
import random
import sqlite3
import ssl
import threading
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

DB_PATH = 'tips.db'
HOST = '0.0.0.0'
PORT = int(os.getenv('PORT', '3000'))
TARGET_EMAIL = os.getenv('TARGET_EMAIL', 'petrcimera@gmail.com')
RESEND_API_KEY = os.getenv('RESEND_API_KEY', 're_MzZPyois_KmMYeivR93BFTR9GHKrkZMjG')
RESEND_FROM_EMAIL = os.getenv('RESEND_FROM_EMAIL', 'onboarding@resend.dev')

SPORTS = ['Fotbal', 'Hokej']
FOOTBALL_LEAGUES = ['Premier League', 'La Liga', 'Serie A', 'Bundesliga', 'Ligue 1']
HOCKEY_LEAGUES = ['NHL', 'Tipsport Extraliga', 'AHL', 'SHL', 'Liiga']
PICKS = ['Výhra domácích', 'Výhra hostů', 'Over 2.5', 'Under 2.5', 'Oba týmy dají gól']


def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_conn()
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS tips (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sport TEXT NOT NULL,
            league TEXT NOT NULL,
            match_name TEXT NOT NULL,
            start_time TEXT NOT NULL,
            pick TEXT NOT NULL,
            odds REAL NOT NULL,
            confidence INTEGER NOT NULL,
            result TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
        '''
    )
    conn.commit()
    conn.close()


def random_tip():
    sport = random.choice(SPORTS)
    league = random.choice(FOOTBALL_LEAGUES if sport == 'Fotbal' else HOCKEY_LEAGUES)
    now = datetime.now()
    start = now.replace(hour=12 + random.randint(0, 10), minute=random.randint(0, 59), second=0, microsecond=0)
    return (
        sport,
        league,
        f"{league} {'FC' if sport == 'Fotbal' else 'HC'} {random.randint(1,99)} vs {'United' if sport == 'Fotbal' else 'Wolves'} {random.randint(1,99)}",
        start.isoformat(),
        random.choice(PICKS),
        round(random.uniform(1.4, 3.6), 2),
        random.randint(55, 95),
        datetime.now().isoformat(),
    )


def insert_tips(count):
    conn = db_conn()
    conn.executemany(
        '''
        INSERT INTO tips (sport, league, match_name, start_time, pick, odds, confidence, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''',
        [random_tip() for _ in range(count)],
    )
    conn.commit()
    conn.close()


def seed_tips():
    conn = db_conn()
    c = conn.execute('SELECT COUNT(*) AS count FROM tips').fetchone()['count']
    conn.close()
    if c < 20:
        insert_tips(20 - c)


def summary_stats():
    conn = db_conn()
    row = conn.execute(
        '''
        SELECT COUNT(*) total,
               SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) wins,
               SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) losses,
               SUM(CASE WHEN result='pending' THEN 1 ELSE 0 END) pending
        FROM tips
        '''
    ).fetchone()
    conn.close()
    wins = row['wins'] or 0
    losses = row['losses'] or 0
    resolved = wins + losses
    rate = round((wins / resolved) * 100, 1) if resolved else 0
    return {'total': row['total'] or 0, 'wins': wins, 'losses': losses, 'pending': row['pending'] or 0, 'success_rate': rate}


def detailed_stats():
    conn = db_conn()
    by_sport = [dict(r) for r in conn.execute(
        "SELECT sport, SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) wins, SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) losses FROM tips GROUP BY sport"
    ).fetchall()]
    by_league = [dict(r) for r in conn.execute(
        "SELECT league, SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) wins, SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) losses FROM tips GROUP BY league ORDER BY league"
    ).fetchall()]
    by_month = [dict(r) for r in conn.execute(
        "SELECT substr(start_time, 1, 7) month, SUM(CASE WHEN result='win' THEN 1 ELSE 0 END) wins, SUM(CASE WHEN result='loss' THEN 1 ELSE 0 END) losses FROM tips GROUP BY month ORDER BY month"
    ).fetchall()]
    conn.close()
    return {'by_sport': by_sport, 'by_league': by_league, 'by_month': by_month}


def send_daily_email():
    conn = db_conn()
    today = datetime.now().date().isoformat()
    tips = conn.execute(
        "SELECT * FROM tips WHERE substr(start_time,1,10)=? ORDER BY confidence DESC LIMIT 20", (today,)
    ).fetchall()
    conn.close()

    rows = ''.join(
        [
            f"<li><strong>{t['sport']}</strong> | {t['league']} | {t['match_name']} | Tip: {t['pick']} | Kurz: {t['odds']} | Důvěra: {t['confidence']}% | Začátek: {datetime.fromisoformat(t['start_time']).strftime('%d.%m.%Y %H:%M')}</li>"
            for t in tips
        ]
    )

    payload = json.dumps(
        {
            'from': RESEND_FROM_EMAIL,
            'to': [TARGET_EMAIL],
            'subject': 'Denní tipy na kurzové sázení (fotbal + hokej)',
            'html': f'<h2>Dnešní tipy</h2><ol>{rows}</ol>',
        }
    ).encode('utf-8')

    req = urllib.request.Request(
        'https://api.resend.com/emails',
        data=payload,
        headers={
            'Authorization': f'Bearer {RESEND_API_KEY}',
            'Content-Type': 'application/json',
        },
        method='POST',
    )

    context = ssl.create_default_context()
    with urllib.request.urlopen(req, context=context, timeout=20) as resp:
        return resp.read().decode('utf-8')


def scheduler_loop():
    last_sent_day = None
    while True:
        now = datetime.now()
        if now.hour == 8 and now.minute == 0:
            day = now.date().isoformat()
            if day != last_sent_day:
                try:
                    send_daily_email()
                    print('Denní email byl odeslán.')
                except Exception as exc:
                    print('Chyba při odeslání denního emailu:', exc)
                last_sent_day = day
        time.sleep(30)


def html_layout(title, body):
    return f'''<!doctype html>
<html lang="cs">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <link rel="stylesheet" href="/styles.css" />
</head>
<body>
{body}
</body>
</html>'''.encode('utf-8')


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == '/styles.css':
            self.serve_css()
            return
        if parsed.path == '/stats':
            self.page_stats()
            return
        if parsed.path == '/':
            self.page_index(parsed.query)
            return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'Not found')

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        length = int(self.headers.get('Content-Length', 0))
        raw = self.rfile.read(length).decode('utf-8')
        data = urllib.parse.parse_qs(raw)

        if parsed.path == '/generate':
            count = max(1, int(data.get('count', ['10'])[0]))
            insert_tips(count)
            return self.redirect('/')

        if parsed.path == '/update-result':
            tip_id = int(data.get('id', ['0'])[0])
            result = data.get('result', ['pending'])[0]
            if result in ('pending', 'win', 'loss') and tip_id > 0:
                conn = db_conn()
                conn.execute('UPDATE tips SET result=? WHERE id=?', (result, tip_id))
                conn.commit()
                conn.close()
            return self.redirect('/')

        if parsed.path == '/send-email':
            try:
                send_daily_email()
            except Exception as exc:
                print('Email se nepodařilo odeslat:', exc)
            return self.redirect('/')

        self.send_response(404)
        self.end_headers()

    def page_index(self, query):
        params = urllib.parse.parse_qs(query)
        league = params.get('league', [''])[0]
        min_conf = int(params.get('minConfidence', ['0'])[0] or 0)

        conn = db_conn()
        leagues = [r['league'] for r in conn.execute('SELECT DISTINCT league FROM tips ORDER BY league').fetchall()]

        sql = 'SELECT * FROM tips'
        clauses = []
        args = []
        if league:
            clauses.append('league=?')
            args.append(league)
        if min_conf:
            clauses.append('confidence>=?')
            args.append(min_conf)
        if clauses:
            sql += ' WHERE ' + ' AND '.join(clauses)
        sql += ' ORDER BY start_time ASC'

        tips = conn.execute(sql, args).fetchall()
        conn.close()
        stats = summary_stats()

        rows = ''
        for t in tips:
            start = datetime.fromisoformat(t['start_time']).strftime('%d.%m.%Y %H:%M')
            badge = {'win': 'Výhra', 'loss': 'Prohra', 'pending': 'Čeká'}[t['result']]
            rows += f'''
<tr>
  <td>{t['sport']}</td><td>{t['league']}</td><td>{t['match_name']}</td><td>{start}</td>
  <td>{t['pick']}</td><td>{t['odds']}</td><td>{t['confidence']}%</td>
  <td><span class="badge {t['result']}">{badge}</span></td>
  <td>
    <form method="POST" action="/update-result" class="inline-form">
      <input type="hidden" name="id" value="{t['id']}" />
      <select name="result">
        <option value="pending" {'selected' if t['result']=='pending' else ''}>Čeká</option>
        <option value="win" {'selected' if t['result']=='win' else ''}>Výhra</option>
        <option value="loss" {'selected' if t['result']=='loss' else ''}>Prohra</option>
      </select>
      <button type="submit">Uložit</button>
    </form>
  </td>
</tr>'''

        league_opts = '<option value="">Všechny</option>' + ''.join(
            [f'<option value="{l}" {"selected" if l == league else ""}>{l}</option>' for l in leagues]
        )

        body = f'''
<header>
  <h1>Denní tipy na kurzové sázení (Fotbal + Hokej)</h1>
  <p>Tipy pro aktuální den, historie, ruční aktualizace výsledků a automatické statistiky.</p>
</header>
<section class="cards">
  <div class="card"><h3>Celkem</h3><p>{stats['total']}</p></div>
  <div class="card"><h3>Výhry</h3><p>{stats['wins']}</p></div>
  <div class="card"><h3>Prohry</h3><p>{stats['losses']}</p></div>
  <div class="card"><h3>Úspěšnost</h3><p>{stats['success_rate']}%</p></div>
</section>
<section class="panel">
  <form method="POST" action="/generate" class="inline-form">
    <label>Generovat další tipy:</label>
    <input type="number" name="count" min="1" value="10" />
    <button type="submit">Generovat</button>
  </form>
  <form method="POST" action="/send-email" class="inline-form">
    <button type="submit">Odeslat dnešní tipy na email</button>
  </form>
  <a class="button-link" href="/stats">Podrobné statistiky</a>
</section>
<section class="panel">
  <h2>Filtrování</h2>
  <form method="GET" action="/" class="inline-form">
    <label>Liga:</label>
    <select name="league">{league_opts}</select>
    <label>Minimální důvěra:</label>
    <input type="number" name="minConfidence" min="0" max="100" value="{min_conf if min_conf else ''}" />
    <button type="submit">Filtrovat</button>
    <a href="/">Reset</a>
  </form>
</section>
<section>
  <h2>Tipy a historie</h2>
  <table>
    <thead><tr><th>Sport</th><th>Liga</th><th>Zápas</th><th>Začátek</th><th>Tip</th><th>Kurz</th><th>Důvěra</th><th>Výsledek</th><th>Aktualizace</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
</section>
'''

        page = html_layout('Denní tipy', body)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(page)

    def page_stats(self):
        stats = detailed_stats()
        body = f'''
<header>
  <h1>Podrobnější statistiky</h1>
  <a class="button-link" href="/">← Zpět</a>
</header>
<section class="charts-grid">
  <div class="chart-card"><h2>Úspěšnost podle sportu</h2><canvas id="sportChart"></canvas></div>
  <div class="chart-card"><h2>Úspěšnost podle ligy</h2><canvas id="leagueChart"></canvas></div>
  <div class="chart-card full"><h2>Úspěšnost podle měsíce</h2><canvas id="monthChart"></canvas></div>
</section>
<script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
<script>
const stats = {json.dumps(stats)};
const pct = (arr) => arr.map(i => {{ const t=(i.wins||0)+(i.losses||0); return t?((i.wins||0)/t*100).toFixed(1):0; }});
new Chart(document.getElementById('sportChart'), {{type:'bar',data:{{labels:stats.by_sport.map(i=>i.sport),datasets:[{{label:'Úspěšnost %',data:pct(stats.by_sport),backgroundColor:'#4338ca'}}]}}}});
new Chart(document.getElementById('leagueChart'), {{type:'bar',data:{{labels:stats.by_league.map(i=>i.league),datasets:[{{label:'Úspěšnost %',data:pct(stats.by_league),backgroundColor:'#15803d'}}]}}}});
new Chart(document.getElementById('monthChart'), {{type:'line',data:{{labels:stats.by_month.map(i=>i.month),datasets:[{{label:'Úspěšnost %',data:pct(stats.by_month),borderColor:'#b91c1c',tension:0.2}}]}}}});
</script>
'''
        page = html_layout('Statistiky', body)
        self.send_response(200)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(page)

    def serve_css(self):
        css = '''
body { font-family: Arial, sans-serif; background:#f8fafc; color:#0f172a; margin:0; padding:24px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(160px,1fr)); gap:12px; margin:16px 0; }
.card, .panel, .chart-card, table { background:white; border-radius:10px; box-shadow:0 2px 8px rgba(0,0,0,.07); }
.card, .panel, .chart-card { padding:12px; }
.inline-form { display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:8px; }
button, .button-link { background:#1d4ed8; color:white; border:none; border-radius:8px; padding:8px 12px; text-decoration:none; cursor:pointer; }
table { width:100%; border-collapse:collapse; overflow:hidden; }
th,td { border-bottom:1px solid #e2e8f0; padding:10px; text-align:left; vertical-align:top; }
.badge { color:white; border-radius:99px; padding:4px 8px; font-size:12px; }
.badge.win { background:#16a34a; } .badge.loss { background:#dc2626; } .badge.pending { background:#64748b; }
.charts-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(320px,1fr)); gap:12px; }
.full { grid-column:1/-1; }
'''.encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'text/css; charset=utf-8')
        self.end_headers()
        self.wfile.write(css)

    def redirect(self, location):
        self.send_response(302)
        self.send_header('Location', location)
        self.end_headers()


if __name__ == '__main__':
    init_db()
    seed_tips()
    threading.Thread(target=scheduler_loop, daemon=True).start()
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f'Server běží na http://localhost:{PORT}')
    server.serve_forever()
