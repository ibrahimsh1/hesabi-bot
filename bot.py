import anthropic
import json
import sqlite3
import os
import re
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

def has_number(msg):
    """Check if message contains a number"""
    return bool(re.search(r'\d+', msg))

async def start(u, c):
    await u.message.reply_text(
        "اهلا! انا محاسبك الشخصي\n\n"
        "ارسل لي معاملاتك المالية بشكل طبيعي مثل:\n"
        "• قهوة 18\n"
        "• استلمت راتب 8000\n"
        "• دفعت ايجار 3500\n"
        "• بنزين 200\n\n"
        "الاوامر:\n"
        "/last10 - آخر 10 معاملات\n"
        "/report - تقرير الشهر\n"
        "/help - المساعدة"
    )

async def help_cmd(u, c):
    await u.message.reply_text(
        "كيف استخدمني:\n\n"
        "1. لاضافة معاملة، اكتبها مع المبلغ:\n"
        "   مثال: قهوة 18\n"
        "   مثال: راتب الشهر 8000\n\n"
        "2. اوامر التقارير:\n"
        "   /last10 - آخر المعاملات\n"
        "   /report - ملخص الشهر\n\n"
        "نصيحة: كل ما كان وصفك واضح، كان التصنيف ادق"
    )

async def last10(u, c):
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT date,description,amount FROM t ORDER BY id DESC LIMIT 10").fetchall()
    conn.close()
    if not rows:
        await u.message.reply_text("ما في معاملات بعد")
        return
    await u.message.reply_text("آخر المعاملات:\n\n" + "\n".join(f"{r[0]} | {r[1]} | {r[2]:,.0f}" for r in rows))

async def report(u, c):
    m = datetime.now().strftime("%Y-%m")
    conn = sqlite3.connect(DB)
    rows = dict(conn.execute(
        "SELECT type,SUM(amount) FROM t WHERE date LIKE ? GROUP BY type",
        (m+"%",)).fetchall())
    conn.close()
    if not rows:
        await u.message.reply_text("ما في بيانات هذا الشهر")
        return
    inc = rows.get("income", 0)
    exp = sum(v for k, v in rows.items() if k not in ("income", "saving"))
    sav = rows.get("saving", 0)
    await u.message.reply_text(
        f"تقرير {m}\n"
        f"━━━━━━━━━━━━\n"
        f"الدخل:    {inc:>10,.0f}\n"
        f"المصاريف: {exp:>10,.0f}\n"
        f"الادخار:  {sav:>10,.0f}\n"
        f"━━━━━━━━━━━━\n"
        f"الصافي:   {inc-exp-sav:>10,.0f}")

async def process(u, c):
    msg = u.message.text.strip()
    
    # رسائل قصيرة جداً
    if len(msg) < 3:
        await u.message.reply_text("ارسل وصف اوضح مثل: قهوة 18")
        return
    
    # رسائل بدون ارقام = مو معاملة
    if not has_number(msg):
        await u.message.reply_text(
            "ما حسبت هذه معاملة لانها بدون مبلغ\n\n"
            "للاضافة اكتب: الوصف + المبلغ\n"
            "مثال: قهوة 18\n\n"
            "للمساعدة: /help"
        )
        return
    
    await u.message.reply_text("جاري التصنيف...")
    
    try:
        r = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system='''You are a Saudi personal finance assistant. The user sends transactions in Arabic.

Rules:
1. If the message is clearly a financial transaction with amount, extract it.
2. If amount is missing or unclear, set "needs_clarification" to true.
3. If it is greeting/question/not a transaction, set "not_transaction" to true.

Reply ONLY with valid JSON in one of these formats:

For valid transaction:
{"date":"YYYY-MM-DD","description":"وصف بالعربي","category":"الفئة بالعربي","type":"income or fixed_expense or variable_expense or saving","amount":number}

For unclear/missing info:
{"needs_clarification":true,"reason":"reason in arabic"}

For non-transaction:
{"not_transaction":true,"reply":"polite reply in arabic"}

Categories (use one): راتب, دخل اضافي, ايجار, فواتير, اشتراكات, طعام وشراب, مواصلات, تسوق, ترفيه, صحة, تعليم, ادخار, متفرقات

Use today date. Be smart about Arabic descriptions.''',
            messages=[{"role": "user", "content": msg}]
        )
        raw = r.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        d = json.loads(raw)
        
        # رسالة مو معاملة
        if d.get("not_transaction"):
            await u.message.reply_text(d.get("reply", "هذي مو معاملة مالية"))
            return
        
        # تحتاج توضيح
        if d.get("needs_clarification"):
            await u.message.reply_text(
                f"محتاج توضيح: {d.get('reason', 'الرسالة غير واضحة')}\n\n"
                f"مثال: قهوة 18 ريال"
            )
            return
        
        # معاملة صحيحة
        save(d)
        type_ar = {
            "income": "دخل",
            "fixed_expense": "مصروف ثابت",
            "variable_expense": "مصروف متغير",
            "saving": "ادخار"
        }.get(d.get("type", ""), d.get("type", ""))
        
        await u.message.reply_text(
            f"تم الحفظ\n"
            f"━━━━━━━━━━━━\n"
            f"التاريخ: {d['date']}\n"
            f"الوصف:  {d['description']}\n"
            f"الفئة:   {d['category']}\n"
            f"النوع:   {type_ar}\n"
            f"المبلغ:  {d['amount']:,.0f} ريال"
        )
    except json.JSONDecodeError:
        await u.message.reply_text("ما قدرت اقرا الرد، حاول بصيغة اوضح\nمثال: قهوة 18")
    except Exception as e:
        await u.message.reply_text(f"خطا تقني، حاول مرة ثانية")
        print(f"Error: {e}")

def main():
    init()
    print("Bot running on Railway!")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("last10", last10))
    app.add_handler(CommandHandler("report", report))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process))
    app.run_polling()

if __name__ == "__main__":
    main()
