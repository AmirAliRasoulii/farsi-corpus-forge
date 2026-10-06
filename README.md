# Farsi Corpus Forge (`farsi-corpus-forge`)

سامانهٔ صنعتی و پژوهشی ارتقایافته برای **فارسی‌سازی داده‌های پژوهشی** و **تولید مستقل دادهٔ سالم فارسی**.

این سامانه متمرکز بر تولید دادگان پژوهشی با درجه اطمینان و وفاداری بالا است؛ نه صرفاً تولید ترجمه‌های ظاهراً روان که توهین‌ها را تلطیف، سانسور یا تحریف کرده باشند.

---

## ۱. اصول معماری و خطوط قرمز

1. **استقلال کامل دو پروژه:** اجرای فارسی‌سازی (`persianization`) کاملاً مستقل از تولید دادهٔ سفید (`white_generation`) است؛ ترجمه داده‌ها هرگز تولید سفید را به صورت خودکار فعال نمی‌کند.
2. **ورود مستقیم دادهٔ بومی فارسی:** متن‌های فارسی هدف مستقیماً و بدون بازنویسی یا فراخوانی مدل وارد سامانه می‌شوند (`origin=native_fa`، `translation_status=not_required`، `quality_status=not_evaluated`).
3. **تفکیک زبان متن و زمینه (Context):** متن و زمینه به صورت مستقل تحلیل می‌شوند. اگر متن فارسی با زمینه انگلیسی باشد، تنها زمینه به فارسی ترجمه می‌شود و متن بومی دست‌نخورده باقی می‌ماند.
4. **فرهنگ ناسزا و زبان محاوره‌ای معاصر ایران:**
   - وفاداری به لحن، شدت و کاربرد گفتگویی ناسزا بدون ستاره‌گذاری (`***`)، تلطیف، یا تبدیل به نقد مؤدبانه.
   - منع بومیسازی انحرافی: هیچ‌گونه توهین ناموسی، جنسیتی، قومی یا مذهبی که در متن مبدأ وجود نداشته نباید به متن مقصد اضافه شود.
   - حفظ شخص هدف و جهت‌گیری گوینده بدون افزودن توهمات زمینه‌ای.
5. **پردازش دانه‌به‌دانه در Batchهای اجرایی:**
   - هر درخواست ترجمه صرفاً شامل یک رکورد و زمینهٔ همان رکورد است (عدم تجمیع چند متن در یک پرامپت).
   - ردیابی با `request_id` و حفظ ترتیب اصلی ورودی با `input_order_idx`.
   - ذخیره‌سازی فوری در SQLite به ازای هر رکورد موفق؛ شکست یک رکورد باعث هدررفت یا تکرار رکوردهای موفق نمی‌شود.
   - محدودیت همزمانی (`MAX_CONCURRENT_REQUESTS`)، اندازه بچ ورودی (`INPUT_BATCH_SIZE`)، سقف تماس و نرخ مشترک (`RateLimiter`) میان تمام workerها.
6. **داوری کیفی دوگانه (Dual Quality Judge):**
   - **ارزیاب اول (`QUALITY_MODEL_1`):** ارزیابی ۷ بعد با روبریم ۱ تا ۵، بررسی ابعاد منطقی (حفظ هدف، موضع، نفی، نقل‌قول، ابهام) و پرچم‌های انسدادی (`censored_content`، `severity_changed`، ...). معیار وفاداری زمینه در نبود context با `applicable=false` مشخص می‌شود.
   - **ارزیاب دوم (`QUALITY_MODEL_2`):** داوری نابینا بدون دیدن نمره و نظر داور اول در دو مسیر مجزا:
     - **الف) نمونه تصادفی پایدار ۱۰٪** مبتنی بر هش شناسه رکورد.
     - **ب) نمونه‌گیری هدفمند** برای مدل‌های Fallback، موارد مشکوک به سانسور، تغییر شدت، یا نمرات مرزی.
   - **ثبت صریح اختلاف:** در صورت تعارض داوران درباره خطای بحرانی، میانگین‌گیری اکیداً ممنوع بوده و وضعیت `review_required` / `disagreement` ثبت می‌شود.
7. **استقلال مطلق مدل‌ها:**
   - مدل‌های `QUALITY_MODEL_1` و `QUALITY_MODEL_2` باید شناسه و ارائه‌دهندهٔ مستقل داشته و با مترجم اصلی و تمام مترجم‌های Fallback متفاوت باشند.
8. **مدیریت سانسور پنهان و Fallback با متن اولیه:**
   - اگر مدلی ترجمه سانسورشده با ساختار JSON معتبر برگرداند، ارزیاب کیفیت آن را رد کرده و سامانه با متن اولیهٔ دست‌نخورده به سراغ مدل Fallback بعدی می‌رود.
9. **کلید قطع اضطراری (Circuit Breaker):**
   - پایش برخط جهش خطاهای فنی، امتناع‌ها، یا افت کیفیت و توقف ایمن خط لوله با قابلیت بازگشت (`PipelineCircuitBreaker`).
10. **طبقه‌بندی صریح بذر در تولید سفید:**
    - تفکیک `unannotated` (بدون برچسب) از `ambiguous_after_annotation` (دارای ابهام پس از ارزیابی). داده‌های `null` بدون برچسب هرگز دوپهلو تلقی نمی‌شوند.
11. **بازبینی انسانی با پاکسازی نمرات پیشین (HITL):**
    - دریافت فایل اکسل با بررسی هش متن خام و اعتبارسنجی پیش از اعمال.
    - ذخیره متن اصلاح‌شده در فیلد مستقل `human_edited_text` و ابطال خودکار نمرات کیفی ماشینی پیشین.

---

## ۲. ساختار مخزن

```text
farsi-corpus-forge/
├── .github/workflows/ci.yml       # پایپ‌لاین CI گیت‌هاب (اجرای ۴۱ تست و دموی آفلاین)
├── shared/                       # ماژول‌های مشترک و قابل استفاده مجدد
│   ├── circuit_breaker.py        # کلید قطع اضطراری خط لوله (Circuit Breaker)
│   ├── rate_limiter.py           # مدیریت نرخ و سقف بودجه مشترک (RateLimiter)
│   ├── api_client.py             # کلاینت سازگار با AvalAI با مدیریت خطاهای احراز هویت
│   ├── io_utils.py               # خواندن جریانی فایل‌ها و اعتبارسنجی ورودی
│   ├── excel_utils.py            # خروجی اکسل با مقابله علیه تزریق فرمول و ستون‌های HITL
│   ├── language_detector.py      # تشخیص دقیق زبان و تفکیک فینگلیش و متن مختلط
│   ├── lineage.py                # ردیابی تبار و جلوگیری از نشت بین Train/Dev/Test
│   └── run_lock.py               # قفل فرآیند برای جلوگیری از تداخل اجراهای همزمان
│
├── persianization/               # پروژه A: فارسی‌سازی داده‌های پژوهشی
│   ├── cli.py                    # ارکستراتور جریانی و خط فرمان
│   ├── config.py                 # اعتبارسنجی متغیرهای محیطی و استقلال مدل‌ها
│   ├── storage.py                # پایگاه داده SQLite با لاگ تلاش‌ها و ذخیره نتایج دو داور
│   ├── router.py                 # تفکیک مسیر متن و زمینه
│   ├── translator.py             # موتور ترجمه، Fallback و ترجمه مستقل زمینه
│   ├── quality_judge.py          # ارزیاب کیفیت دوگانه (DualQualityJudge)
│   ├── exporter.py               # صدور خروجی‌های استاندارد همراه با فیلدهای داور دوم
│   ├── review_manager.py         # دریافت بازبینی انسانی با ابطال نمرات مدل
│   ├── prompts/                  # پرامپت‌های مستقل ترجمه و ارزیابی کیفیت
│   ├── config/review_policy.json # خط مشی پذیرش کیفی و پرچم‌های بحرانی
│   └── .env.example              # نمونه تنظیمات محیطی بدون کلید
│
├── white_generation/             # پروژه B: تولید مستقل داده سالم و داوری ۴ نفره
│   ├── cli.py                    # خط فرمان مستقل پروژه سفید
│   ├── config.py                 # تنظیمات پروژه سفید
│   ├── storage.py                # پایگاه داده SQLite کاندیداها و بذرها
│   ├── recipes/generator.py      # الگوهای تولید داده سالم
│   ├── quality_judge.py          # ارزیاب روانی زبان فارسی کاندیداها
│   ├── offense_judges.py         # پنل داوری توهین ۴ نفره نابینا
│   ├── exporter.py               # صدور ۸ فایل خروجی استاندارد
│   └── review_manager.py         # اعمال بازبینی انسانی برای کاندیداها
│
├── mock_demo/                    # دموی آفلاین کامل و تعیین‌کننده (بدون مصرف توکن)
│   ├── mock_llm.py               # شبیه‌ساز رفتار مدل‌ها، امتناع، سانسور و اختلاف داوران
│   └── run_mock_demo.py          # اجرای انتهای‌به‌انتهای هر دو پروژه
│
├── tests/                        # ۴۱ آزمون جامع واحد و یکپارچگی (Pytest)
│   ├── test_advanced_requirements.py # تست‌های استقلال، سانسور پنهان، داور دوم و...
│   ├── test_fidelity_and_qc.py
│   ├── test_input_validation.py
│   ├── test_language_routing.py
│   ├── test_persistence_and_lineage.py
│   ├── test_refusal_and_fallbacks.py
│   ├── test_text_preservation.py
│   └── test_white_generation.py
│
├── pilot/                        # ابزار اجرای پایلوت و قالب گزارش ارزیابی
│   ├── pilot_runner.py
│   └── pilot_report_template.md
│
├── requirements.txt              # نیازمندی‌های سبک پایتون
├── pyproject.toml                # تنظیمات پروژه و ابزارها
├── LICENSE                       # مجوز نرم‌افزار (MIT License)
└── README.md
```

---

## ۳. نصب و پیش‌نیازها

سامانه بدون وابستگی به فریم‌ورک‌های سنگین یادگیری ماشین اجرا می‌شود:

```bash
# کلون کردن مخزن
git clone https://github.com/AmirAliRasoulii/farsi-corpus-forge.git
cd farsi-corpus-forge

# ایجاد و فعال‌سازی محیط مجازی
python3 -m venv venv
source venv/bin/activate

# نصب وابستگی‌ها
pip install --upgrade pip
pip install -r requirements.txt
pip install pytest openpyxl
```

---

## ۴. اجرای آزمون‌ها و دموی آفلاین

### اجرای ۵۵ آزمون خودکار:
```bash
pytest -v
```

### اجرای دموی آفلاین سرتاسری:
```bash
python -m mock_demo.run_mock_demo
```
این دستور بدون نیاز به اینترنت یا کلید API، هر دو پروژه را اجرا کرده و خروجی‌های معتبر JSONL، CSV و Excel تولید می‌کند.

---

## ۵. راهنمای اجرای خط لوله‌ها (`persianization` و `white_generation`)

### ۱. اجرای خط لوله فارسی‌سازی (`persianization`):
```bash
python -m persianization.cli run \
  --input examples/sample_persianization_input.csv \
  --output-dir outputs/persianization \
  --batch-size 50 \
  --concurrency 4
```

### ۲. ادامه اجرای متوقف‌شده (Resume):
در صورت بروز وقفه، با پرچم `--resume` پردازش از آخرین رکورد ثبت‌شده در SQLite بدون تکرار کارهای موفق ادامه می‌یابد (بر اساس اثرانگشت محتوا و تنظیمات):
```bash
python -m persianization.cli run \
  --input examples/sample_persianization_input.csv \
  --output-dir outputs/persianization \
  --resume
```

### ۳. بازبینی انسانی از اکسل (HITL):
فایل `outputs/persianization/review.xlsx` را ویرایش کرده و دستور زیر را اجرا کنید:
```bash
python -m persianization.cli review-ingest \
  --excel-file outputs/persianization/review.xlsx \
  --output-dir outputs/persianization \
  --reviewer "نام_ارزیاب"
```

### ۴. اجرای خط لوله تولید داده سالم (`white_generation`):
```bash
python -m white_generation.cli run \
  --input examples/persian_white_seeds.jsonl \
  --output-dir outputs/white_generation \
  --batch-size 10 \
  --concurrency 4
```

---

## ۶. وضعیت آزمون و پایلوت واقعی AvalAI

- **وضعیت اجرای پایلوت زنده با AvalAI:** **انجام‌نشده (Unexecuted)**
- **علت:** عدم تنظیم کلید واقعی و معتبر `LLM_API_KEY` در محیط فعلی. سامانه جهت رعایت صداقت علمی و اصول امنیتی، اجرای پایلوت زنده را بدون کلید واقعی معتبر اعلام نمی‌کند.
- **دستور اجرای پایلوت پس از تنظیم کلید واقعی:**
  ```bash
  python -m pilot.pilot_runner \
    --models gpt-4o-mini,gemini-2.5-flash,claude-haiku-4-5 \
    --output pilot/pilot_results.json
  ```

---

## ۷. مجوز

این پروژه تحت مجوز [MIT License](LICENSE) منتشر شده است. این مجوز صرفاً متعلق به کدهای این مخزن است و مجوزی برای دیتاست‌های خارجی متفرقه تلقی نمی‌شود.
