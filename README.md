# سامانه پژوهشی فارسی‌سازی دیتاست و تولید دادهٔ سالم فارسی

این مخزن شامل پیاده‌سازی صنعتی و پژوهشی دو پروژه مستقل و خودکفا برای پردازش داده‌های متنی است:

1. **پروژه A (`persianization`):** فارسی‌سازی دیتاست‌های پژوهشی شامل ورود مستقیم داده‌های بومی فارسی (`native_fa`) بدون فراخوانی مدل، ترجمه دقیق انگلیسی به فارسی رایج و طبیعی ایران (`translated_en_to_fa`)، کنترل کیفیت مستقل و وفاداری به لحن، شدت و ساختار متن، مدیریت امتناع و مدل‌های جایگزین (Fallback)، بازبینی انسانی و خروجی‌های استاندارد.
2. **پروژه B (`white_generation`):** تولید مستقل داده‌های سالم (White/Clean Data) بر پایه بذور فارسی (شامل خروجی فارسی پروژه A یا هر دیتای فارسی دیگر)، اعمال الگوهای مستقل (دستورالعمل‌های رفع ابهام، نقد مستدل، هارد نگاتیو، عادی و آموزشی)، ارزیابی کیفیت زبان فارسی، و در نهایت داوری توهین توسط پنل ۴ داور مستقل نابینا با قواعد اجماع صریح.

---

## ۱. اصول اساسی و خطوط قرمز سامانه

- **استقلال کامل دو پروژه:** اجرای فارسی‌سازی (پروژه A) هرگز به اجرای تولید سفید وابسته نیست و تولید سفید را فعال نمی‌کند. ترجمه نباید به سالم‌سازی تبدیل شود.
- **حفظ مطلق اصالت متن خام:** متن اصلی، متن زمینه، ایموجی‌ها، لحن، واژگان رکیک، کنایه‌ها، نگارش عامیانه و ساختارهای پوشیده عیناً حفظ می‌شوند. هیچ رکوردی بی‌سر و صدا حذف نمی‌شود.
- **عدم سانسور در ترجمه:** اگر متن اصلی توهین‌آمیز است، توهین تلطیف، حذف، ستاره‌گذاری (`***`) یا تبدیل به نقد نمی‌شود؛ شدت معادل فارسی متناسب با کاربرد اصل حفظ می‌شود.
- **تفکیک ترجمه از سالم بودن:** خروجی `accepted_persian` یعنی متنی که از نظر ساختار زبان فارسی و وفاداری به اصل تأیید شده است؛ این خروجی شامل متون سالم و متون توهین‌آمیز است و نباید «clean» یا «white» نامیده شود.
- **ارزیاب مستقل کیفیت:** مدل ارزیاب کیفیت (`QUALITY_MODEL`) الزاماً مدلی متفاوت از مدل مترجم است تا استقلال داوری مخدوش نشود.
- **عدم اختلاط عبارت «نمی‌توانم» با امتناع مدل:** ترجمه وفادار عباراتی مانند "I cannot understand" که حاوی «نمی‌توانم» است، امتناع شمرده نمی‌شود.
- **تولید سفید کاملاً برچسب‌گذاری شده:** داده‌های سالم تولیدی با `origin=generated_white` ثبت می‌شوند و هرگز به عنوان دادهٔ بومی گردآوری‌شده معرفی نمی‌شوند.

---

## ۲. ساختار پروژه

```text
translate-offset-data/
├── shared/                      # ماژول‌های مشترک و قابل استفاده مجدد
│   ├── api_client.py            # کلاینت سازگار با AvalAI و OpenAI با توقف ایمن در 401/403
│   ├── rate_limiter.py          # مدیریت نرخ درخواست (RPM) و سقف بودجه (MAX_API_CALLS)
│   ├── io_utils.py              # خواندن جریانی CSV (UTF-8/BOM)، JSON و JSONL با اعتبارسنجی پیش از API
│   ├── excel_utils.py           # تولید فایل اکسل با دفاع تزریق فرمول و ستون‌های بازبینی انسانی
│   ├── language_detector.py     # مسیریابی دقیق زبان (فارسی، انگلیسی، فینگلیش، زبان مختلط)
│   ├── lineage.py               # ردیابی منشأ، تکرار قطعی و جلوگیری از نشت داده میان splitها
│   ├── run_lock.py              # قفل دایرکتوری اجرا جهت جلوگیری از تداخل فرآیندهای همزمان
│   └── text_safety.py           # مصون‌سازی متن و بررسی محدودیت طول سلول اکسل
│
├── persianization/              # پروژه A: ورود مستقیم فارسی و ترجمه وفادار انگلیسی
│   ├── cli.py                   # رابط خط فرمان مستقل پروژه A
│   ├── config.py                # بارگذاری تنظیمات و اعتبارسنجی استقلال مدل‌ها
│   ├── storage.py               # ذخیره‌سازی مرحله‌ای در SQLite و قابلیت Resume
│   ├── router.py                # تفکیک مسیر متن و زمینه (Context)
│   ├── translator.py            # موتور ترجمه، مدل اصلی و Fallbackهای مرتب
│   ├── quality_judge.py         # ارزیاب کیفیت وفاداری بر اساس روبریم ۱ تا ۵ و پرچم‌های خطا
│   ├── exporter.py              # صدور ۱۰ فایل خروجی استاندارد پروژه A
│   ├── review_manager.py        # دریافت و اعمال بازبینی انسانی از فایل Excel
│   ├── prompts/                 # پرامپت‌های مستقل ترجمه و ارزیابی کیفیت
│   ├── config/                  # خط مشی پذیرش کیفی (review_policy.json)
│   └── .env.example             # نمونه پیکربندی متغیرهای محیطی
│
├── white_generation/            # پروژه B: تولید مستقل داده سالم و فیلتر ۴ داور
│   ├── cli.py                   # رابط خط فرمان مستقل پروژه B
│   ├── config.py                # بارگذاری تنظیمات پروژه B
│   ├── storage.py               # ذخیره‌سازی مرحله‌ای کاندیداها و آرا در SQLite
│   ├── recipes/                 # الگوهای تولید: رفع ابهام، نقد، هارد نگاتیو، عادی و...
│   ├── quality_judge.py         # ارزیاب کیفیت و روانی زبان فارسی کاندیدا
│   ├── offense_judges.py        # پنل ۴ داور نابینا برای ارزیابی توهین و قواعد اجماع
│   ├── exporter.py              # صدور ۸ فایل خروجی استاندارد پروژه B
│   ├── review_manager.py        # دریافت و اعمال بازبینی انسانی برای کاندیداها
│   ├── prompts/                 # پرامپت‌های الگوها و داوری نابینا
│   ├── config/                  # خط مشی تولید و اجماع (generation_policy.json)
│   └── .env.example             # نمونه پیکربندی متغیرهای محیطی
│
├── mock_demo/                   # دموی آفلاین برای بررسی کامل بدون نیاز به اینترنت و کلید API
│   ├── mock_llm.py              # شبیه‌ساز پاسخ‌های واقعی مدل
│   └── run_mock_demo.py         # اجرای کامل انتهای‌به‌انتهای هر دو پروژه
│
├── pilot/                       # پایلوت مقایسه مدل‌ها و ممیزی انسانی
│   ├── pilot_runner.py          # بنچمارک مقایسه زمان، مصرف توکن و نرخ امتناع مدل‌ها
│   └── pilot_report_template.md # قالب گزارش ارزیابی کیفی انسانی
│
├── examples/                    # داده‌های نمونه استاندارد در قالب‌های CSV، JSON و JSONL
├── tests/                       # مجموعه آزمون‌های جامع واحد و یکپارچگی (۲۸ تست)
├── requirements.txt             # پیش‌نیازهای حداقلی (openpyxl، pytest، python-dotenv)
└── README.md
```

---

## ۳. نصب و راه‌اندازی

سامانه بدون وابستگی‌های سنگین یادگیری عمیق توسعه داده شده است و صرفاً به پایتون ۳.۱۰ به بالا و بسته‌های سبک نیاز دارد:

```bash
# کلون کردن و ورود به پوشه پروژه
cd /home/amirali/projects/translate-offset-data

# نصب بسته‌های مورد نیاز
pip install -r requirements.txt
```

### پیکربندی متغیرهای محیطی (`.env`)
فایل `.env.example` را به عنوان الگو کپی کنید:
```bash
cp persianization/.env.example .env
```
مقادیر درگاه AvalAI و مدل‌های مد نظر را تنظیم کنید:
```dotenv
LLM_API_KEY=your_avalai_api_key_here
LLM_BASE_URL=https://api.avalai.ir/v1

# مدل‌های پروژه A
TRANSLATOR_PRIMARY_MODEL=gpt-4o-mini
TRANSLATOR_FALLBACK_MODELS=claude-haiku-4-5,gemini-2.5-flash,deepseek-chat
QUALITY_MODEL=deepseek-chat

# مدل‌های پروژه B
GENERATOR_MODEL=gpt-4o-mini
WHITE_QUALITY_MODEL=claude-haiku-4-5
OFFENSE_JUDGE_1=gpt-4o-mini
OFFENSE_JUDGE_2=claude-haiku-4-5
OFFENSE_JUDGE_3=gemini-2.5-flash
OFFENSE_JUDGE_4=deepseek-chat
```
> **تذکر امنیتی:** هرگز کلید واقعی API را در کد، مخزن گیت یا لاگ‌ها قرار ندهید.

---

## ۴. راهنمای اجرای پروژه A (فارسی‌سازی دیتاست)

پروژه A متن ورودی را می‌گیرد؛ در صورتی که متن فارسی باشد، مستقیماً وارد خروجی می‌کند؛ در صورتی که انگلیسی باشد، آن را با رعایت سبک و شدت ترجمه کرده و با مدل مستقل ارزیابی می‌کند.

### ۱. اجرای ترجمه و ورود داده:
```bash
python -m persianization.cli run \
  --input examples/sample_persianization_input.csv \
  --output-dir outputs/persianization
```

### ۲. ادامه اجرای متوقف‌شده (Resume):
در صورت قطع شبکه یا وقفه، با اضافه کردن فلگ `--resume` فرآیند از آخرین رکورد تکمیل‌شده در SQLite ادامه می‌یابد:
```bash
python -m persianization.cli run \
  --input examples/sample_persianization_input.csv \
  --output-dir outputs/persianization \
  --resume
```

### ۳. بازبینی انسانی از طریق Excel (HITL):
فایل `outputs/persianization/review.xlsx` را باز کرده و در ستون‌های سبز رنگ (`human_decision`، `human_edited_text`، `human_notes`) تصمیم خود را ثبت کنید (مثلاً `accept`، `reject`، یا `edit`). سپس تغییرات را به پایگاه داده و فایل‌های خروجی اعمال نمایید:
```bash
python -m persianization.cli review-ingest \
  --excel-file outputs/persianization/review.xlsx \
  --output-dir outputs/persianization \
  --reviewer "نام_ارزیاب"
```

### ۴. صدور مجدد خروجی‌ها:
```bash
python -m persianization.cli export --output-dir outputs/persianization
```

### خروجی‌های استاندارد پروژه A:
1. `all_records.jsonl` / `all_records.csv`: کلیه رکوردهای پردازش‌شده با متادیتا کامل.
2. `accepted_persian.jsonl` / `accepted_persian.csv`: متون فارسی پذیرفته‌شده (شامل فارسی بومی و ترجمه‌های تأییدشده؛ ممکن است سالم یا توهین‌آمیز باشند).
3. `native_fa.jsonl` / `native_fa.csv`: متون بومی فارسی که بدون فراخوانی مدل وارد شده‌اند.
4. `accepted_translations.jsonl` / `accepted_translations.csv`: ترجمه‌های باکیفیت تأییدشده توسط ارزیاب کیفیت.
5. `review_queue.csv`: موارد نیازمند بازبینی (نمونه‌های ممیزی انسانی، فینگلیش، موارد با پرچم خطا).
6. `failed_or_unresolved.jsonl`: مواردی که همه مدل‌ها امتناع کرده یا با خطا مواجه شدند.
7. `raw_responses.jsonl`: لاگ تمام تلاش‌ها، پاسخ‌های خام و توکن‌های مصرفی.
8. `summary.json`: خلاصه آماری دقیق، تفکیک برچسب‌ها و مصرف واقعی توکن.
9. `manifest.json`: شناسنامه اجرا، تنظیمات و هش داده‌ها.
10. `review.xlsx`: کاربرگ اکسل همراه با رنگ‌بندی وضعیت و ستون‌های بازبینی انسانی.

---

## ۵. راهنمای اجرای پروژه B (تولید مستقل دادهٔ سالم)

پروژه B تنها با دستور صریح خودش اجرا می‌شود و دادهٔ ورودی فارسی (مانند `accepted_persian.jsonl` از پروژه A) را به عنوان بذر مصرف می‌کند.

### ۱. اجرای تولید سفید:
```bash
python -m white_generation.cli run \
  --input outputs/persianization/accepted_persian.jsonl \
  --output-dir outputs/white_generation \
  --recipes minimal_disambiguation,criticism,hard_negative,ordinary
```

### ۲. الگوهای تولید داده سالم (Recipes):
- `minimal_disambiguation`: رفع ابهام و سوءتفاهم با کمترین تغییر ممکن.
- `criticism`: تبدیل حمله و توهین شخصی به نقد منطقی رفتار، اثر یا استدلال.
- `hard_negative`: تولید متن سالم چالش‌برانگیز با نشانه‌های ظاهری بحث تند یا کلمات حساس، اما با معنای نهایی کاملاً سالم و بدون توهین.
- `ordinary`: تولید گزاره سالم روزمره مرتبط با موضوع بذر.
- `educational`: تبیین آموزشی یا واکاوی پدیده بدون توهین (نیازمند بازبینی انسانی).
- `reported_condemnation`: نقل یا گزارش محکومیت رفتار ناپسند (نیازمند بازبینی انسانی).

### ۳. پنل ۴ داور نابینا و قواعد اجماع:
هر کاندیدای تولیدی توسط ۴ مدل مستقل بدون اطلاع از بذر، الگو یا سایر داوران ارزیابی می‌شود:
- **حداقل ۳ رأی ۰:** کاندیدای سالم (`candidate0`). در صورت اجماع کامل ۴/۰ مستقیماً پذیرفته می‌شود؛ در صورت رأی ۳/۱ برای بازبینی انسانی به صف review می‌رود.
- **حداقل ۳ رأی ۱:** کاندیدای توهین‌آمیز (`candidate1`)؛ رد قطعی و عدم ورود به خروجی سفید.
- **تساوی ۲ به ۲:** وضعیت حل‌نشده و انتقال الزامی به صف بازبینی انسانی (`review_queue`).

### ۴. بازبینی انسانی خروجی‌های سفید:
```bash
python -m white_generation.cli review-ingest \
  --excel-file outputs/white_generation/review.xlsx \
  --output-dir outputs/white_generation \
  --reviewer "نام_ارزیاب"
```

---

## ۶. اجرای دموی آفلاین (بدون نیاز به اینترنت یا کلید API)

برای بررسی صحت نرم‌افزاری و مشاهده تولید خروجی‌های استاندارد به صورت شبیه‌سازی‌شده:
```bash
python3 -m mock_demo.run_mock_demo
```
این اسکریپت هر دو پروژه را به صورت مستقل اجرا کرده، فایل‌های CSV، JSONL و Excel را تولید می‌کند و گزارش کاملی از جریان داده ارائه می‌دهد.

---

## ۷. پایلوت مقایسه تجربی مدل‌ها

برای مقایسه عملکرد مدل‌های مترجم روی AvalAI و استخراج نرخ امتناع، زمان پاسخ، مصرف توکن و خطای شِما:
```bash
python3 -m pilot.pilot_runner \
  --models gpt-4o-mini,claude-haiku-4-5,gemini-2.5-flash,deepseek-chat \
  --output pilot/pilot_results.json
```
*(در صورتی که `LLM_API_KEY` در محیط تنظیم نشده باشد، این ابزار به طور خودکار اخطار داده و از شبیه‌سازی نتایج خودداری می‌کند).*

---

## ۸. اجرای آزمون‌های خودکار (Unit Tests)

سامانه دارای ۲۸ آزمون جامع است که الزامات مطرح‌شده در شیوه‌نامه را ارزیابی می‌کنند:
```bash
python3 -m pytest -v
```

### موارد تحت پوشش آزمون‌ها:
1. ورود مستقیم فارسی بدون تماس با مدل (`test_native_persian_direct_entry`).
2. ترجمه وفادار انگلیسی به فارسی (`test_english_translation_routing`).
3. تفکیک بررسی زبان متن و زبان زمینه (`test_text_context_language_separation`).
4. عدم تبدیل خودکار فینگلیش به فارسی بومی (`test_fingilish_not_treated_as_native_fa`).
5. حفظ ساختار فارسی حاوی وام‌واژه‌های انگلیسی (`test_persian_with_english_loanwords_stays_persian`).
6. حفظ مطلق متن خام، ایموجی‌ها و متادیتا (`test_raw_text_strict_preservation`).
7. تطابق و یکسانی خروجی‌های CSV، JSON و JSONL (`test_format_parity_csv_json_jsonl`).
8. کشف خطاهای ورودی قبل از تماس با API (`test_empty_text_rejected`, `test_duplicate_csv_header_rejected`, ...).
9. شناسایی سانسور یا تلطیف پنهان توسط ارزیاب کیفیت (`test_quality_evaluator_catches_censorship`).
10. الزام به استقلال مدل کیفیت از مدل مترجم (`test_independence_violation_check`).
11. عدم تبدیل خودکار متون مستقیم یا دارای source_label به label0 (`test_native_fa_and_source_label_not_auto_label0`).
12. عدم اشتباه گرفتن عبارت «نمی‌توانم» در متن اصلی با امتناع مدل (`test_cannot_phrase_in_genuine_translation_not_refusal`).
13. فراخوانی مدل جایگزین (Fallback) با متن خام اصلی در صورت امتناع مدل اولیه (`test_fallback_called_when_primary_refuses`).
14. ثبت وضعیت unresolved در صورت شکست تمام مدل‌ها (`test_all_fallbacks_failing_produces_unresolved`).
15. ایمن‌سازی سلول‌های اکسل در برابر تزریق فرمول (`test_excel_formula_sanitization`).
16. مسدودسازی کاندیداهای دارای بار توهین از ورود به خروجی سفید (`test_offensive_candidate_blocked_from_accepted_white`).
17. توقف کاندیداهای با رأی ۳/۱ و تساوی ۲-۲ در صف بازبینی (`test_split_3_1_held_for_review`, `test_tie_2_2_held_for_review`).
18. تمایز صریح عدد '0' وارد شده توسط انسان با سلول خالی (`test_human_review_zero_distinct_from_blank`).
19. مدیریت بودجه و کنترل سقف تماس‌های API (`test_rate_limiter_budget_exceeded`).
20. ردیابی منشأ و هشدار نشت داده میان splitها (`test_family_split_leakage_detection`).
21. دوام اجرا و امکان Resume از پایگاه داده SQLite (`test_sqlite_checkpoint_and_resumption`).

---

## ۹. ملاحظات فنی و محدودیت‌های شناخته‌شده

1. **تشخیص تکرار (Duplicate Detection):** شناسایی تکرارها در این سامانه بر اساس هش دقیق SHA-256 متن خام انجام می‌شود. تکرارهای نزدیک معنایی (Near-duplicates یا Semantic similarity) نیازمند مدول‌های جاسازی (Embeddings) مجزا هستند و تحت پوشش تطابق قطعی قرار نمی‌گیرند.
2. **محدودیت طول سلول اکسل:** حداکثر طول مجاز نمایش یک سلول در نرم‌افزار اکسل ۳۲,۷۶۷ کاراکتر است. برای متون بسیار حجیم، فایل‌های مرجع اصلی همواره نسخه `jsonl` خواهند بود.
3. **ممیزی یک‌نفره:** ویرایش انسانی انجام‌شده از طریق `review-ingest` به منزله یک ممیزی انسانی کنترل‌شده ثبت می‌شود و نباید به عنوان داده طلایی حاصل از اجماع دو ارزیاب مستقل (Double-annotated gold) تلقی شود مگر اینکه پروتکل پایلوت مربوطه اجرا گردد.
