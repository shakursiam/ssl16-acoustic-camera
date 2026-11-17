// SSL-16 Rev A — board self-test
// Arduino IDE, board "ESP32S3 Dev Module", core 3.x (ESP-IDF 5.x)
// Settings: USB CDC On Boot = Enabled, PSRAM = OPI PSRAM, Flash = 8MB
// Open Serial Monitor at 115200. Each stage prints PASS / FAIL.

#include <Wire.h>
#include <string.h>
#include <math.h>
#include "driver/i2s_tdm.h"

// ---------- pins ----------
#define PIN_SDA    8
#define PIN_SCL    9
#define PIN_SHDNZ  11
#define PIN_LED    48
#define PIN_BCLK   6    // BCLK_Y3 from LMK1C1104
#define PIN_FSYNC  7
#define PIN_DIN    13   // I2S_DIN from U1

// ---------- audio ----------
#define FS          48000   // if I2S init fails, set 24000
#define NSLOT       16
#define FRAMES      480     // 10 ms per read

const uint8_t ADC_ADDR[4] = {0x4C, 0x4D, 0x4E, 0x4F};  // U1..U4 (U4 = controller)
const uint8_t TMP_ADDR = 0x48;
const char* SLOT_MIC[16] = {"MK2","MK7","MK10","MK15","MK1","MK4","MK9","MK12",
                            "MK3","MK6","MK11","MK14","MK5","MK8","MK13","MK16"};

i2s_chan_handle_t rx = NULL;
static int16_t buf[FRAMES * NSLOT];
bool adcOK = false, i2sOK = false;

// ---------- I2C helpers ----------
bool wr(uint8_t a, uint8_t r, uint8_t v) {
  Wire.beginTransmission(a); Wire.write(r); Wire.write(v);
  return Wire.endTransmission() == 0;
}
int rd(uint8_t a, uint8_t r) {
  Wire.beginTransmission(a); Wire.write(r);
  if (Wire.endTransmission(false) != 0) return -1;
  if (Wire.requestFrom(a, (uint8_t)1) != 1) return -1;
  return Wire.read();
}
bool present(uint8_t a) { Wire.beginTransmission(a); return Wire.endTransmission() == 0; }

// write + read back; counts mismatches
int errs = 0;
void wv(uint8_t a, uint8_t r, uint8_t v) {
  if (!wr(a, r, v) || rd(a, r) != v) {
    Serial.printf("   reg 0x%02X @0x%02X: wrote 0x%02X read 0x%02X\n", r, a, v, rd(a, r));
    errs++;
  }
}

void pass(const char* s, bool ok) { Serial.printf("[%s] %s\n", ok ? "PASS" : "FAIL", s); }

// ---------- stages ----------
void testPsram() {
  uint32_t p = ESP.getPsramSize();
  Serial.printf("PSRAM %u bytes\n", p);
  pass("PSRAM ~8 MB", p > 7000000);
}

bool testI2C() {
  Serial.println("I2C scan:");
  int n = 0;
  for (uint8_t a = 1; a < 127; a++) if (present(a)) { Serial.printf("  found 0x%02X\n", a); n++; }
  bool ok = present(TMP_ADDR);
  for (int i = 0; i < 4; i++) {
    bool p = present(ADC_ADDR[i]);
    if (!p) Serial.printf("  MISSING U%d (0x%02X)\n", i + 1, ADC_ADDR[i]);
    ok &= p;
  }
  if (!present(TMP_ADDR)) Serial.println("  MISSING TMP112 (0x48)");
  pass("I2C: 0x48, 0x4C-0x4F all present", ok);
  return ok;
}

void testTemp() {
  Wire.beginTransmission(TMP_ADDR); Wire.write(0x00);
  if (Wire.endTransmission(false) == 0 && Wire.requestFrom(TMP_ADDR, (uint8_t)2) == 2) {
    int16_t raw = (Wire.read() << 8) | Wire.read();
    float t = (raw >> 4) * 0.0625f;
    Serial.printf("TMP112 = %.2f C\n", t);
    pass("TMP112 reading 10-50 C", t > 10 && t < 50);
  } else pass("TMP112 read", false);
}

// Register values from the bring-up plan, Phase 5 — verify against the datasheet
void configADCs() {
  errs = 0;
  uint8_t fsCode = (FS == 48000) ? 0x48 : 0x28;   // MST_CFG1: FS rate | BCLK = 256*fs
  for (int i = 0; i < 4; i++) {
    uint8_t a = ADC_ADDR[i];
    wr(a, 0x00, 0x00);          // page 0
    wr(a, 0x02, 0x81);          // SLEEP_CFG: wake, internal AREG
  }
  delay(2);
  for (int i = 0; i < 4; i++) {
    uint8_t a = ADC_ADDR[i];
    bool ctrl = (i == 3);
    wv(a, 0x07, 0x01);                          // ASI_CFG0: TDM, 16-bit
    wv(a, 0x08, (i == 0) ? 0xA1 : 0x81);        // ASI_CFG1
    if (!ctrl) wv(a, 0x09, 0x80);               // ASI_CFG2: daisy chain
    if (ctrl) {
      wv(a, 0x13, 0xA0);                        // MST_CFG0: controller
      wv(a, 0x14, fsCode);                      // MST_CFG1
      wv(a, 0x16, 0xD8);                        // CLK_SRC
      wv(a, 0x21, 0xA0);                        // GPIO1 = MCLK in
    } else {
      wv(a, 0x13, 0x00);                        // target
      wv(a, 0x21, 0xB0);                        // GPIO1 = daisy in
    }
    wv(a, 0x3B, 0x00);                          // BIAS_CFG: MICBIAS ~2.75 V (NEVER AVDD)
    wv(a, 0x3C, 0x04); wv(a, 0x41, 0x04);       // CH1..CH4 CH_CFG0
    wv(a, 0x46, 0x04); wv(a, 0x4B, 0x04);
    wv(a, 0x74, 0xF0);                          // CH1..CH4 enabled
  }
  wr(ADC_ADDR[3], 0x75, 0xC0);                  // U4 power-up first -> clocks start
  delay(5);
  for (int i = 0; i < 3; i++) wr(ADC_ADDR[i], 0x75, 0xE0);
  delay(20);
  pass("ADC register write/readback", errs == 0);

  bool ok = true;
  for (int i = 0; i < 4; i++) {
    int asi = rd(ADC_ADDR[i], 0x15), s0 = rd(ADC_ADDR[i], 0x76), s1 = rd(ADC_ADDR[i], 0x77);
    Serial.printf("  U%d  ASI_STS=0x%02X  DEV_STS0=0x%02X  DEV_STS1=0x%02X\n", i + 1, asi, s0, s1);
    if (i < 3 && asi != fsCode) ok = false;    // targets must detect fs + ratio
    if (s0 != 0xF0) ok = false;                 // 4 channels powered
  }
  pass("ADCs see clocks and are powered (check MICBIAS TPs ~2.75 V now)", ok);
  adcOK = (errs == 0) && ok;
}

bool startI2S(bool shift, int inv, bool quiet);

// median per-slot RMS (dBFS) and number of clipping slots over ~100 ms
float measure(int* clipSlots) {
  size_t got;
  for (int k = 0; k < 5; k++) i2s_channel_read(rx, buf, sizeof(buf), &got, 200);  // flush
  float db[NSLOT]; int clip = 0;
  if (i2s_channel_read(rx, buf, sizeof(buf), &got, 200) != ESP_OK || got == 0) { *clipSlots = 99; return 0; }
  int frames = got / (2 * NSLOT);
  for (int s = 0; s < NSLOT; s++) {
    double sum = 0, sq = 0; int pk = 0;
    for (int f = 0; f < frames; f++) { int v = buf[f * NSLOT + s]; sum += v; if (abs(v) > pk) pk = abs(v); }
    double dc = sum / frames;
    for (int f = 0; f < frames; f++) { double x = buf[f * NSLOT + s] - dc; sq += x * x; }
    db[s] = 20 * log10((sqrt(sq / frames) + 1e-9) / 32768.0);
    if (pk >= 32767) clip++;
  }
  for (int i = 1; i < NSLOT; i++) for (int j = i; j > 0 && db[j] < db[j - 1]; j--) { float t = db[j]; db[j] = db[j - 1]; db[j - 1] = t; }
  *clipSlots = clip;
  return (db[7] + db[8]) / 2;
}

void stopI2S() { if (rx) { i2s_channel_disable(rx); i2s_del_channel(rx); rx = NULL; } }

// Try bit_shift x bclk_inv; keep the quietest (correct alignment = low noise floor)
bool findAlignment() {
  Serial.println("Alignment search (keep the room quiet):");
  Serial.println("  bit_shift bclk_inv  median dBFS  clipping slots");
  float best = 1e9; bool bS = true; int bI = 0; bool any = false;
  for (int s = 1; s >= 0; s--) for (int inv = 0; inv <= 1; inv++) {
    if (!startI2S(s, inv, true)) { Serial.printf("  %d         %d         init failed\n", s, inv); continue; }
    int clip; float m = measure(&clip);
    Serial.printf("  %d         %d         %7.1f      %d\n", s, inv, m, clip);
    if (clip < 99 && m < best) { best = m; bS = s; bI = inv; any = true; }
    stopI2S();
  }
  if (!any) return false;
  Serial.printf("Using bit_shift=%d bclk_inv=%d (median %.1f dBFS)\n", bS, bI, best);
  pass("Noise floor below -40 dBFS (quiet room)", best < -40);
  return startI2S(bS, bI, false);
}

bool startI2S(bool shift, int inv, bool quiet) {
  const uint32_t divs[] = {8, 6, 4};
  for (uint32_t d : divs) {
    i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_SLAVE);
    cc.dma_desc_num = 8; cc.dma_frame_num = FRAMES;
    if (i2s_new_channel(&cc, NULL, &rx) != ESP_OK) return false;

    i2s_tdm_config_t t; memset(&t, 0, sizeof(t));
    t.clk_cfg.sample_rate_hz = FS;
    t.clk_cfg.clk_src = I2S_CLK_SRC_DEFAULT;
    t.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
    t.clk_cfg.bclk_div = d;
    t.slot_cfg.data_bit_width = I2S_DATA_BIT_WIDTH_16BIT;
    t.slot_cfg.slot_bit_width = I2S_SLOT_BIT_WIDTH_16BIT;
    t.slot_cfg.slot_mode = I2S_SLOT_MODE_STEREO;
    t.slot_cfg.slot_mask = (i2s_tdm_slot_mask_t)0xFFFF;
    t.slot_cfg.ws_width = 1;          // short FSYNC pulse
    t.slot_cfg.ws_pol = true;
    t.slot_cfg.bit_shift = shift;     // true = data 1 BCLK after FSYNC
    t.slot_cfg.total_slot = NSLOT;
    t.gpio_cfg.mclk = I2S_GPIO_UNUSED;
    t.gpio_cfg.bclk = (gpio_num_t)PIN_BCLK;
    t.gpio_cfg.ws   = (gpio_num_t)PIN_FSYNC;
    t.gpio_cfg.dout = I2S_GPIO_UNUSED;
    t.gpio_cfg.din  = (gpio_num_t)PIN_DIN;
    t.gpio_cfg.invert_flags.bclk_inv = inv;

    if (i2s_channel_init_tdm_mode(rx, &t) == ESP_OK && i2s_channel_enable(rx) == ESP_OK) {
      if (!quiet) Serial.printf("I2S TDM slave up: fs=%d, bclk_div=%u\n", FS, d);
      return true;
    }
    i2s_del_channel(rx); rx = NULL;
  }
  if (!quiet) Serial.println("I2S init failed at this fs -> set FS to 24000 and re-upload");
  return false;
}

// ---------- main ----------
void setup() {
  Serial.begin(115200);
  delay(2000);
  pinMode(PIN_LED, OUTPUT);
  Serial.println("\n===== SSL-16 self-test =====");

  testPsram();

  pinMode(PIN_SHDNZ, OUTPUT); digitalWrite(PIN_SHDNZ, HIGH);   // ADCs out of shutdown
  delay(10);
  Wire.begin(PIN_SDA, PIN_SCL, 100000);                         // long bus -> 100 kHz

  if (testI2C()) {
    testTemp();
    configADCs();
    i2sOK = findAlignment();
    pass("I2S start", i2sOK);
  }
  Serial.println("\nLive levels below (1/s). Scratch near one mic: only its slot should jump.");
}

void loop() {
  static uint32_t t0 = 0;
  digitalWrite(PIN_LED, (millis() / 250) & 1);   // heartbeat

  if (!i2sOK) { delay(50); return; }

  size_t got = 0;
  if (i2s_channel_read(rx, buf, sizeof(buf), &got, 200) != ESP_OK || got == 0) {
    if (millis() - t0 > 1000) { t0 = millis(); Serial.println("no I2S data (check BCLK_Y3 / FSYNC at IO6 / IO7)"); }
    return;
  }
  if (millis() - t0 < 1000) return;
  t0 = millis();

  int frames = got / (2 * NSLOT);
  Serial.println("slot mic    RMS dBFS   DC     peak   status");
  for (int s = 0; s < NSLOT; s++) {
    double sum = 0, sq = 0; int pk = 0;
    for (int f = 0; f < frames; f++) {
      int v = buf[f * NSLOT + s];
      sum += v; if (abs(v) > pk) pk = abs(v);
    }
    double dc = sum / frames;
    for (int f = 0; f < frames; f++) { double x = buf[f * NSLOT + s] - dc; sq += x * x; }
    double rms = sqrt(sq / frames);
    double db = 20 * log10((rms + 1e-9) / 32768.0);
    const char* st = (rms < 1.0) ? "DEAD/constant" : (pk >= 32767) ? "CLIPPING" : "ok";
    Serial.printf("%2d   %-5s  %7.1f  %6.0f  %6d   %s\n", s, SLOT_MIC[s], db, dc, pk, st);
  }
  Serial.println();
}
