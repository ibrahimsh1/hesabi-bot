"""
Hesabi Bot - Full Personal Accounting System
With persistent storage, CSV import/export
"""
import anthropic
import json
import sqlite3
import os
import re
import csv
from telegram.ext import Application, CommandHandler, MessageHandler, filters
from datetime import datetime

TOKEN = os.environ.get("TOKEN", "")
KEY = os.environ.get("KEY", "")
# Use Railway volume mount path, fallback to local
DB = os.environ.get("DB_PATH", "/data/hesabi.db")
# Ensure directory exists
os.makedirs(os.path.dirname(DB), exist_ok=True)

ai = anthropic.Anthropic(api_key=KEY)


# ============== DATABASE ==============
def init():
    c = sqlite3.connect(DB)
    c.execute("""CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        type TEXT,
        active INTEGER DEFAULT 1
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS journal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        description TEXT,
        debit_account TEXT,
        credit_account TEXT,
        amount REAL
    )""")
    count = c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    if count == 0:
        defaults = [
            ("نقد", "asset"), ("بنك", "asset"), ("استثمارات", "asset"),
            ("ذهب", "asset"), ("عقار", "asset"), ("سيارة", "asset"),
            ("قرض", "liability"), ("بطاقة ائتمان", "liability"),
            ("رأس المال", "equity"),
            ("راتب", "income"), ("دخل اضافي", "income"), ("ارباح استثمار", "income"),
            ("طعام وشراب", "expense"), ("مواصلات", "expense"), ("ايجار", "expense"),
            ("فواتير", "expense"), ("اشتراكات", "expense"), ("تسوق", "expense"),
            ("ترفيه", "expense"), ("صحة", "expense"), ("تعليم", "expense"),
            ("متفرقات", "expense"),
        ]
        c.executemany("INSERT INTO accounts (name, type) VALUES (?, ?)", defaults)
    c.commit()
    c.close()


def post_entry(date, desc, debit_acc, credit_acc, amount):
    c = sqlite3.connect(DB)
    c.execute("INSERT INTO journal (date, description, debit_account, credit_account, amount) VALUES (?, ?, ?, ?, ?)",
              (date, desc, debit_acc, credit_acc, amount))
    last_id = c.lastrowid
    c.commit()
    c.close()
    return last_id


def get_accounts():
    c = sqlite3.connect(DB)
    rows = c.execute("SELECT name, type FROM accounts WHERE active=1 ORDER BY type, name").fetchall()
    c.close()
    return rows


def account_exists(name):
    c = sqlite3.connect(DB)
    r = c.execute("SELECT type FROM accounts WHERE name=?", (name,)).fetchone()
    c.close()
    return r[0] if r else None


def get_balance(account):
    c = sqlite3.connect(DB)
    acc_type = c.execute("SELECT type FROM accounts WHERE name=?", (account,)).fetchone()
    if not acc_type:
        c.close()
        return 0
    acc_type = acc_type[0]
    debits = c.execute("SELECT COALESCE(SUM(amount), 0) FROM journal WHERE debit_account=?", (account,)).fetchone()[0]
    credits = c.execute("SELECT COALESCE(SUM(amount), 0) FROM journal WHERE credit_account=?", (account,)).fetchone()[0]
    c.close()
    if acc_type in ("asset", "expense"):
        return debits - credits
    return credits - debits


def get_totals_by_type():
    c = sqlite3.connect(DB)
    accounts = c.execute("SELECT name, type FROM accounts WHERE active=1").fetchall()
    c.close()
    totals = {"asset": 0, "liability": 0, "equity": 0, "income": 0, "expense": 0}
    by_account = {}
    for name, atype in accounts:
        bal = get_balance(name)
        totals[atype] += bal
        if abs(bal) > 0.01:
            by_account[name] = (atype, bal)
    return totals, by_account


# ============== COMMANDS ==============
async def start(u, c):
    await u.message.reply_text(
        "🏦 محاسبك الشخصي\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📝 معاملة طبيعية:\n"
        "  قهوة 18 | راتب 8000\n\n"
        "📊 التقارير:\n"
        "  /balance - الميزانية\n"
        "  /income - قائمة الدخل\n"
        "  /networth - صافي الثروة\n"
        "  /accounts - الحسابات\n"
        "  /last10 - آخر المعاملات\n\n"
        "💾 البيانات:\n"
        "  /export - تصدير CSV\n"
        "  /import - استيراد CSV\n\n"
        "🛠️ الإدارة:\n"
        "  /opening - رصيد افتتاحي\n"
        "  /delete - حذف معاملة\n"
        "  /reset - مسح الكل\n"
        "  /help - المساعدة"
    )


async def help_cmd(u, c):
    await u.message.reply_text(
        "📖 الدليل\n━━━━━━━━━━━━━━━\n\n"
        "💡 معاملات:\n"
        "  قهوة 18\n"
        "  راتب 8000\n"
        "  اشتريت ذهب 5000\n\n"
        "🔧 ادارة:\n"
        "  /opening نقد 5000\n"
        "  /delete 5\n"
        "  /reset confirm\n\n"
        "💾 ملفات:\n"
        "  /export ← يرسل CSV\n"
        "  /import ← ارفع CSV بعدها\n\n"
        "📋 صيغة الاستيراد:\n"
        "  date,description,debit,credit,amount\n"
        "  أو رصيد افتتاحي:\n"
        "  account,amount"
    )


async def cmd_accounts(u, c):
    accounts = get_accounts()
    by_type = {}
    for name, atype in accounts:
        by_type.setdefault(atype, []).append(name)
    labels = {"asset": "💰 الأصول", "liability": "💳 الخصوم",
              "equity": "📈 حقوق الملكية", "income": "💵 الدخل", "expense": "💸 المصاريف"}
    text = "🗂️ شجرة الحسابات\n━━━━━━━━━━━━━━━\n\n"
    for atype in ("asset", "liability", "equity", "income", "expense"):
        if atype in by_type:
            text += f"{labels[atype]}:\n"
            for name in by_type[atype]:
                bal = get_balance(name)
                text += f"  • {name}: {bal:,.0f}\n"
            text += "\n"
    await u.message.reply_text(text)


async def cmd_balance(u, c):
    totals, by_acc = get_totals_by_type()
    text = f"📋 الميزانية العمومية\n   {datetime.now().strftime('%Y-%m-%d')}\n━━━━━━━━━━━━━━━\n\n"
    text += "💰 الأصول:\n"
    assets_total = 0
    for name, (atype, bal) in by_acc.items():
        if atype == "asset":
            text += f"  {name}: {bal:,.0f}\n"
            assets_total += bal
    text += f"  ─────────\n  المجموع: {assets_total:,.0f}\n\n"
    text += "💳 الخصوم:\n"
    liab_total = 0
    for name, (atype, bal) in by_acc.items():
        if atype == "liability":
            text += f"  {name}: {bal:,.0f}\n"
            liab_total += bal
    if liab_total == 0:
        text += "  (لا يوجد)\n"
    text += f"  ─────────\n  المجموع: {liab_total:,.0f}\n\n"
    net_income = totals["income"] - totals["expense"]
    equity_total = totals["equity"] + net_income
    text += f"📈 حقوق الملكية:\n  رأس المال: {totals['equity']:,.0f}\n  الأرباح: {net_income:,.0f}\n"
    text += f"  ─────────\n  المجموع: {equity_total:,.0f}\n\n"
    text += f"━━━━━━━━━━━━━━━\n"
    text += f"الأصول: {assets_total:,.0f}\n"
    text += f"الخصوم + الملكية: {liab_total + equity_total:,.0f}\n"
    diff = assets_total - (liab_total + equity_total)
    text += f"✅ متوازنة" if abs(diff) < 0.01 else f"⚠️ فرق: {diff:,.0f}"
    await u.message.reply_text(text)


async def cmd_income(u, c):
    totals, by_acc = get_totals_by_type()
    text = f"📊 قائمة الدخل\n   {datetime.now().strftime('%Y-%m')}\n━━━━━━━━━━━━━━━\n\n"
    text += "💵 الإيرادات:\n"
    income_total = 0
    for name, (atype, bal) in by_acc.items():
        if atype == "income":
            text += f"  {name}: {bal:,.0f}\n"
            income_total += bal
    if income_total == 0:
        text += "  (لا يوجد)\n"
    text += f"  ─────────\n  مجموع الدخل: {income_total:,.0f}\n\n"
    text += "💸 المصاريف:\n"
    exp_total = 0
    for name, (atype, bal) in by_acc.items():
        if atype == "expense":
            text += f"  {name}: {bal:,.0f}\n"
            exp_total += bal
    if exp_total == 0:
        text += "  (لا يوجد)\n"
    text += f"  ─────────\n  مجموع المصاريف: {exp_total:,.0f}\n\n"
    text += "━━━━━━━━━━━━━━━\n"
    net = income_total - exp_total
    text += f"✅ صافي الربح: {net:,.0f}" if net >= 0 else f"⚠️ صافي الخسارة: {abs(net):,.0f}"
    await u.message.reply_text(text)


async def cmd_networth(u, c):
    totals, _ = get_totals_by_type()
    net_worth = totals["asset"] - totals["liability"]
    text = f"💎 صافي الثروة\n━━━━━━━━━━━━━━━\n"
    text += f"الأصول:  {totals['asset']:>12,.0f}\n"
    text += f"الخصوم:  {totals['liability']:>12,.0f}\n"
    text += f"━━━━━━━━━━━━━━━\n"
    text += f"الصافي:  {net_worth:>12,.0f} ريال"
    await u.message.reply_text(text)


async def cmd_last10(u, c):
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT id, date, description, debit_account, credit_account, amount FROM journal ORDER BY id DESC LIMIT 10").fetchall()
    conn.close()
    if not rows:
        await u.message.reply_text("ما في معاملات")
        return
    text = "📜 آخر 10 معاملات\n━━━━━━━━━━━━━━━\n\n"
    for r in rows:
        text += f"🔢 #{r[0]} | 📅 {r[1]}\n   {r[2]}\n   {r[4]} → {r[3]}\n   💰 {r[5]:,.0f}\n\n"
    text += "💡 /delete <رقم>"
    await u.message.reply_text(text)


async def cmd_opening(u, c):
    args = u.message.text.split(maxsplit=2)
    if len(args) < 3:
        await u.message.reply_text(
            "📌 رصيد افتتاحي\n\n"
            "/opening <الحساب> <المبلغ>\n\n"
            "أمثلة:\n"
            "/opening نقد 5000\n"
            "/opening بنك 50000\n"
            "/opening قرض 30000"
        )
        return
    account = args[1]
    try:
        amount = float(args[2])
    except ValueError:
        await u.message.reply_text("⚠️ المبلغ غير صحيح")
        return
    atype = account_exists(account)
    if not atype:
        await u.message.reply_text(f"⚠️ حساب '{account}' غير موجود")
        return
    today = datetime.now().strftime("%Y-%m-%d")
    desc = f"رصيد افتتاحي - {account}"
    if atype == "asset":
        post_entry(today, desc, account, "رأس المال", amount)
    elif atype == "liability":
        post_entry(today, desc, "رأس المال", account, amount)
    else:
        await u.message.reply_text("⚠️ للأصول والخصوم فقط")
        return
    new_bal = get_balance(account)
    await u.message.reply_text(f"✅ تم\n{account}: {new_bal:,.0f}")


async def cmd_delete(u, c):
    args = u.message.text.split()
    if len(args) < 2:
        await u.message.reply_text("/delete <رقم>\nشوف الأرقام: /last10")
        return
    try:
        entry_id = int(args[1])
    except ValueError:
        await u.message.reply_text("⚠️ رقم غير صحيح")
        return
    conn = sqlite3.connect(DB)
    row = conn.execute("SELECT date, description, amount FROM journal WHERE id=?", (entry_id,)).fetchone()
    if not row:
        conn.close()
        await u.message.reply_text(f"⚠️ المعاملة {entry_id} غير موجودة")
        return
    conn.execute("DELETE FROM journal WHERE id=?", (entry_id,))
    conn.commit()
    conn.close()
    await u.message.reply_text(f"🗑️ تم حذف #{entry_id}\n{row[1]} - {row[2]:,.0f}")


async def cmd_reset(u, c):
    args = u.message.text.split()
    if len(args) < 2 or args[1] != "confirm":
        await u.message.reply_text("⚠️ سيُمسح كل شيء!\nللتأكيد: /reset confirm")
        return
    conn = sqlite3.connect(DB)
    count = conn.execute("SELECT COUNT(*) FROM journal").fetchone()[0]
    conn.execute("DELETE FROM journal")
    conn.commit()
    conn.close()
    await u.message.reply_text(f"🧹 تم مسح {count} معاملة")


async def cmd_addaccount(u, c):
    args = u.message.text.split(maxsplit=2)
    if len(args) < 3:
        await u.message.reply_text(
            "/addaccount <النوع> <الاسم>\n"
            "الأنواع: asset, liability, equity, income, expense"
        )
        return
    atype = args[1].lower()
    name = args[2]
    if atype not in ("asset", "liability", "equity", "income", "expense"):
        await u.message.reply_text("نوع غير صحيح")
        return
    try:
        conn = sqlite3.connect(DB)
        conn.execute("INSERT INTO accounts (name, type) VALUES (?, ?)", (name, atype))
        conn.commit()
        conn.close()
        await u.message.reply_text(f"✅ تم اضافة: {name}")
    except sqlite3.IntegrityError:
        await u.message.reply_text("⚠️ موجود")


async def cmd_export(u, c):
    """Export all journal entries as CSV"""
    conn = sqlite3.connect(DB)
    rows = conn.execute("SELECT id, date, description, debit_account, credit_account, amount FROM journal ORDER BY date, id").fetchall()
    accounts = conn.execute("SELECT name, type FROM accounts").fetchall()
    conn.close()
    
    if not rows:
        await u.message.reply_text("ما في بيانات للتصدير")
        return
    
    # Journal CSV
    path = "/tmp/hesabi_export.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "date", "description", "debit_account", "credit_account", "amount"])
        for r in rows:
            writer.writerow(r)
    
    # Accounts summary
    path2 = "/tmp/hesabi_accounts.csv"
    with open(path2, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["account", "type", "balance"])
        for name, atype in accounts:
            bal = get_balance(name)
            if abs(bal) > 0.01:
                writer.writerow([name, atype, f"{bal:.2f}"])
    
    await u.message.reply_text(f"📤 جاري تصدير {len(rows)} معاملة...")
    await u.message.reply_document(document=open(path, "rb"), filename="hesabi_journal.csv", caption="📒 دفتر اليومية")
    await u.message.reply_document(document=open(path2, "rb"), filename="hesabi_accounts.csv", caption="📊 الحسابات والأرصدة")


async def cmd_import(u, c):
    """Instructions for import"""
    await u.message.reply_text(
        "📥 الاستيراد\n━━━━━━━━━━━━━━━\n\n"
        "ارفع ملف CSV بإحدى الصيغتين:\n\n"
        "1️⃣ أرصدة افتتاحية (عمودين):\n"
        "account,amount\n"
        "نقد,5000\n"
        "بنك,50000\n\n"
        "2️⃣ معاملات كاملة (5 أعمدة):\n"
        "date,description,debit,credit,amount\n"
        "2026-05-18,قهوة,طعام وشراب,نقد,18\n\n"
        "💡 فقط ارفع الملف وبيشتغل تلقائياً"
    )


async def handle_document(u, c):
    """Handle uploaded CSV files for import"""
    doc = u.message.document
    if not doc.file_name.lower().endswith('.csv'):
        await u.message.reply_text("⚠️ ارفع ملف CSV فقط")
        return
    
    file = await doc.get_file()
    path = "/tmp/import.csv"
    await file.download_to_drive(path)
    
    await u.message.reply_text("📥 جاري الاستيراد...")
    
    today = datetime.now().strftime("%Y-%m-%d")
    success = 0
    errors = []
    
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            reader = csv.reader(f)
            rows = list(reader)
        
        if not rows:
            await u.message.reply_text("⚠️ الملف فاضي")
            return
        
        # Detect format by header or column count
        header = rows[0]
        data = rows[1:] if any(c.lower() in ('id', 'date', 'account', 'description') for c in header) else rows
        
        for i, row in enumerate(data, start=2):
            try:
                if len(row) == 2:
                    # Opening balance format: account, amount
                    account = row[0].strip()
                    amount = float(row[1].strip())
                    atype = account_exists(account)
                    if not atype:
                        errors.append(f"سطر {i}: حساب '{account}' غير موجود")
                        continue
                    desc = f"رصيد افتتاحي - {account}"
                    if atype == "asset":
                        post_entry(today, desc, account, "رأس المال", amount)
                    elif atype == "liability":
                        post_entry(today, desc, "رأس المال", account, amount)
                    else:
                        errors.append(f"سطر {i}: '{account}' ليس أصل/خصم")
                        continue
                    success += 1
                
                elif len(row) >= 5:
                    # Full format: [id?], date, description, debit, credit, amount
                    if len(row) == 6:  # has id column
                        date, desc, debit, credit, amount = row[1], row[2], row[3], row[4], row[5]
                    else:  # no id
                        date, desc, debit, credit, amount = row[0], row[1], row[2], row[3], row[4]
                    
                    if not account_exists(debit.strip()):
                        errors.append(f"سطر {i}: حساب مدين '{debit}' غير موجود")
                        continue
                    if not account_exists(credit.strip()):
                        errors.append(f"سطر {i}: حساب دائن '{credit}' غير موجود")
                        continue
                    
                    post_entry(date.strip(), desc.strip(), debit.strip(), credit.strip(), float(amount))
                    success += 1
                else:
                    errors.append(f"سطر {i}: صيغة غير صحيحة")
            except Exception as e:
                errors.append(f"سطر {i}: {str(e)[:30]}")
        
        msg = f"✅ تم استيراد {success} سجل"
        if errors:
            msg += f"\n\n⚠️ {len(errors)} خطأ:\n" + "\n".join(errors[:10])
        await u.message.reply_text(msg)
        
    except Exception as e:
        await u.message.reply_text(f"⚠️ خطأ: {str(e)[:100]}")


# ============== AI PROCESSING ==============
async def process(u, c):
    msg = u.message.text.strip()
    today = datetime.now().strftime("%Y-%m-%d")
    
    if len(msg) < 3:
        await u.message.reply_text("ارسل وصف اوضح")
        return
    if not re.search(r'\d+', msg):
        await u.message.reply_text("❌ بدون مبلغ\nمثال: قهوة 18")
        return
    
    await u.message.reply_text("🔄 جاري التسجيل...")
    accounts = get_accounts()
    accounts_text = "\n".join([f"- {name} ({atype})" for name, atype in accounts])
    
    try:
        r = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=f'''Saudi personal accounting with DOUBLE-ENTRY.
TODAY: {today}

ACCOUNTS:
{accounts_text}

RULES:
- Assets ↑ DEBIT | Liabilities ↑ CREDIT
- Income = CREDIT | Expense = DEBIT

PATTERNS:
1. Expense small (<500): debit=expense, credit=نقد
2. Expense large (>500): debit=expense, credit=بنك
3. Salary: debit=بنك, credit=راتب
4. Buy asset: debit=asset, credit=نقد or بنك
5. Loan: debit=نقد, credit=قرض
6. Pay loan: debit=قرض, credit=نقد

Reply ONLY JSON:
Transaction: {{"description":"وصف","debit_account":"name","credit_account":"name","amount":number}}
Unclear: {{"needs_clarification":true,"reason":"السبب"}}
Not transaction: {{"not_transaction":true,"reply":"رد"}}

Use EXACT account names.''',
            messages=[{"role": "user", "content": msg}]
        )
        raw = r.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        d = json.loads(raw)
        
        if d.get("not_transaction"):
            await u.message.reply_text(d.get("reply", "مو معاملة"))
            return
        if d.get("needs_clarification"):
            await u.message.reply_text(f"❓ {d.get('reason')}")
            return
        if not account_exists(d["debit_account"]) or not account_exists(d["credit_account"]):
            await u.message.reply_text(f"⚠️ حساب غير موجود\nمدين: {d['debit_account']}\nدائن: {d['credit_account']}")
            return
        
        entry_id = post_entry(today, d["description"], d["debit_account"], d["credit_account"], d["amount"])
        await u.message.reply_text(
            f"✅ #{entry_id}\n━━━━━━━━━━━━━━━\n"
            f"📅 {today}\n📝 {d['description']}\n💰 {d['amount']:,.0f}\n\n"
            f"⬆️ مدين: {d['debit_account']}\n⬇️ دائن: {d['credit_account']}"
        )
    except json.JSONDecodeError:
        await u.message.reply_text("⚠️ ما فهمت، حاول أوضح")
    except Exception as e:
        await u.message.reply_text("⚠️ خطأ تقني")
        print(f"Error: {e}")


def main():
    init()
    print("Bot running with volume support!")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("accounts", cmd_accounts))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("income", cmd_income))
    app.add_handler(CommandHandler("networth", cmd_networth))
    app.add_handler(CommandHandler("last10", cmd_last10))
    app.add_handler(CommandHandler("opening", cmd_opening))
    app.add_handler(CommandHandler("delete", cmd_delete))
    app.add_handler(CommandHandler("reset", cmd_reset))
    app.add_handler(CommandHandler("addaccount", cmd_addaccount))
    app.add_handler(CommandHandler("export", cmd_export))
    app.add_handler(CommandHandler("import", cmd_import))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process))
    app.run_polling()


if __name__ == "__main__":
    main()
