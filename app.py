import os, json, requests, smtplib, queue, time, threading, sqlite3
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from flask import Flask, request, jsonify, render_template, Response, stream_with_context
from datetime import datetime

import os
app = Flask(__name__, 
            template_folder=os.path.join(os.getcwd(), 'templates'),
            static_folder=os.path.join(os.getcwd(), 'static'))

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
EMAIL_FROM         = os.environ.get("EMAIL_FROM", "")
EMAIL_PASSWORD     = os.environ.get("EMAIL_PASSWORD", "")
EMAIL_TO           = os.environ.get("EMAIL_TO", "")
WEBHOOK_SECRET     = os.environ.get("WEBHOOK_SECRET", "my-secret-key")
DB_PATH            = os.environ.get("DB_PATH", "calls.db")

# SSE broadcast — هر تب مرورگر یه queue داره
_sse_clients = []
_sse_lock = threading.Lock()

def sse_broadcast(data: dict):
    msg = f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try: q.put_nowait(msg)
            except: dead.append(q)
        for q in dead: _sse_clients.remove(q)

# ── DB ──────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS calls (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        call_id TEXT, seller_name TEXT, seller_number TEXT,
        customer_number TEXT, direction TEXT, duration INTEGER,
        result TEXT, started_at TEXT, ended_at TEXT,
        ai_score INTEGER, ai_duration_analysis TEXT,
        ai_strengths TEXT, ai_weaknesses TEXT,
        ai_suggestions TEXT, ai_script_tip TEXT, ai_follow_up TEXT,
        raw_payload TEXT,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit(); conn.close()

def save_call(d: dict) -> int:
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""INSERT INTO calls (call_id,seller_name,seller_number,
        customer_number,direction,duration,result,started_at,ended_at,
        ai_score,ai_duration_analysis,ai_strengths,ai_weaknesses,
        ai_suggestions,ai_script_tip,ai_follow_up,raw_payload)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        d.get("call_id"), d.get("seller_name"), d.get("seller_number"),
        d.get("customer_number"), d.get("direction"), d.get("duration"),
        d.get("result"), d.get("started_at"), d.get("ended_at"),
        d.get("ai_score"), d.get("ai_duration_analysis"),
        d.get("ai_strengths"), d.get("ai_weaknesses"),
        d.get("ai_suggestions"), d.get("ai_script_tip"), d.get("ai_follow_up"),
        json.dumps(d.get("raw_payload", {}), ensure_ascii=False)
    ))
    row_id = c.lastrowid
    conn.commit(); conn.close()
    return row_id

def get_calls(date=None, seller=None, limit=100):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    q = "SELECT * FROM calls WHERE 1=1"
    p = []
    if date:   q += " AND DATE(created_at)=?"; p.append(date)
    if seller: q += " AND seller_name LIKE ?"; p.append(f"%{seller}%")
    q += f" ORDER BY created_at DESC LIMIT {limit}"
    rows = [dict(r) for r in c.execute(q, p).fetchall()]
    conn.close()
    return rows

def get_stats():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    def one(q, *p): return (c.execute(q,p).fetchone() or [None])[0]
    stats = {
        "today_calls":   one("SELECT COUNT(*) FROM calls WHERE DATE(created_at)=?", today),
        "avg_score":     round(one("SELECT AVG(ai_score) FROM calls WHERE DATE(created_at)=?", today) or 0),
        "avg_duration":  round(one("SELECT AVG(duration) FROM calls WHERE DATE(created_at)=?", today) or 0),
        "total_calls":   one("SELECT COUNT(*) FROM calls"),
        "sellers_today": one("SELECT COUNT(DISTINCT seller_name) FROM calls WHERE DATE(created_at)=?", today),
    }
    # per-seller stats today
    rows = c.execute("""SELECT seller_name,
        COUNT(*) as cnt, AVG(ai_score) as avg_s, AVG(duration) as avg_d
        FROM calls WHERE DATE(created_at)=? GROUP BY seller_name
        ORDER BY avg_s DESC""", (today,)).fetchall()
    stats["sellers"] = [{"name": r[0], "count": r[1],
        "avg_score": round(r[2] or 0), "avg_duration": round(r[3] or 0)} for r in rows]
    conn.close()
    return stats

# ── Claude آنالیز ───────────────────────────────────────────────
def analyze_with_claude(call_info: dict) -> dict:
    duration = call_info.get("duration", 0)
    direction_fa = "خروجی" if call_info.get("direction") == "outgoing" else "ورودی"
    prompt = f"""شما متخصص ارشد فروش تلفنی تجهیزات هوشمند در بازار ایران هستید.

اطلاعات تماس از VoIP دفترشما:
- فروشنده: {call_info.get("seller_name","نامشخص")}
- مشتری: {call_info.get("customer_number","نامشخص")}
- نوع: {direction_fa}
- مدت: {duration} ثانیه ({duration//60} دقیقه و {duration%60} ثانیه)
- زمان پایان: {call_info.get("ended_at","")}

راهنمای تفسیر مدت:
زیر ۳۰ ثانیه: تماس ناموفق یا قطع شده | ۳۰-۹۰ ثانیه: معرفی اولیه ضعیف | ۲-۵ دقیقه: مکالمه کوتاه | ۵-۱۲ دقیقه: مذاکره جدی | بالای ۱۲ دقیقه: مشتری علاقه‌مند

فقط JSON زیر را برگردانید، هیچ متن اضافه‌ای ندهید:
{{
  "score": <0-100>,
  "duration_analysis": "<تحلیل دقیق مدت تماس در ۱ جمله>",
  "strengths": ["<قوت ۱>","<قوت ۲>"],
  "weaknesses": ["<ضعف ۱>","<ضعف ۲>"],
  "suggestions": ["<راهکار عملی ۱>","<راهکار عملی ۲>","<راهکار عملی ۳>"],
  "script_tip": "<یک جمله طلایی برای استفاده در تماس بعدی>",
  "follow_up": "<توصیه پیگیری>"
}}"""
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": ANTHROPIC_API_KEY,
                     "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model":"claude-sonnet-4-6","max_tokens":1000,
                  "messages":[{"role":"user","content":prompt}]}, timeout=30)
        text = r.json()["content"][0]["text"].replace("```json","").replace("```","").strip()
        return json.loads(text)
    except Exception as e:
        return {"score":50,"duration_analysis":"آنالیز در دسترس نیست",
                "strengths":["تماس برقرار شد"],"weaknesses":[f"خطا: {e}"],
                "suggestions":["API Key را بررسی کنید"],"script_tip":"-","follow_up":"-"}

# ── Telegram ────────────────────────────────────────────────────
def send_telegram(call_info, analysis):
    if not TELEGRAM_BOT_TOKEN: return
    score = analysis.get("score",0)
    em = "🟢" if score>=70 else "🟡" if score>=45 else "🔴"
    dur = call_info.get("duration",0)
    sug = "\n".join(f"  💡 {s}" for s in analysis.get("suggestions",[]))
    msg = f"""{em} <b>{call_info.get('seller_name','؟')}</b> | {dur//60}:{dur%60:02d} دقیقه | امتیاز <b>{score}/100</b>
📊 {analysis.get('duration_analysis','')}
<b>راهکارها:</b>
{sug}
💬 <i>"{analysis.get('script_tip','')}"</i>"""
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id":TELEGRAM_CHAT_ID,"text":msg,"parse_mode":"HTML"}, timeout=10)
    except: pass

# ── Email ───────────────────────────────────────────────────────
def send_email(call_info, analysis):
    if not EMAIL_FROM: return
    score = analysis.get("score",0)
    color = "#1D9E75" if score>=70 else "#BA7517" if score>=45 else "#E24B4A"
    dur = call_info.get("duration",0)
    sug_html = "".join(f"<li>{s}</li>" for s in analysis.get("suggestions",[]))
    html = f"""<div dir="rtl" style="font-family:Tahoma;max-width:600px;margin:auto;padding:20px">
<h2 style="border-bottom:3px solid {color};padding-bottom:10px">
گزارش تماس — {call_info.get('seller_name')}</h2>
<p>⏱ مدت: {dur//60}:{dur%60:02d} | 🏆 امتیاز: <strong style="color:{color}">{score}/100</strong></p>
<p>📊 {analysis.get('duration_analysis','')}</p>
<h3>💡 راهکارهای بهبود</h3><ul>{sug_html}</ul>
<div style="background:#e8f5e9;padding:12px;border-radius:8px;margin:12px 0">
💬 <em>"{analysis.get('script_tip','')}"</em></div>
<p>🔄 {analysis.get('follow_up','')}</p>
</div>"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"تماس {call_info.get('seller_name')} | امتیاز {score}/100"
        msg["From"] = EMAIL_FROM; msg["To"] = EMAIL_TO
        msg.attach(MIMEText(html,"html","utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com",465) as s:
            s.login(EMAIL_FROM, EMAIL_PASSWORD)
            s.sendmail(EMAIL_FROM, EMAIL_TO, msg.as_string())
    except: pass

# ── Webhook ─────────────────────────────────────────────────────
@app.route("/webhook/daftareshoma", methods=["POST"])
def webhook():
    secret = request.headers.get("X-Webhook-Secret","") or request.args.get("secret","")
    if WEBHOOK_SECRET and secret != WEBHOOK_SECRET:
        return jsonify({"error":"unauthorized"}), 401

    payload = request.json or {}
    event = payload.get("event","")
    if event not in ("Call.incoming.ended","Call.outgoing.ended"):
        return jsonify({"status":"ignored"}), 200

    cd = payload.get("data", payload)
    direction = "outgoing" if "outgoing" in event else "incoming"
    seller_name = (cd.get("agent_name") or cd.get("user_name") or
                   cd.get("extension_name") or cd.get("caller_name") or "نامشخص")
    customer_number = cd.get("caller_number") if direction=="incoming" else cd.get("callee_number","")
    duration = int(cd.get("duration",0) or cd.get("talk_time",0) or 0)
    ended_at = cd.get("ended_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    call_info = {
        "call_id": cd.get("call_id") or cd.get("id",""),
        "seller_name": seller_name,
        "seller_number": cd.get("extension",""),
        "customer_number": customer_number,
        "direction": direction,
        "duration": duration,
        "result": "پایان یافته",
        "started_at": cd.get("started_at",""),
        "ended_at": ended_at,
        "raw_payload": payload
    }

    # بلافاصله به SSE اطلاع بده که تماس شروع شد
    sse_broadcast({"type":"call_started","call": call_info})

    def process():
        analysis = analyze_with_claude(call_info)
        call_info.update({
            "ai_score": analysis.get("score"),
            "ai_duration_analysis": analysis.get("duration_analysis"),
            "ai_strengths":   json.dumps(analysis.get("strengths",[]),   ensure_ascii=False),
            "ai_weaknesses":  json.dumps(analysis.get("weaknesses",[]),  ensure_ascii=False),
            "ai_suggestions": json.dumps(analysis.get("suggestions",[]), ensure_ascii=False),
            "ai_script_tip":  analysis.get("script_tip",""),
            "ai_follow_up":   analysis.get("follow_up",""),
        })
        row_id = save_call(call_info)
        call_info["id"] = row_id
        call_info["analysis"] = analysis
        # broadcast کامل با آنالیز
        sse_broadcast({"type":"call_analyzed", "call": call_info,
                       "stats": get_stats()})
        send_telegram(call_info, analysis)
        send_email(call_info, analysis)

    threading.Thread(target=process, daemon=True).start()
    return jsonify({"status":"received"}), 200

# ── SSE endpoint ────────────────────────────────────────────────
@app.route("/sse")
def sse():
    q = queue.Queue(maxsize=50)
    with _sse_lock: _sse_clients.append(q)
    def stream():
        # heartbeat
        yield "data: {\"type\":\"ping\"}\n\n"
        try:
            while True:
                try: yield q.get(timeout=25)
                except queue.Empty: yield "data: {\"type\":\"ping\"}\n\n"
        except GeneratorExit:
            with _sse_lock:
                if q in _sse_clients: _sse_clients.remove(q)
    return Response(stream_with_context(stream()),
                    mimetype="text/event-stream",
                    headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

# ── API endpoints ───────────────────────────────────────────────
@app.route("/api/calls")
def api_calls():
    return jsonify(get_calls(request.args.get("date"), request.args.get("seller")))

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

@app.route("/health")
def health():
    return jsonify({"status":"ok"})

@app.route("/")
def dashboard():
    return render_template("dashboard.html")

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT",5000)), debug=False)
