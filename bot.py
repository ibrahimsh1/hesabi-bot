"""
Hesabi Bot - Full Personal Accounting System
- Double-entry bookkeeping
- Assets, Liabilities, Equity, Income, Expenses
- Balance Sheet, Income Statement, Cash Flow
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
    # Accounts (chart of accounts)
    c.execute("""CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE,
        type TEXT,
        active INTEGER DEFAULT 1
    )""")
    # Journal entries (double-entry)
    c.execute("""CREATE TABLE IF NOT EXISTS journal (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT,
        description TEXT,
        debit_account TEXT,
        credit_account TEXT,
        amount REAL
    )""")
    # Insert default accounts if empty
    count = c.execute("SELECT COUNT(*) FROM accounts").fetchone()[0]
    if count == 0:
        defaults = [
            # Assets
            ("نقد", "asset"),
            ("بنك", "asset"),
            ("استثمارات", "asset"),
            ("ذهب", "asset"),
            ("عقار", "asset"),
            ("سيارة", "asset"),
            # Liabilities
            ("قرض", "liability"),
            ("بطاقة ائتمان", "liability"),
            # Equity
            ("رأس المال", "equity"),
            # Income
            ("راتب", "income"),
            ("دخل اضافي", "income"),
            ("ارباح استثمار", "income"),
            # Expenses
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
    c.commit()
    c.close()


def get_accounts():
    c = sqlite3.connect(DB)
    rows = c.execute("SELECT name, type FROM accounts WHERE active=1 ORDER BY type, name").fetchall()
    c.close()
    return rows


def get_balance(account):
    """Get account balance based on type"""
    c = sqlite3.connect(DB)
    acc_type = c.execute("SELECT type FROM accounts WHERE name=?", (account,)).fetchone()
    if not acc_type:
        c.close()
        return 0
    acc_type = acc_type[0]
    
    debits = c.execute("SELECT COALESCE(SUM(amount), 0) FROM journal WHERE debit_account=?", (account,)).fetchone()[0]
    credits = c.execute("SELECT COALESCE(SUM(amount), 0) FROM journal WHERE credit_account=?", (account,)).fetchone()[0]
    c.close()
    
    # Assets & Expenses: debit - credit (debit-normal)
    # Liabilities, Equity, Income: credit - debit (credit-normal)
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


# ============== TELEGRAM HANDLERS ==============
async def start(u, c):
    await u.message.reply_text(
        "🏦 محاسبك الشخصي - نظام محاسبة كامل\n"
        "━━━━━━━━━━━━━━━\n\n"
        "📝 لاضافة معاملة، اكتبها طبيعي:\n"
        "  • قهوة 18\n"
        "  • راتب 8000\n"
        "  • اشتريت اسهم بـ 5000\n"
        "  • سددت قرض 2000\n\n"
        "📊 التقارير:\n"
        "  /balance - الميزانية العمومية\n"
        "  /income - قائمة الدخل\n"
        "  /networth - صافي الثروة\n"
        "  /accounts - كل الحسابات\n"
        "  /last10 - آخر المعاملات\n\n"
        "🛠️ ادارة الحسابات:\n"
        "  /addaccount - اضف حساب جديد\n"
        "  /help - مساعدة"
    )


async def help_cmd(u, c):
    await u.message.reply_text(
        "📖 الدليل السريع\n"
        "━━━━━━━━━━━━━━━\n\n"
        "💡 امثلة على المعاملات:\n\n"
        "مصاريف:\n"
        "  قهوة 18\n"
        "  بنزين 200\n\n"
        "دخل:\n"
        "  راتب 8000\n"
        "  بيع منتج 500\n\n"
        "تحويلات (اصول):\n"
        "  حولت 1000 للبنك\n"
        "  اشتريت ذهب 3000\n\n"
        "قروض (خصوم):\n"
        "  اخذت قرض 50000\n"
        "  سددت قسط 2000\n\n"
        "📊 كل التقارير تجي من البيانات المدخلة"
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
    """Balance Sheet"""
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
    text += f"  مجموع الأصول: {assets_total:,.0f}\n\n"
    
    text += "💳 الخصوم:\n"
    liab_total = 0
    for name, (atype, bal) in by_acc.items():
        if atype == "liability":
            text += f"  {name}: {bal:,.0f}\n"
            liab_total += bal
    if liab_total == 0:
        text += "  (لا يوجد)\n"
    text += f"  ─────────\n"
    text += f"  مجموع الخصوم: {liab_total:,.0f}\n\n"
    
    # Net income (income - expense) goes to equity
    net_income = totals["income"] - totals["expense"]
    equity_total = totals["equity"] + net_income
    
    text += "📈 حقوق الملكية:\n"
    text += f"  رأس المال: {totals['equity']:,.0f}\n"
    text += f"  الأرباح المحتجزة: {net_income:,.0f}\n"
    text += f"  ─────────\n"
    text += f"  مجموع حقوق الملكية: {equity_total:,.0f}\n\n"
    
    text += "━━━━━━━━━━━━━━━\n"
    text += f"إجمالي الأصول: {assets_total:,.0f}\n"
    text += f"إجمالي الخصوم + حقوق الملكية: {liab_total + equity_total:,.0f}\n"
    
    diff = assets_total - (liab_total + equity_total)
    if abs(diff) > 0.01:
        text += f"⚠️ فرق: {diff:,.0f}"
    else:
        text += "✅ الميزانية متوازنة"
    
    await u.message.reply_text(text)


async def cmd_income(u, c):
    """Income Statement"""
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
    """Quick Net Worth"""
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
        "SELECT date, description, debit_account, credit_account, amount FROM journal ORDER BY id DESC LIMIT 10"
    ).fetchall()
    conn.close()
    
    if not rows:
        await u.message.reply_text("ما في معاملات بعد")
        return
    
    text = "📜 آخر 10 معاملات\n━━━━━━━━━━━━━━━\n\n"
    for r in rows:
        text += f"📅 {r[0]}\n"
        text += f"   {r[1]}\n"
        text += f"   من: {r[3]} → الى: {r[2]}\n"
        text += f"   💰 {r[4]:,.0f}\n\n"
    
    await u.message.reply_text(text)


async def cmd_addaccount(u, c):
    args = u.message.text.split(maxsplit=2)
    if len(args) < 3:
        await u.message.reply_text(
            "الاستخدام:\n"
            "/addaccount <النوع> <الاسم>\n\n"
            "الأنواع: asset, liability, equity, income, expense\n\n"
            "مثال:\n"
            "/addaccount asset محفظة الجيب\n"
            "/addaccount liability قرض السيارة"
        )
        return
    
    atype = args[1].lower()
    name = args[2]
    
    if atype not in ("asset", "liability", "equity", "income", "expense"):
        await u.message.reply_text("النوع غير صحيح. استخدم: asset, liability, equity, income, expense")
        return
    
    try:
        conn = sqlite3.connect(DB)
        conn.execute("INSERT INTO accounts (name, type) VALUES (?, ?)", (name, atype))
        conn.commit()
        conn.close()
        await u.message.reply_text(f"✅ تم اضافة الحساب: {name} ({atype})")
    except sqlite3.IntegrityError:
        await u.message.reply_text("⚠️ الحساب موجود مسبقاً")


# ============== AI PROCESSING ==============
async def process(u, c):
    msg = u.message.text.strip()
    today = datetime.now().strftime("%Y-%m-%d")
    
    if len(msg) < 3:
        await u.message.reply_text("ارسل وصف اوضح")
        return
    
    if not re.search(r'\d+', msg):
        await u.message.reply_text(
            "❌ الرسالة بدون مبلغ\n\n"
            "اكتب: الوصف + المبلغ\n"
            "مثال: قهوة 18"
        )
        return
    
    await u.message.reply_text("🔄 جاري تسجيل القيد المحاسبي...")
    
    # Get available accounts for context
    accounts = get_accounts()
    accounts_text = "\n".join([f"- {name} ({atype})" for name, atype in accounts])
    
    try:
        r = ai.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system=f'''You are a Saudi personal accounting assistant using DOUBLE-ENTRY bookkeeping.

TODAY: {today}

AVAILABLE ACCOUNTS:
{accounts_text}

RULES FOR DOUBLE ENTRY:
- Every transaction has DEBIT (مدين) and CREDIT (دائن) of EQUAL amount
- Assets ↑ = DEBIT | Assets ↓ = CREDIT
- Liabilities ↑ = CREDIT | Liabilities ↓ = DEBIT  
- Income = CREDIT
- Expenses = DEBIT
- Equity = CREDIT

COMMON PATTERNS:
1. Expense paid in cash: DEBIT expense_account, CREDIT نقد
   Example "قهوة 18": debit="طعام وشراب", credit="نقد", amount=18

2. Salary received: DEBIT نقد (or بنك), CREDIT راتب
   Example "راتب 8000": debit="بنك", credit="راتب", amount=8000

3. Buy investment: DEBIT استثمارات, CREDIT نقد
   Example "اشتريت اسهم بـ 5000": debit="استثمارات", credit="نقد", amount=5000

4. Transfer between assets: DEBIT new_asset, CREDIT old_asset
   Example "حولت 1000 للبنك": debit="بنك", credit="نقد", amount=1000

5. Take loan: DEBIT نقد, CREDIT قرض
6. Pay loan: DEBIT قرض, CREDIT نقد

REPLY ONLY with valid JSON:

For transaction:
{{"description":"وصف بالعربي","debit_account":"اسم الحساب","credit_account":"اسم الحساب","amount":number}}

For unclear:
{{"needs_clarification":true,"reason":"السبب بالعربي"}}

For non-transaction:
{{"not_transaction":true,"reply":"رد مهذب"}}

Use EXACT account names from the list above. If none fits, use closest match.''',
            messages=[{"role": "user", "content": msg}]
        )
        
        raw = r.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        d = json.loads(raw)
        
        if d.get("not_transaction"):
            await u.message.reply_text(d.get("reply", "هذي مو معاملة مالية"))
            return
        
        if d.get("needs_clarification"):
            await u.message.reply_text(f"❓ {d.get('reason', 'محتاج توضيح')}")
            return
        
        # Validate accounts exist
        conn = sqlite3.connect(DB)
        valid = lambda name: conn.execute("SELECT 1 FROM accounts WHERE name=?", (name,)).fetchone()
        
        if not valid(d["debit_account"]) or not valid(d["credit_account"]):
            conn.close()
            await u.message.reply_text(
                f"⚠️ حساب غير موجود\n"
                f"المدين: {d['debit_account']}\n"
                f"الدائن: {d['credit_account']}\n\n"
                f"شوف الحسابات: /accounts"
            )
            return
        conn.close()
        
        # Post the journal entry
        post_entry(today, d["description"], d["debit_account"], d["credit_account"], d["amount"])
        
        await u.message.reply_text(
            f"✅ تم تسجيل القيد\n"
            f"━━━━━━━━━━━━━━━\n"
            f"📅 التاريخ: {today}\n"
            f"📝 الوصف: {d['description']}\n"
            f"💰 المبلغ: {d['amount']:,.0f} ريال\n\n"
            f"⬆️ مدين: {d['debit_account']}\n"
            f"⬇️ دائن: {d['credit_account']}"
        )
    
    except json.JSONDecodeError:
        await u.message.reply_text("⚠️ ما قدرت اقرا الرد، حاول بصيغة اوضح")
    except Exception as e:
        await u.message.reply_text(f"⚠️ خطا تقني")
        print(f"Error: {e}")


def main():
    init()
    print("Bot running on Railway!")
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("accounts", cmd_accounts))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("income", cmd_income))
    app.add_handler(CommandHandler("networth", cmd_networth))
    app.add_handler(CommandHandler("last10", cmd_last10))
    app.add_handler(CommandHandler("addaccount", cmd_addaccount))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, process))
    app.run_polling()


if __name__ == "__main__":
    main()
