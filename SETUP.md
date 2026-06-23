# 🚀 راهنمای نصب آنالیزور هوشمند تماس فروش

## معماری سیستم
```
دفترشما VoIP
    ↓ Webhook (پایان هر تماس)
Railway.app Server (app.py)
    ↓ Claude API آنالیز
    ├── 📱 تلگرام (فوری)
    ├── 📧 ایمیل (HTML زیبا)
    └── 🌐 داشبورد وب (آرشیو کامل)
```

---

## مرحله ۱ - آپلود کد روی GitHub

۱. به https://github.com برو و حساب بساز (اگه نداری)
۲. New Repository → نام: `voip-analyzer` → Public → Create
۳. همه فایل‌های این پوشه رو آپلود کن (Upload files)

---

## مرحله ۲ - دیپلوی روی Railway

۱. برو به https://railway.app
۲. با GitHub لاگین کن
۳. **New Project** → **Deploy from GitHub repo**
۴. Repo رو انتخاب کن → Deploy

---

## مرحله ۳ - تنظیم Environment Variables در Railway

در Railway → پروژه‌ات → **Variables** → این‌ها رو اضافه کن:

| کلید | مقدار |
|------|-------|
| `ANTHROPIC_API_KEY` | از console.anthropic.com/settings/keys |
| `WEBHOOK_SECRET` | یه رمز دلخواه مثل `daftar1403` |
| `TELEGRAM_BOT_TOKEN` | از @BotFather |
| `TELEGRAM_CHAT_ID` | ID گروه یا کانال تلگرامت |
| `EMAIL_FROM` | ایمیل Gmail فرستنده |
| `EMAIL_PASSWORD` | App Password گوگل |
| `EMAIL_TO` | ایمیل گیرنده |

---

## مرحله ۴ - دریافت دامنه

در Railway → **Settings** → **Generate Domain**
آدرسی مثل این میگیری:
```
https://voip-analyzer-production.up.railway.app
```

---

## مرحله ۵ - تنظیم Webhook در دفترشما

۱. برو به **portal.daftareshoma.com/hook**
۲. **افزودن هوک** رو بزن
۳. آدرس هوک:
   ```
   https://YOUR-APP.up.railway.app/webhook/daftareshoma?secret=daftar1403
   ```
   *(به جای `daftar1403` همون WEBHOOK_SECRET که گذاشتی)*

۴. نام هوک: `آنالیزور هوشمند`
۵. رویدادها رو فعال کن:
   - ✅ اعلام پایان تماس وردی (Call.incoming.ended)
   - ✅ اعلام پایان تماس خروجی (Call.outgoing.ended)
۶. **ذخیره‌سازی** رو بزن

---

## مرحله ۶ - تست

یه تماس آزمایشی برقرار کن و چک کن:

**تلگرام:** باید ظرف ۳۰ ثانیه گزارش بیاد
**ایمیل:** ظرف ۱ دقیقه
**داشبورد:** `https://YOUR-APP.up.railway.app`

---

## ساختار داده Webhook دفترشما

دفترشما این payload رو می‌فرسته:
```json
{
  "event": "Call.outgoing.ended",
  "data": {
    "call_id": "abc123",
    "caller_number": "09121234567",
    "callee_number": "09361234567",
    "duration": 420,
    "agent_name": "علی رضایی",
    "extension": "101",
    "started_at": "2024-01-15 10:30:00",
    "ended_at": "2024-01-15 10:37:00"
  }
}
```

---

## خروجی‌ها

### تلگرام
پیام فوری بعد از هر تماس با:
- امتیاز ۰-۱۰۰
- نقاط قوت و ضعف
- پیشنهادات بهبود
- جمله طلایی برای تماس بعدی

### ایمیل
گزارش HTML زیبا به مدیر

### داشبورد وب
- آمار لحظه‌ای
- جدول همه تماس‌ها
- فیلتر بر اساس تاریخ و فروشنده
- جزئیات کامل هر تماس با کلیک

---

## هزینه

| سرویس | هزینه |
|-------|-------|
| Railway | رایگان تا ۵۰۰ ساعت/ماه |
| Claude API | ~$۰.۰۰۳ به ازای هر تماس |
| تلگرام | رایگان |
| Gmail | رایگان |

---

## سوالات رایج

**Q: اگه تماس ضبط نشه چی؟**
A: سیستم از روی مدت تماس آنالیز می‌کنه (بدون transcript)

**Q: برای دریافت transcript صوتی چی کار کنم؟**
A: نسخه پیشرفته با Whisper API در مرحله بعدی اضافه میشه

**Q: چند فروشنده می‌تونم داشته باشم؟**
A: نامحدود - سیستم از نام extension در دفترشما استفاده می‌کنه
