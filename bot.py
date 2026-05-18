import anthropic
import json
import sqlite3
import os
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from datetime import datetime

TOKEN = os.environ.get("TOKEN", "")
KEY = os.environ.get("KEY", "")
DB = "hesabi.db"
ai = anthropic.Anthropic(api_key=KEY)

def init():
    c = sqlite3.connect(DB)
    c.execute("CREATE TABLE IF NOT EXISTS t (id INTEGER PRIMARY KEY AUTOINCREMENT, date TEXT, description TEXT, category TEXT, type TEXT, amount REAL)")
    c.commit()
    c.close()

def save(d):
    c = sqlite3.connect(DB)
    c.execute("INSERT INTO t VALUES (NULL,?,?,?,?,?)",
        (d["date"], d["description"], d["category"], d["type"], d["amount"]))
    c.commit()
    c.close()

async def start(u, c):
    await u.message.reply_text("Bot ready!\nSend: coffee 18\nCommands:\n/last10\n/report")

async def last10(u, c):
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT date,description,amount FROM t ORDER BY id DESC LIMIT 10").fetchall()
    conn.close()
    if not rows:
        await u.message.reply_text("no data yet")
        return
    await u.message.reply_text("\n".join(f"{r[0]} | {r[1]} | {r[2]:.0f}" for r in rows))

async def report(u, c):
    m = datetime.now().strftime("%Y-%m")
    conn = sqlite3.connect(DB)
    rows = dict(conn.execute(
        "SELECT type,SUM(amount) FROM t WHERE date LIKE ? GROUP BY type",
        (m+"%",)).fetchall())
    conn.close()
    if not rows:
        await u.message.reply_text("no data this month")
        return
    inc = rows.get("income", 0)
    exp = sum(v for k, v in rows.items() if k not in ("income", "saving"))
    sav = rows.get("saving", 0)
    await u.message.reply_text(
        f"Report {m}\n"
        f"income:  {inc:,.0f}\n"
        f"expense: {exp:,.0f}\n"
        f"saving:  {sav:,.0f}\n"
        f"net:     {inc-exp-sav:,.0f}")

async def process(u, c):
    msg = u.message.text
    await u.message.reply_text("classifying...")
    try:
        r = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=200,
            system='Reply ONLY with valid JSON: {"date":"YYYY-MM-DD","description":"desc","category":"cat","type":"income or fixed_expense or variable_expense or saving","amount":0} Use today date.',
            messages=[{"role": "user", "content": msg}]
        )
        raw = r.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        d = json.loads(raw)
        save(d)
        await u.message.reply_text(
            f"Saved!\n"
            f"Date: {d['date']}\n"
            f"Desc: {d['description']}\n"
            f"Cat:  {d['category']}\n"
            f"Amt:  {d['amount']:,.0f}")
    except Exception as e:
        await u.message.reply_text(f"error: {e}")

def main():
    init()
    print("Bot running!")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("last10", last10))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process))
    app.run_polling()

if __name__ == "__main__":
    main()
