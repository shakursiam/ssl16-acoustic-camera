# SSL-16 ল্যাব গাইড (বাংলা): ধাপে ধাপে পরীক্ষা E0 থেকে E8

এই গাইডটি ল্যাবে দাঁড়িয়ে পড়ে কাজ করার জন্য। বিস্তারিত ব্যাখ্যা, chord টেবিল আর uncertainty budget আছে [test_campaign_plan.md](test_campaign_plan.md) ফাইলে। এখানে শুধু "কী করতে হবে, কোন ক্রমে, কখন থামতে হবে" লেখা।

**সময়সীমা:** ল্যাব ২২ নভেম্বর পর্যন্ত। সময় কম পড়লে এই ক্রমে করুন: E0 → E1 → E6 → E3 → E4 → E2 → E5 → E8 → E7।

**তিনটি নিয়ম যা কখনো ভাঙবেন না**

1. কোনো WAV / JSON / `runs.csv` ফাইল edit, rename বা delete করবেন না। খারাপ run হলে GUI-তে **Flag last bad** চাপুন এবং কারণ লিখুন, তারপর আবার মাপুন।
2. প্রতিদিন E0.5 (orientation check) পাস না করা পর্যন্ত E1–E8-এর কোনো data বৈধ নয়।
3. দিনের শেষে পুরো session ফোল্ডার এবং SD কার্ডের ফাইল দুই জায়গায় কপি করুন (Google Drive + আরেকটি ব্যাকআপ)।

---

## ০. কোন ফাইল কী কাজের

| ফাইল | কাজ |
|---|---|
| `firmware/arduino/SSL16_SelfTest` | বোর্ড ঠিক আছে কি না (I2C, ADC, TDM)। বোর্ড ১-এ আগে পাস করেছে। |
| `firmware/arduino/SSL16_SDTest` | SD কার্ডের গতি মাপে। **এখনো চালানো হয়নি।** |
| `firmware/arduino/SSL16_WavRecorder_v45` | আপনার চালু থাকা recorder (12 kHz)। ব্যাকআপ হিসেবে রাখা, পরিবর্তন করা হয়নি। |
| `firmware/arduino/SSL16_Rec48` | **নতুন।** SD কার্ডে raw 48 kHz, USB-তে আগের মতো 12 kHz। **এখনো compile বা বোর্ডে চালানো হয়নি**, নিচের Day 0 ধাপে যাচাই করতে হবে। |
| `software/python/ssl16_recorder_gui.py` | সহজ recorder GUI, ১৬টি mic-এর level bar দেখায়। Tap test-এ লাগবে। |
| `software/python/ssl16_buzzer_gui.py` | মূল campaign logger। **Measure** চাপলে PC-তে 12 kHz WAV + metadata সেভ হয়, আর বোর্ডকে একই নামে SD-তে 48 kHz ফাইল লিখতে বলে। |
| `software/python/ssl16_analyze.py` | সন্ধ্যার বিশ্লেষণ। |

**কেন দুই রকম ফাইল:** USB (full speed) দিয়ে 16 চ্যানেল × 48 kHz (1.54 MB/s) পাঠানো যায় না, তাই USB-তে 12 kHz যায়। Raw 48 kHz শুধু SD কার্ডে লেখা সম্ভব। পেপারের মূল data হবে SD-র 48 kHz ফাইল; PC-র 12 kHz ফাইল live দেখা আর ব্যাকআপের জন্য।

---

## ১. Day 0: প্রস্তুতি (ল্যাবে যাওয়ার আগে, প্রায় ২ ঘণ্টা)

### ১.১ সফটওয়্যার

PowerShell খুলে:

```powershell
cd "G:\My Drive\Research_2026\SSL-16 Journal\ssl16-acoustic-camera"
git checkout feat/test-campaign-handoff
& "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe" -m pip install -r software\python\requirements.txt
```

Arduino IDE settings (সব sketch-এর জন্য একই): Board = *ESP32S3 Dev Module*, *USB CDC On Boot = Enabled*, *USB Mode = Hardware CDC and JTAG*, *PSRAM = OPI PSRAM*, *Flash Size = 8MB*।

Upload না হলে ("No serial data received"): **BOOT চেপে ধরুন → EN একবার চাপুন → BOOT ছাড়ুন**, upload করুন, শেষে EN চাপুন। Python চালানোর আগে Arduino Serial Monitor বন্ধ করুন।

### ১.২ SD কার্ড পরীক্ষা (বাধ্যতামূলক)

1. কার্ডটি FAT32-এ format করুন, বোর্ডে ঢোকান।
2. `SSL16_SDTest` upload করুন, Serial Monitor খুলুন।
3. **write speed** লিখে রাখুন।
   - **1.6 MB/s-এর বেশি** হলে: 48 kHz recording চলবে।
   - কম হলে: আরেকটি কার্ড (Class 10 / U1 বা ভালো) দিয়ে আবার চেষ্টা করুন। কোনো কার্ডেই না হলে আমাকে সংখ্যাটি জানান; তখন 12 kHz recorder দিয়ে campaign হবে এবং পেপারে সেটাই লেখা হবে।

### ১.৩ নতুন firmware `SSL16_Rec48` যাচাই

1. `firmware/arduino/SSL16_Rec48/SSL16_Rec48.ino` খুলে **Verify** চাপুন।
   - **Compile error এলে upload করবেন না।** পুরো error লেখাটি আমাকে পাঠান। ততক্ষণ `SSL16_WavRecorder_v45` দিয়ে কাজ চালানো যাবে।
2. Compile হলে upload করুন, EN চাপুন। LED সবুজ blink = streaming।
3. Recorder GUI চালান:
   ```powershell
   cd software\python
   & "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe" ssl16_recorder_gui.py
   ```
   COM19 connect করুন। ১৬টি bar নড়ছে এবং status-এ `sd=ok` দেখাচ্ছে কি না দেখুন।
4. একটি **৩০ সেকেন্ডের** পরীক্ষামূলক run রেকর্ড করুন (নাম দিন `test48`), তারপর stop করুন। LED লাল blink = recording।
5. Status লাইনে তিনটি সংখ্যা দেখুন, তিনটিই **0** থাকতে হবে: `ring_drop`, `sd_err`, `i2s_ovf`।
6. কার্ড বের করে PC-তে `/ssl16/test48.wav`, `test48.txt`, `test48_temp.csv` কপি করুন। `test48.txt`-এ থাকা উচিত: `fs_hz=48000`, `samples_per_channel` ≈ 1,440,000 (৩০ সেকেন্ড), `ring_dropped_blocks=0`, `i2s_overflows_during_run=0`।
7. **এই তিনটি ফাইল আমাকে দিন** (Journal ফোল্ডারে `day0_test/` নামে রাখলেই হবে)। আমি চ্যানেল, sample সংখ্যা, clipping আর চ্যানেল-ক্রম পরীক্ষা করে জানাব। এটি পাস না করা পর্যন্ত আসল data নেওয়া শুরু করবেন না।

`ring_drop` শূন্য না হলে: কার্ড ধীর। `i2s_ovf` শূন্য না হলে: firmware-এ সমস্যা, আমাকে জানান।

### ১.৪ Tap test (slot map যাচাই, এখনো করা হয়নি)

উদ্দেশ্য: প্রতিটি mic ঠিক নিজের চ্যানেলেই আসছে কি না। এটি claim C1-এর ভিত্তি।

1. Recorder GUI খোলা রাখুন (bar গুলো M1…M16 ক্রমে)। ঘর শান্ত রাখুন।
2. বোর্ডের sound-hole পাশে M1-এর ছিদ্রের ঠিক পাশে নখ বা কলমের ডগা দিয়ে হালকা আঁচড় দিন (ছিদ্র ঢাকবেন না, কিছু ঢোকাবেন না)।
3. শুধু M1-এর bar সবচেয়ে বেশি লাফাবে। পাশের mic সামান্য নড়তে পারে, কিন্তু সর্বোচ্চ হবে M1।
4. M2 থেকে M16 পর্যন্ত একইভাবে করুন। একটি কাগজে লিখুন: "আঁচড় দিলাম Mn → সর্বোচ্চ bar Mk"।
5. পুরো test চলাকালে একটি run রেকর্ড করুন (নাম `taptest`), মুখে বলুন "এম ওয়ান", "এম টু"… যাতে পরে ফাইল থেকে যাচাই করা যায়।

**পাস:** ১৬টিতেই n = k। কোনোটি না মিললে থামুন এবং টেবিলটি আমাকে পাঠান; mic টেবিল ঠিক না করে localization করলে সব কোণ ভুল আসবে।

Mic-এর অবস্থান চেনার জন্য [microphone_array.md](microphone_array.md)-এর টেবিল দেখুন (M1 কেন্দ্রের কাছে, M16 সবচেয়ে বাইরে নিচের দিকে)।

### ১.৫ সরঞ্জাম

বোর্ড ২টি, ল্যাপটপ + USB-C কেবল, tripod ২টি, বোর্ড ধরার plate (কোনো sound hole ঢাকবে না), buzzer ৩টি (প্রায় 2.3, 2.8, 4 kHz), ছোট speaker ২টি, sound level meter, laser distance meter, 5 m স্টিল টেপ, masking tape, chalk line, plumb bob, inclinometer, thermometer/hygrometer, power bank, SD কার্ড (পরীক্ষিত) + card reader, ফোন ক্যামেরা।

---

## ২. Setup A তৈরি (camera mode, বোর্ড খাড়া)

1. ল্যাবের সবচেয়ে ফাঁকা জায়গা বাছুন: বোর্ডের সামনে কমপক্ষে 3 m, দুই পাশে দেয়াল থেকে 1 m।
2. বোর্ড tripod-এ লাগান। **বোর্ডের কেন্দ্র মেঝে থেকে 1.20 m।** Inclinometer দিয়ে face খাড়া (±0.5°) এবং x-অক্ষ সমতল করুন।
3. বোর্ডের কেন্দ্র থেকে plumb bob ঝুলিয়ে মেঝেতে বিন্দু **O** চিহ্ন দিন।
4. O থেকে বোর্ডের face-এর লম্ব বরাবর chalk line টানুন (এটিই 0° রেখা)। এই রেখায় O থেকে **2.00 m** দূরে বিন্দু **R** চিহ্ন দিন।
5. প্রতিটি কোণের বিন্দু P: O থেকে দূরত্ব 2.00 m **এবং** R থেকে chord দূরত্ব c = 2r·sin(θ/2)। r = 2.0 m-এর জন্য:

   | θ | 10° | 20° | 30° | 40° | 50° | 60° | 70° | 80° | 90° |
   |---|---|---|---|---|---|---|---|---|---|
   | chord (cm) | 34.9 | 69.5 | 103.5 | 136.8 | 169.0 | 200.0 | 229.4 | 257.1 | 282.8 |

   রেখার দুই পাশেই একই মান। প্রতিটি বিন্দুতে masking tape লাগিয়ে ID লিখুন (যেমন `P+30`, `P-30`)।
6. Source (buzzer) দ্বিতীয় tripod-এ, উচ্চতা 1.20 m, sound hole বোর্ডের কেন্দ্রের দিকে।
7. **ছবি তুলুন:** পুরো bench, tape চিহ্নসহ, এবং বোর্ডের mount। পেপারের Fig. 4-এ লাগবে।

**+θ কোন দিকে:** বোর্ডের +x দিক যে পাশে, সেই পাশের বিন্দুগুলো +θ। কোন পাশ +x তা E0.5-এ শব্দ দিয়ে নিশ্চিত হবে; আগে থেকে ধরে নেবেন না।

---

## ৩. Campaign GUI চালানো (সব পরীক্ষায় একই)

```powershell
cd "G:\My Drive\Research_2026\SSL-16 Journal\ssl16-acoustic-camera\software\python"
& "C:\Users\HP\AppData\Local\Programs\Python\Python313\python.exe" ssl16_buzzer_gui.py
```

1. **Session dialog:** base folder দিন `G:\My Drive\Research_2026\SSL-16 Journal\ssl16_campaign` (repo-র বাইরে, যাতে audio git-এ না যায়)। room, board (`board1`), operator, humidity, background dB(A), firmware (`SSL16_Rec48`) লিখুন।
2. **Connect** → COM19। সবুজ লেখায় `SSL6 12000 Hz | packets … | gaps 0` দেখাবে।
3. **Settings:** temperature-এ thermometer-এর মান দিন। flip x / flip y শুধু E0.5-এ ঠিক করবেন, তারপর আর বদলাবেন না।
4. প্রতিটি বিন্দুর জন্য: setup (A/B), range, angle, source height, board height লিখুন → experiment ID, point ID, source নাম লিখুন → source চালু করে ২ সেকেন্ড অপেক্ষা → **Measure**। একই বিন্দুতে মোট ৩ বার (rep আপনাআপনি বাড়ে)।
5. Measure শেষে সতর্কবার্তা এলে পড়ুন:
   - "detections only …%" বা "spread …°": বিন্দুটি একবার আবার মাপুন।
   - "USB gaps": USB কেবল/পোর্ট দেখুন।
   - **"board did NOT confirm the SD recording"**, **"SD too slow"**, **"I2S overflow"**: এই run-এর 48 kHz ফাইল নির্ভরযোগ্য নয়। **Flag last bad** চাপুন, কারণ ঠিক করে আবার মাপুন।
6. মাপার সময়: কেউ কথা বলবে না, হাঁটবে না। Operator বোর্ডের পেছনে কমপক্ষে 1 m দূরে। দরজা বন্ধ, ফ্যান বন্ধ (বন্ধ করা না গেলে notes-এ লিখুন)।
7. **প্রতি ১০ বিন্দু পর** control point (θ = 0°) আবার মাপুন। দিনের শুরুর মান থেকে 1°-এর বেশি সরলে থামুন, কী নড়েছে খুঁজুন।
8. বিন্দুগুলো বাঁ থেকে ডানে ক্রমে নয়, **Shuffle order** দিয়ে এলোমেলো ক্রমে মাপুন।

**দিনের শেষে:**

1. GUI বন্ধ করুন (recording চালু থাকলে আগে stop)। বোর্ডের power খোলার আগে নিশ্চিত হোন LED লাল blink করছে না।
2. SD কার্ডের `/ssl16/` ফোল্ডারের সব ফাইল session ফোল্ডারের ভেতরে `sd_raw\` নামে একটি ফোল্ডারে কপি করুন। **নাম বদলাবেন না।** কপি যাচাই না করে কার্ড মুছবেন না।
3. পুরো session ফোল্ডার দ্বিতীয় জায়গায় ব্যাকআপ করুন।
4. আমাকে বলুন "আজকের session কপি হয়েছে"; আমি integrity check আর coverage টেবিল চালিয়ে জানাব কোন বিন্দু আবার নিতে হবে।

---

## ৪. E0: Calibration ও characterization (প্রতিদিন শুরুতে, Setup A)

প্রথম দিন প্রায় ১.৫ ঘণ্টা; পরের দিনগুলোতে E0.1, E0.2, E0.5 (২০ মিনিট)। GUI-তে experiment = `E0`, point = নিচের ID।

| ধাপ | Point ID | কী করবেন | পাস / নোট |
|---|---|---|---|
| E0.1 পরিবেশ | `ENV` | তাপমাত্রা, আর্দ্রতা, background dB(A) session-এ লিখুন। বোর্ড থেকে 2 m দূরে একটি বেলুন ফাটান (বা জোরে তালি), ১০ সেকেন্ড Measure। | এই recording থেকে RT60 বের হবে। |
| E0.2 Noise floor | `NOISE` | সব source বন্ধ, ঘর নিঃশব্দ, **৩০ সেকেন্ড** Measure। | আগের মান: সব চ্যানেল −72 থেকে −78 dBFS। |
| E0.3 Channel calibration | `CAL_1000` … `CAL_5000` | Speaker θ = 0°, উচ্চতা 1.20 m, r = 2 m। 1000 থেকে 5000 Hz, 500 Hz ধাপে tone বাজান, প্রতিটি ৩ সেকেন্ড Measure। | Clipping হবে না; level bar −20 থেকে −40 dBFS-এর মধ্যে রাখুন। |
| E0.4 Source | `SRC_<নাম>` | প্রতিটি buzzer বোর্ড থেকে 0.3 m দূরে, ৫ সেকেন্ড Measure। SLM দিয়ে 1 m-এ SPL মাপুন, notes-এ লিখুন। | প্রতিটি buzzer-এর আসল frequency এখান থেকে আসবে। |
| **E0.5 Orientation** | `ORI_T45`, `ORI_P30` | (ক) source θ = +45° বিন্দুতে, উচ্চতা 1.20 m। (খ) source θ = 0°, r = 1.5 m, উচ্চতা 2.07 m (φ ≈ +30°)। | নিচে দেখুন। |
| E0.6 Boresight | `BORE` | Source θ = 0°, ৩ × ১০ সেকেন্ড। | গড় θ যদি ±1°-এর বাইরে হয়: বোর্ড ঘুরিয়ে ঠিক করুন, software-এ নয়। |
| E0.7 Real-time | `RT10` | Source চালু রেখে ১০ মিনিট একটানা। GUI-র packets আর gaps সংখ্যা শুরুতে ও শেষে লিখুন। | শুধু প্রথম দিন। |

**E0.5 কীভাবে পাস করবেন (এখনো করা হয়নি, তাই প্রথম দিন সবচেয়ে জরুরি):**

1. Source +45° বিন্দুতে রাখুন। GUI-র estimate-এ θ দেখুন।
   - প্রায় **+45°** এলে ঠিক আছে।
   - প্রায় **−45°** এলে Settings-এ **flip x** টগল করুন, আবার মাপুন।
2. Source ওপরে (φ ≈ +30°) রাখুন। GUI-র φ দেখুন।
   - **ধনাত্মক** এলে ঠিক আছে। ঋণাত্মক এলে **flip y** টগল করুন, আবার মাপুন।
3. দুটোই ঠিক হলে চূড়ান্ত flip x / flip y / rot মান session notes-এ লিখুন। **এরপর পুরো campaign-এ এই মান বদলাবেন না।**
4. θ বা φ যদি 45° / 30° থেকে অনেক দূরে হয় (যেমন 20°-এর বেশি ভুল) এবং flip দিয়েও না মেলে: থামুন, tap test-এর ফল আর এই দুই run আমাকে দিন।

**A2-এর জন্য বাড়তি কাজ (ল্যাব বন্ধ হওয়ার আগে অবশ্যই):**

- একটি reference thermometer বোর্ডের পাশে রেখে তার মান আর GUI/status-এর `temp` একই সময়ে লিখুন, দিনে অন্তত দুবার।
- দুটি স্পষ্ট আলাদা ঘরের তাপমাত্রায় (যেমন AC চালু করে ~22 °C এবং AC বন্ধ রেখে ~30 °C) E1-এর ৫টি বিন্দু (θ = 0, ±30, ±60°) মাপুন। experiment ID দিন `A2`।
- আর্দ্রতা প্রতিবার লিখুন; আর্দ্রতাও শব্দের গতি সামান্য বদলায়।

---

## ৫. E1: Bearing sweep (মূল ফলাফল, Setup A, প্রায় ২ ঘণ্টা)

- **স্থির:** r = 2.0 m, source উচ্চতা 1.20 m (φ = 0°), 2.8 kHz buzzer।
- **বদলাবে:** θ = −90° থেকে +90°, 10° ধাপে (১৯টি বিন্দু)। Point ID: `P-90` … `P+90`।
- **বাড়তি:** অন্য দুই buzzer দিয়ে θ = 0, ±30, ±60, ±90° (৭ × ২ = ১৪টি বিন্দু)। Source নাম আলাদা দিন।
- প্রতিটি বিন্দু ৩ × ৫ সেকেন্ড, এলোমেলো ক্রমে, প্রতি ১০ বিন্দু পর control point।

**শেষ হয়েছে যখন:** ৩৩ বিন্দু × ৩ = ৯৯টি run সেভ হয়েছে এবং কোনোটিতে SD সতর্কবার্তা নেই।

---

## ৬. E6: SNR (Setup A, প্রায় ১ ঘণ্টা)

- **Source:** 2.8 kHz buzzer, θ = +30°, r = 2 m।
- **Noise:** দ্বিতীয় speaker-এ pink noise, θ = −45°, r = 2 m।
- **ধাপ:**
  1. শুধু source চালু, ১০ সেকেন্ড Measure (point `SRC_ONLY`)।
  2. শুধু noise, প্রতিটি noise level-এ ১০ সেকেন্ড (point `N_ONLY_L1` … )। এগুলো থেকেই আসল in-band SNR হিসাব হবে।
  3. দুটো একসাথে, noise-এর volume বাড়িয়ে SNR আনুমানিক +30, +20, +10, +5, 0, −5 dB। প্রতিটি ৩ × ১০ সেকেন্ড (point `SNR+30` …)।
- SLM-এর মান প্রতিটি level-এ notes-এ লিখুন। Speaker-এর volume knob-এর অবস্থান চিহ্ন দিয়ে রাখুন, যাতে `N_ONLY` আর মিশ্র run-এ একই level হয়।

---

## ৭. E3: 360° sweep (Setup B, বোর্ড শোয়ানো, প্রায় ২ ঘণ্টা)

1. বোর্ড face ওপরে রেখে stand-এ, standoff-এর ওপর, **উচ্চতা 1.00 m**। Inclinometer দিয়ে সমতল করুন।
2. Plumb bob দিয়ে O চিহ্ন দিন। বোর্ডের **+x দিক বরাবর** 0° রেখা টানুন, তাতে 1.5 m দূরে R।
3. 1.5 m ব্যাসার্ধের বৃত্তে 15° পরপর ২৪টি বিন্দু। chord (cm), r = 1.5 m: 15° → 39.2, 30° → 77.6, 45° → 114.8, 60° → 150.0, 75° → 182.6, 90° → 212.1, 105° → 238.0, 120° → 259.8, 135° → 277.2, 150° → 289.8, 165° → 297.4, 180° → 300.0।
4. **নতুন setup, তাই E0.5 আবার:** source α = +45° এবং α = +135°-তে রেখে estimate একই পাশে আসছে কি না দেখুন।
5. মাপুন: elevation 15° (source বোর্ডের 0.40 m ওপরে, অর্থাৎ মেঝে থেকে 1.40 m) এ ২৪টি বিন্দু; elevation 40° (বোর্ডের 1.26 m ওপরে, মেঝে থেকে 2.26 m) এ 30° পরপর ১২টি বিন্দু। GUI-তে setup = B।
6. Source সবসময় বোর্ডের **ওপরে** থাকবে, নিচে নয়।

---

## ৮. E4: Distance (Setup A, প্রায় ১ ঘণ্টা)

- r = 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0 m (ঘরে জায়গা থাকলে 5.0 m)। θ = 0° এবং 45°।
- Source: speaker-এ 2.8 kHz tone। **প্রতিটি দূরত্বে SLM বোর্ডের কাছে ধরে speaker-এর volume এমনভাবে ঠিক করুন যাতে বোর্ডে SPL একই থাকে (±1 dB)।** SPL notes-এ লিখুন।
- 45°-এর বিন্দুগুলোর chord: c = 2r·sin(22.5°) = 0.765 × r।
- Laser meter দিয়ে প্রতিটি দূরত্ব মেপে GUI-তে আসল মান লিখুন।

---

## ৯. E2: Vertical sweep (Setup A, প্রায় ১.৫ ঘণ্টা)

- Horizontal range 1.5 m; θ = 0°, +45°, −45°।
- Source উচ্চতা: 0.33, 0.80, 1.20, 1.60, 2.07, 2.46 m (φ = −30, −15, 0, +15, +30, +40°)।
- প্রতিবার laser meter দিয়ে উচ্চতা মেপে GUI-তে আসল মান দিন। উঁচু বিন্দুতে tripod নড়বড়ে হলে notes-এ লিখুন।

---

## ১০. E5: Frequency ও source (Setup A, প্রায় ১.৫ ঘণ্টা)

- r = 2.0 m; θ = 0°, +30°, +60°।
- Source: speaker tone 1.0, 1.5, 2, 3, 4, 5 kHz; তিনটি buzzer; গাড়ির হর্নের recording; white-noise burst।
- 1 kHz tone আর হর্নের জন্য GUI band-এর low = 800 Hz করুন, **পরে আবার 1500 Hz-এ ফেরান**। প্রতিটি run-এ কোন band ছিল তা GUI নিজেই সেভ করে।

---

## ১১. E8: Repeatability (Setup A, প্রায় ১ ঘণ্টা)

- **E8a (পরের দিন):** বোর্ড tripod থেকে খুলে আবার লাগান, alignment নতুন করে করুন। θ = 0, ±45, +90° মাপুন।
- **E8b (বোর্ড ২):** বোর্ড ২-এ আগে `SSL16_SelfTest`, তারপর `SSL16_Rec48`। Session-এ board = `board2`। নিজস্ব E0.2, E0.3, E0.5 করুন, তারপর θ = −60 থেকে +60°, 30° ধাপে।

---

## ১২. E7: Environment (প্রায় ২ ঘণ্টা)

- করিডোর এবং খোলা জায়গা (ছাদ বা মাঠ)। প্রতিটিতে নতুন session (room নাম আলাদা)।
- প্রতিটি জায়গায় আগে E0.1 (বেলুন) আর E0.5, তারপর θ = −60 থেকে +60°, 30° ধাপে, r = 2 m, 2.8 kHz buzzer।
- বাইরে বাতাস বেশি হলে মাপবেন না; বাতাসের অবস্থা notes-এ লিখুন।

---

## ১৩. প্রতিদিন আমাকে যা জানাবেন

1. আজ কোন পরীক্ষা হলো, session ফোল্ডারের নাম।
2. তাপমাত্রা, আর্দ্রতা, reference thermometer বনাম বোর্ডের `temp`।
3. E0.5-এর চূড়ান্ত flip মান (প্রথম দিন)।
4. কোনো সতর্কবার্তা বা অস্বাভাবিক ঘটনা।

এরপর আমি integrity check, coverage টেবিল আর সেদিনের error-vs-angle plot চালিয়ে জানাব কোন বিন্দু পরদিন আবার নিতে হবে।
