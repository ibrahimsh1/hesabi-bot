"""
Hesabi Bot - Full Personal Accounting System
- Double-entry bookkeeping
- Assets, Liabilities, Equity, Income, Expenses
- Balance Sheet, Income Statement, Cash Flow
- Opening balances, Delete, Reset
"""
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
            ("نقد", "asset"),
            ("بنك", "asset"),
            ("استثمارات", "asset"),
            ("ذهب", "asset"),
            ("عقار", "asset"),
            ("سيارة", "asset"),
            ("قرض", "liability"),
            ("بطاقة ائتمان", "liability"),
            ("رأس المال", "equity"),
            ("راتب", "income"),
            ("دخل اضافي", "income"),
            ("ارباح استثمار", "income"),
            ("طعام وشراب", "expense"),
            ("مواصلات", "expense"),
            ("ايجار", "expense"),
            ("فواتير", "expense"),
            ("اشتراكات", "expense"),
            ("تسوق", "expense"),
            ("ترفيه", "expense"),
            ("صحة", "expense"),
            ("تعليم", "expense"),
            ("متفرقات", "expense"),
        ]
        c.executemany("INSERT INTO accounts (name, type) VALUES (?, ?)", defaults)
    c.commit()
    c.close()


def post_entry(date, desc, debit_acc, credit_acc, amount):
    c = sqlite3.connect(DB)
    c.execute(
        "INSERT INTO journal (date, description, debit_account, credit_account, amount) VALUES (?, ?, ?, ?, ?)",
        (date, desc, debit_acc, credit_acc, amount)
    )
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
    else:
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


# ============== HANDLERS ==============
async def start(u, c):
    await u.message.reply_text(
        "🏦 محاسبك الشخصي\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📝 لاضافة معاملة، اكتبها طبيعي:\n"
        "  • قهوة 18\n"
        "  • راتب 8000\n"
        "  • اشتريت ذهب 5000\n\n"
        "📊 التقارير:\n"
        "  /balance - الميزانية العمومية\n"
        "  /income - قائمة الدخل\n"
        "  /networth - صافي الثروة\n"
        "  /accounts - شجرة الحسابات\n"
        "  /last10 - آخر المعاملات\n\n"
        "🛠️ الإدارة:\n"
        "  /opening - رصيد افتتاحي\n"
        "  /delete - حذف معاملة\n"
        "  /reset - مسح الكل\n"
        "  /addaccount - حساب جديد\n"
        "  /help - المساعدة"
    )


async def help_cmd(u, c):
    await u.message.reply_text(
        "📖 الدليل الكامل\n"
        "━━━━━━━━━━━━━━━\n\n"
        "💡 المعاملات:\n"
        "  قهوة 18\n"
        "  راتب 8000\n"
        "  اشتريت اسهم 5000\n"
        "  حولت 1000 للبنك\n"
        "  اخذت قرض 10000\n\n"
        "🔧 إدارة الأرصدة:\n\n"
        "/opening <الحساب> <المبلغ>\n"
        "  مثال: /opening نقد 5000\n"
        "  مثال: /opening بنك 50000\n\n"
        "/delete <رقم_المعاملة>\n"
        "  مثال: /delete 5\n"
        "  (شوف الأرقام من /last10)\n\n"
        "/reset\n"
        "  يمسح كل المعاملات (احذر!)"
    )


async def cmd_accounts(u, c):
    accounts = get_accounts()
    by_type = {}
    for name, atype in accounts:
        by_type.setdefault(atype, []).append(name)
    labels = {
        "asset": "💰 الأصول",
        "liability": "💳 الخصوم",
        "equity": "📈 حقوق الملكية",
        "income": "💵 الدخل",
        "expense": "💸 المصاريف"
    }
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
    text = "📋 الميزانية العمومية\n"
    text += f"   {datetime.now().strftime('%Y-%m-%d')}\n"
    text += "━━━━━━━━━━━━━━━\n\n"
    text += "💰 الأصول:\n"
    assets_total = 0
    for name, (atype, bal) in by_acc.items():
        if atype == "asset":
            text += f"  {name}: {bal:,.0f}\n"
            assets_total += bal
    text += f"  ─────────\n"
    text += f"  المجموع: {assets_total:,.0f}\n\n"
    text += "💳 الخصوم:\n"
    liab_total = 0
    for name, (atype, bal) in by_acc.items():
        if atype == "liability":
            text += f"  {name}: {bal:,.0f}\n"
            liab_total += bal
    if liab_total == 0:
        text += "  (لا يوجد)\n"
    text += f"  ─────────\n"
    text += f"  المجموع: {liab_total:,.0f}\n\n"
    net_income = totals["income"] - totals["expense"]
    equity_total = totals["equity"] + net_income
    text += "📈 حقوق الملكية:\n"
    text += f"  رأس المال: {totals['equity']:,.0f}\n"
    text += f"  الأرباح المحتجزة: {net_income:,.0f}\n"
    text += f"  ─────────\n"
    text += f"  المجموع: {equity_total:,.0f}\n\n"
    text += "━━━━━━━━━━━━━━━\n"
    text += f"إجمالي الأصول: {assets_total:,.0f}\n"
    text += f"إجمالي الخصوم + حقوق الملكية: {liab_total + equity_total:,.0f}\n"
    diff = assets_total - (liab_total + equity_total)
    if abs(diff) > 0.01:
        text += f"⚠️ فرق: {diff:,.0f}"
    else:
        text += "✅ متوازنة"
    await u.message.reply_text(text)


async def cmd_income(u, c):
    totals, by_acc = get_totals_by_type()
    text = "📊 قائمة الدخل\n"
    text += f"   {datetime.now().strftime('%Y-%m')}\n"
    text += "━━━━━━━━━━━━━━━\n\n"
    text += "💵 الإيرادات:\n"
    income_total = 0
    for name, (atype, bal) in by_acc.items():
        if atype == "income":
            text += f"  {name}: {bal:,.0f}\n"
            income_total += bal
    if income_total == 0:
        text += "  (لا يوجد)\n"
    text += f"  ─────────\n"
    text += f"  مجموع الدخل: {income_total:,.0f}\n\n"
    text += "💸 المصاريف:\n"
    exp_total = 0
    for name, (atype, bal) in by_acc.items():
        if atype == "expense":
            text += f"  {name}: {bal:,.0f}\n"
            exp_total += bal
    if exp_total == 0:
        text += "  (لا يوجد)\n"
    text += f"  ─────────\n"
    text += f"  مجموع المصاريف: {exp_total:,.0f}\n\n"
    text += "━━━━━━━━━━━━━━━\n"
    net = income_total - exp_total
    if net >= 0:
        text += f"✅ صافي الربح: {net:,.0f}"
    else:
        text += f"⚠️ صافي الخسارة: {abs(net):,.0f}"
    await u.message.reply_text(text)


async def cmd_networth(u, c):
    totals, _ = get_totals_by_type()
    net_worth = totals["asset"] - totals["liability"]
    text = "💎 صافي الثروة\n"
    text += "━━━━━━━━━━━━━━━\n"
    text += f"الأصول:  {totals['asset']:>12,.0f}\n"
    text += f"الخصوم:  {totals['liability']:>12,.0f}\n"
    text += "━━━━━━━━━━━━━━━\n"
    text += f"الصافي:  {net_worth:>12,.0f} ريال"
    await u.message.reply_text(text)


async def cmd_last10(u, c):
    conn = sqlite3.connect(DB)
    rows = conn.execute(
        "SELECT id, date, description, debit_account, credit_account, amount FROM journal ORDER BY id DESC LIMIT 10"
    ).fetchall()
    conn.close()
    if not rows:
        await u.message.reply_text("ما في معاملات بعد")
        return
    text = "📜 آخر 10 معاملات\n━━━━━━━━━━━━━━━\n\n"
    for r in rows:
        text += f"🔢 #{r[0]} | 📅 {r[1]}\n"
        text += f"   {r[2]}\n"
        text += f"   من: {r[4]} → الى: {r[3]}\n"
        text += f"   💰 {r[5]:,.0f}\n\n"
    text += "💡 لحذف معاملة: /delete <الرقم>"
    await u.message.reply_text(text)


async def cmd_opening(u, c):
    args = u.message.text.split(maxsplit=2)
    if len(args) < 3:
        await u.message.reply_text(
            "📌 رصيد افتتاحي\n\n"
            "الاستخدام:\n"
            "/opening <اسم الحساب> <المبلغ>\n\n"
            "أمثلة:\n"
            "/opening نقد 5000\n"
            "/opening بنك 50000\n"
            "/opening قرض 30000\n\n"
            "🔍 شوف الحسابات: /accounts"
        )
        return
    
    account = args[1]
    try:
        amount = float(args[2])
    except ValueError:
        await u.message.reply_text("⚠️ المبلغ يجب أن يكون رقماً")
        return
    
    atype = account_exists(account)
    if not atype:
        await u.message.reply_text(f"⚠️ حساب '{account}' غير موجود\n\nشوف الحسابات: /accounts")
        return
    
    today = datetime.now().strftime("%Y-%m-%d")
    desc = f"رصيد افتتاحي - {account}"
    
    # Logic: for assets, debit account / credit equity
    # For liabilities, debit equity / credit account
    if atype == "asset":
        post_entry(today, desc, account, "رأس المال", amount)
    elif atype == "liability":
        post_entry(today, desc, "رأس المال", account, amount)
    else:
        await u.message.reply_text("⚠️ الرصيد الافتتاحي للأصول والخصوم فقط")
        return
    
    new_bal = get_balance(account)
    await u.message.reply_text(
        f"✅ تم تسجيل الرصيد الافتتاحي\n"
        f"━━━━━━━━━━━━━━━\n"
        f"الحساب: {account}\n"
        f"المبلغ: {amount:,.0f}\n"
        f"الرصيد الجديد: {new_bal:,.0f}"
    )


async def cmd_delete(u, c):
    args = u.message.text.split()
    if len(args) < 2:
        await u.message.reply_text(
            "📌 حذف معاملة\n\n"
            "الاستخدام:\n"
            "/delete <رقم المعاملة>\n\n"
            "مثال: /delete 5\n\n"
            "🔍 شوف الأرقام: /last10"
        )
        return
    
    try:
        entry_id = int(args[1])
    except ValueError:
        await u.message.reply_text("⚠️ الرقم غير صحيح")
        return
    
    conn = sqlite3.connect(DB)
    row = conn.execute(
        "SELECT date, description, debit_account, credit_account, amount FROM journal WHERE id=?",
        (entry_id,)
    ).fetchone()
    
    if not row:
        conn.close()
        await u.message.reply_text(f"⚠️ لا توجد معاملة برقم {entry_id}")
        return
    
    conn.execute("DELETE FROM journal WHERE id=?", (entry_id,))
    conn.commit()
    conn.close()
    
    await u.message.reply_text(
        f"🗑️ تم حذف المعاملة\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔢 #{entry_id}\n"
        f"📅 {row[0]}\n"
        f"📝 {row[1]}\n"
        f"💰 {row[4]:,.0f}"
    )


async def cmd_reset(u, c):
    args = u.message.text.split()
    if len(args) < 2 or args[1] != "confirm":
        await u.message.reply_text(
            "⚠️ تحذير: سيتم مسح كل المعاملات!\n"
            "━━━━━━━━━━━━━━━\n\n"
            "هل أنت متأكد؟\n\n"
            "للتأكيد اكتب:\n"
            "/reset confirm"
        )
        return
    
    conn = sqlite3.connect(DB)
    count = conn.execute("SELECT COUNT(*) FROM journal").fetchone()[0]
    conn.execute("DELETE FROM journal")
    conn.commit()
    conn.close()
    
    await u.message.reply_text(
        f"🧹 تم مسح {count} معاملة\n\n"
        f"💡 ابدأ بتسجيل أرصدتك الافتتاحية:\n"
        f"/opening نقد <المبلغ>\n"
        f"/opening بنك <المبلغ>"
    )


async def cmd_addaccount(u, c):
    args = u.message.text.split(maxsplit=2)
    if len(args) < 3:
        await u.message.reply_text(
            "الاستخدام:\n"
            "/addaccount <النوع> <الاسم>\n\n"
            "الأنواع: asset, liability, equity, income, expense\n\n"
            "مثال:\n"
            "/addaccount asset محفظة الجيب"
        )
        return
    atype = args[1].lower()
    name = args[2]
    if atype not in ("asset", "liability", "equity", "income", "expense"):
        await u.message.reply_text("النوع غير صحيح")
        return
    try:
        conn = sqlite3.connect(DB)
        conn.execute("INSERT INTO accounts (name, type) VALUES (?, ?)", (name, atype))
        conn.commit()
        conn.close()
        await u.message.reply_text(f"✅ تم اضافة: {name} ({atype})")
    except sqlite3.IntegrityError:
        await u.message.reply_text("⚠️ الحساب موجود")


# ============== AI PROCESSING ==============
async def process(u, c):
    msg = u.message.text.strip()
    today = datetime.now().strftime("%Y-%m-%d")
    
    if len(msg) < 3:
        await u.message.reply_text("ارسل وصف اوضح")
        return
    
    if not re.search(r'\d+', msg):
        await u.message.reply_text(
            "❌ بدون مبلغ\n\n"
            "مثال: قهوة 18"
        )
        return
    
    await u.message.reply_text("🔄 جاري التسجيل...")
    
    accounts = get_accounts()
    accounts_text = "\n".join([f"- {name} ({atype})" for name, atype in accounts])
    
    try:
        r = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=f'''Saudi personal accounting with DOUBLE-ENTRY bookkeeping.
TODAY: {today}

ACCOUNTS:
{accounts_text}

DOUBLE ENTRY RULES:
- Assets ↑ DEBIT, Assets ↓ CREDIT
- Liabilities ↑ CREDIT, Liabilities ↓ DEBIT
- Income = CREDIT, Expenses = DEBIT, Equity = CREDIT

PATTERNS:
1. Expense in cash: debit=expense_account, credit=نقد
2. Expense from bank: debit=expense_account, credit=بنك
3. Salary: debit=بنك, credit=راتب
4. Buy investment: debit=استثمارات, credit=نقد or بنك
5. Transfer: debit=destination, credit=source
6. Take loan: debit=نقد, credit=قرض
7. Pay loan: debit=قرض, credit=نقد

DEFAULT: If user doesn't specify source, assume بنك for amounts > 500, نقد for smaller.

Reply ONLY with JSON:
For transaction: {{"description":"وصف","debit_account":"exact name","credit_account":"exact name","amount":number}}
For unclear: {{"needs_clarification":true,"reason":"السبب"}}
For non-transaction: {{"not_transaction":true,"reply":"رد"}}

Use EXACT account names from list.''',
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
            await u.message.reply_text(
                f"⚠️ حساب غير موجود\n"
                f"مدين: {d['debit_account']}\n"
                f"دائن: {d['credit_account']}\n\n"
                f"/accounts"
            )
            return
        
        entry_id = post_entry(today, d["description"], d["debit_account"], d["credit_account"], d["amount"])
        
        await u.message.reply_text(
            f"✅ تم التسجيل #{entry_id}\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📅 {today}\n"
            f"📝 {d['description']}\n"
            f"💰 {d['amount']:,.0f} ريال\n\n"
            f"⬆️ مدين: {d['debit_account']}\n"
            f"⬇️ دائن: {d['credit_account']}"
        )
    
    except json.JSONDecodeError:
        await u.message.reply_text("⚠️ ما قدرت أفهم، حاول بصيغة أوضح")
    except Exception as e:
        await u.message.reply_text("⚠️ خطأ تقني")
        print(f"Error: {e}")


def main():
    init()
    print("Bot running!")
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
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process))
    app.run_polling()


if __name__ == "__main__":
    main()
