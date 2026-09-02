# نشر MarketPulse على Ubuntu VPS

الخدمة مضبوطة افتراضيًا على `http://187.77.174.215:8081`. ينصح بتشغيلها بحساب Linux مستقل وبـ Gunicorn عامل واحد، لأن طابور أوامر MT5 وحالة بعض الحسابات موجودان في الذاكرة.

## 1. تجهيز الملفات والبيئة

انسخ ملفات المشروع إلى `/var/www/Forex2`، ثم نفّذ على الـVPS:

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip ufw
sudo useradd --system --home /var/www/Forex2 --shell /usr/sbin/nologin marketpulse || true
sudo chown -R marketpulse:marketpulse /var/www/Forex2
sudo -u marketpulse python3 -m venv /var/www/Forex2/.venv
sudo -u marketpulse /var/www/Forex2/.venv/bin/pip install -r /var/www/Forex2/requirements.txt
```

انسخ `.env.example` إلى `.env`، وأنشئ سرًا جديدًا بدل القيمة الافتراضية:

```bash
cp /var/www/Forex2/.env.example /var/www/Forex2/.env
openssl rand -hex 32
```

ضع الناتج في `MARKETPULSE_EA_SECRET`، وضع القيمة نفسها في `SecretKey` داخل `MarketPulse_Bridge.mq5` قبل تجميع الـEA.

## 2. فتح المنفذ 8081

```bash
sudo ufw allow 8081/tcp
sudo ufw status
```

إذا كان مزود الـVPS يملك Cloud Firewall أو Security Group، افتح TCP/8081 هناك أيضًا. لا يمكن فتح جدار الـVPS من ملفات المشروع نفسها.

## 3. تشغيل الخدمة تلقائيًا

```bash
sudo cp /var/www/Forex2/marketpulse.service.example /etc/systemd/system/marketpulse.service
sudo systemctl daemon-reload
sudo systemctl enable --now marketpulse
sudo systemctl status marketpulse --no-pager
```

## 4. التحقق

```bash
curl http://127.0.0.1:8081/api/health
curl http://187.77.174.215:8081/api/health
```

بعدها افتح `http://187.77.174.215:8081` في المتصفح، وأضف العنوان نفسه إلى قائمة Allow WebRequest في MetaTrader 5.

## ملاحظة أمان

لا تشغّل حساب تداول حقيقي قبل إضافة مصادقة خادمية للوحة التحكم. تسجيل دخول الأدمن الحالي موجود في JavaScript و`localStorage` فقط، لذلك هو واجهة شكلية وليس حماية للخادم. استخدم HTTPS عبر نطاق وNginx قبل إدخال مفاتيح AI أو بيانات حساسة في المتصفح.
