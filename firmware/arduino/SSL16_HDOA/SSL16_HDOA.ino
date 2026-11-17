// SSL-16 Rev D — HDOA-protocol firmware for hdoa_pcb_verify.py
//
// This board has ONE daisy chain (U4->U3->U2->U1 -> IO13, 16 TDM slots), not the two-port Rev C1 wiring the
// script was written for. Stream channels 0..7 play the role of "port A" and 8..15 of "port B"; both come from
// the same I2S frame, so port_b_shift is always 0.
//
// Arduino IDE: "ESP32S3 Dev Module", core 3.x, USB CDC On Boot = Enabled, PSRAM = OPI PSRAM.
// Close the Serial Monitor before running the Python script: the port carries binary packets only.
//
// Protocol (all little endian):
//   data   : 'HDOA' | u32 seq | u64 first_frame | u16 n_frames | u16 n_ch(16) | u16 flags | u16 0 | i16 data[n_frames][16]
//            flags bit0 = I2S DMA overflow since the last packet, bit1 = packet(s) dropped because USB was too slow
//   status : 'HDST' | u16 len | JSON
//   commands (text lines): START, STOP, STATUS, REGDUMP n (n = 1..4 -> I2C 0x4C..0x4F)

#include <Wire.h>
#include <string.h>
#include "driver/i2s_tdm.h"

// ---- output rate: must match FS in hdoa_pcb_verify.py ----
#define FS_OUT     24000              // 24000 (script default) or 12000 if the link stage reports pool_drops

#define PIN_SDA    8
#define PIN_SCL    9
#define PIN_SHDNZ  11
#define PIN_LED    48
#define PIN_BCLK   6
#define PIN_FSYNC  7
#define PIN_DIN    13

#define FS_IN      48000
#define DECIM      (FS_IN / FS_OUT)
#define NCH        16
#define FRAMES     480                // input frames per I2S read (10 ms)
#define NOUT       (FRAMES / DECIM)   // output frames per read: 240 @ 24 kHz, 120 @ 12 kHz
#define PKT_FR     120                // frames per packet
#define HDR_LEN    24

// alignment found by the self-test on this board
#define I2S_BIT_SHIFT true
#define I2S_BCLK_INV  1

#if FS_OUT == 24000
#define NT 58                          // Kaiser low-pass: flat to 9 kHz, -53 dB from 12 kHz
const float H[NT] = {
  0.00031906f, -0.00064099f, -0.00102469f, 0.00054195f, 0.00205383f, 0.00029747f,
  -0.00303488f, -0.00213391f, 0.00330810f, 0.00488195f, -0.00206668f, -0.00793890f,
  -0.00137038f, 0.01013823f, 0.00721620f, -0.00988122f, -0.01490516f, 0.00542633f,
  0.02290680f, 0.00478005f, -0.02867802f, -0.02198000f, 0.02853510f, 0.04778345f,
  -0.01635575f, -0.08826830f, -0.02648153f, 0.19086451f, 0.39570739f, 0.39570739f,
  0.19086451f, -0.02648153f, -0.08826830f, -0.01635575f, 0.04778345f, 0.02853510f,
  -0.02198000f, -0.02867802f, 0.00478005f, 0.02290680f, 0.00542633f, -0.01490516f,
  -0.00988122f, 0.00721620f, 0.01013823f, -0.00137038f, -0.00793890f, -0.00206668f,
  0.00488195f, 0.00330810f, -0.00213391f, -0.00303488f, 0.00029747f, 0.00205383f,
  0.00054195f, -0.00102469f, -0.00064099f, 0.00031906f
};
#elif FS_OUT == 12000
#define NT 96                          // Kaiser low-pass: flat to 4.5 kHz, -50 dB from 6 kHz
const float H[NT] = {
  0.00035055f, 0.00023967f, -0.00008387f, -0.00051075f, -0.00081919f, -0.00077516f,
  -0.00027333f, 0.00055610f, 0.00134994f, 0.00165289f, 0.00115191f, -0.00010715f,
  -0.00164898f, -0.00272035f, -0.00263260f, -0.00115033f, 0.00127605f, 0.00359461f,
  0.00457597f, 0.00342213f, 0.00027492f, -0.00366382f, -0.00654008f, -0.00667332f,
  -0.00345258f, 0.00214480f, 0.00774658f, 0.01052296f, 0.00852839f, 0.00184581f,
  -0.00707340f, -0.01418489f, -0.01555701f, -0.00933598f, 0.00293666f, 0.01640138f,
  0.02456238f, 0.02206940f, 0.00751346f, -0.01501744f, -0.03650507f, -0.04576755f,
  -0.03357345f, 0.00341019f, 0.06043619f, 0.12529277f, 0.18171476f, 0.21449577f,
  0.21449577f, 0.18171476f, 0.12529277f, 0.06043619f, 0.00341019f, -0.03357345f,
  -0.04576755f, -0.03650507f, -0.01501744f, 0.00751346f, 0.02206940f, 0.02456238f,
  0.01640138f, 0.00293666f, -0.00933598f, -0.01555701f, -0.01418489f, -0.00707340f,
  0.00184581f, 0.00852839f, 0.01052296f, 0.00774658f, 0.00214480f, -0.00345258f,
  -0.00667332f, -0.00654008f, -0.00366382f, 0.00027492f, 0.00342213f, 0.00457597f,
  0.00359461f, 0.00127605f, -0.00115033f, -0.00263260f, -0.00272035f, -0.00164898f,
  -0.00010715f, 0.00115191f, 0.00165289f, 0.00134994f, 0.00055610f, -0.00027333f,
  -0.00077516f, -0.00081919f, -0.00051075f, -0.00008387f, 0.00023967f, 0.00035055f
};
#else
#error "FS_OUT must be 24000 or 12000"
#endif

const uint8_t ADC_ADDR[4] = {0x4C, 0x4D, 0x4E, 0x4F};

i2s_chan_handle_t rx = NULL;
static int16_t inbuf[FRAMES * NCH];
static float   x[NCH][NT - 1 + FRAMES];
static int16_t outbuf[NOUT * NCH];
static uint8_t pkt[HDR_LEN + PKT_FR * NCH * 2];

volatile uint32_t i2s_ovf = 0;
uint32_t pool_drops = 0, seq = 0, ovf_seen = 0;
uint64_t frame = 0;
bool streaming = false, drop_flag = false;
bool adc_present[4];
uint8_t asi_sts[4];

// ---------------- I2C ----------------
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

void configADCs() {
  for (int i = 0; i < 4; i++) {
    Wire.beginTransmission(ADC_ADDR[i]);
    adc_present[i] = (Wire.endTransmission() == 0);
    wr(ADC_ADDR[i], 0x00, 0x00); wr(ADC_ADDR[i], 0x02, 0x81);
  }
  delay(2);
  for (int i = 0; i < 4; i++) {
    uint8_t a = ADC_ADDR[i]; bool ctrl = (i == 3);
    wr(a, 0x07, 0x01);
    wr(a, 0x08, (i == 0) ? 0xA1 : 0x81);
    if (!ctrl) wr(a, 0x09, 0x80);
    if (ctrl) { wr(a, 0x13, 0xA0); wr(a, 0x14, 0x48); wr(a, 0x16, 0xD8); wr(a, 0x21, 0xA0); }
    else      { wr(a, 0x13, 0x00); wr(a, 0x21, 0xB0); }
    wr(a, 0x3B, 0x00);                                    // MICBIAS ~2.75 V (never AVDD)
    wr(a, 0x3C, 0x04); wr(a, 0x41, 0x04); wr(a, 0x46, 0x04); wr(a, 0x4B, 0x04);
    wr(a, 0x74, 0xF0);
  }
  wr(ADC_ADDR[3], 0x75, 0xC0);
  delay(5);
  for (int i = 0; i < 3; i++) wr(ADC_ADDR[i], 0x75, 0xE0);
  delay(20);
  for (int i = 0; i < 4; i++) { int v = rd(ADC_ADDR[i], 0x15); asi_sts[i] = v < 0 ? 0 : v; }
}

// ---------------- I2S ----------------
static bool IRAM_ATTR on_ovf(i2s_chan_handle_t h, i2s_event_data_t* e, void* u) { i2s_ovf = i2s_ovf + 1; return false; }

bool startI2S() {
  i2s_chan_config_t cc = I2S_CHANNEL_DEFAULT_CONFIG(I2S_NUM_0, I2S_ROLE_SLAVE);
  cc.dma_desc_num = 8; cc.dma_frame_num = FRAMES;
  if (i2s_new_channel(&cc, NULL, &rx) != ESP_OK) return false;
  i2s_tdm_config_t t; memset(&t, 0, sizeof(t));
  t.clk_cfg.sample_rate_hz = FS_IN;
  t.clk_cfg.clk_src = I2S_CLK_SRC_DEFAULT;
  t.clk_cfg.mclk_multiple = I2S_MCLK_MULTIPLE_256;
  t.clk_cfg.bclk_div = 8;
  t.slot_cfg.data_bit_width = I2S_DATA_BIT_WIDTH_16BIT;
  t.slot_cfg.slot_bit_width = I2S_SLOT_BIT_WIDTH_16BIT;
  t.slot_cfg.slot_mode = I2S_SLOT_MODE_STEREO;
  t.slot_cfg.slot_mask = (i2s_tdm_slot_mask_t)0xFFFF;
  t.slot_cfg.ws_width = 1;
  t.slot_cfg.ws_pol = true;
  t.slot_cfg.bit_shift = I2S_BIT_SHIFT;
  t.slot_cfg.total_slot = NCH;
  t.gpio_cfg.mclk = I2S_GPIO_UNUSED;
  t.gpio_cfg.bclk = (gpio_num_t)PIN_BCLK;
  t.gpio_cfg.ws   = (gpio_num_t)PIN_FSYNC;
  t.gpio_cfg.dout = I2S_GPIO_UNUSED;
  t.gpio_cfg.din  = (gpio_num_t)PIN_DIN;
  t.gpio_cfg.invert_flags.bclk_inv = I2S_BCLK_INV;
  if (i2s_channel_init_tdm_mode(rx, &t) != ESP_OK) return false;
  i2s_event_callbacks_t cbs; memset(&cbs, 0, sizeof(cbs));
  cbs.on_recv_q_ovf = on_ovf;
  i2s_channel_register_event_callback(rx, &cbs, NULL);
  return i2s_channel_enable(rx) == ESP_OK;
}

// ---------------- USB out ----------------
void sendStatus(const char* json) {
  uint16_t n = strlen(json);
  uint8_t h[6] = {'H', 'D', 'S', 'T', (uint8_t)(n & 0xFF), (uint8_t)(n >> 8)};
  Serial.write(h, 6);
  Serial.write((const uint8_t*)json, n);
  Serial.flush();
}

void statusReply() {
  static char js[512];
  snprintf(js, sizeof(js),
    "{\"fw\":\"ssl16_hdoa_revD\",\"fs\":%d,\"n_ch\":16,\"streaming\":%s,"
    "\"adc_present\":[%s,%s,%s,%s],\"asi_sts\":[%u,%u,%u,%u],"
    "\"pool_drops\":%u,\"i2s_ovf\":%u,\"seq\":%u,\"frame\":%llu,\"bit_shift\":%d,\"bclk_inv\":%d,"
    "\"ports\":\"single daisy chain on IO13; A = stream 0-7, B = stream 8-15\"}",
    FS_OUT, streaming ? "true" : "false",
    adc_present[0] ? "true" : "false", adc_present[1] ? "true" : "false",
    adc_present[2] ? "true" : "false", adc_present[3] ? "true" : "false",
    asi_sts[0], asi_sts[1], asi_sts[2], asi_sts[3],
    pool_drops, (unsigned)i2s_ovf, seq, (unsigned long long)frame, (int)I2S_BIT_SHIFT, I2S_BCLK_INV);
  sendStatus(js);
}

void regdumpReply(int n) {
  static char js[1100];
  if (n < 1 || n > 4) { sendStatus("{\"error\":\"REGDUMP n, n = 1..4\"}"); return; }
  uint8_t a = ADC_ADDR[n - 1];
  int p = snprintf(js, sizeof(js), "{\"regdump\":{\"addr\":%u,\"regs\":[", a);
  for (int r = 0; r < 128; r++) {
    int v = rd(a, r);
    p += snprintf(js + p, sizeof(js) - p, "%d%s", v < 0 ? -1 : v, r < 127 ? "," : "");
  }
  snprintf(js + p, sizeof(js) - p, "]}}");
  sendStatus(js);
}

void sendPackets(const int16_t* d, int nframes) {
  for (int off = 0; off < nframes; off += PKT_FR) {
    int nf = min(PKT_FR, nframes - off);
    size_t len = HDR_LEN + nf * NCH * 2;
    uint16_t flags = 0;
    uint32_t ov = i2s_ovf;
    if (ov != ovf_seen) { flags |= 1; ovf_seen = ov; }
    if (drop_flag) flags |= 2;
    if ((size_t)Serial.availableForWrite() < len) {      // USB too slow: drop, never block the audio path
      pool_drops++; drop_flag = true;
      frame += nf; seq++;                                  // the frame gap shows up on the PC as missing frames
      continue;
    }
    drop_flag = false;
    uint16_t nfr = nf, nch = NCH, rsv = 0;
    memcpy(pkt, "HDOA", 4);
    memcpy(pkt + 4, &seq, 4);
    memcpy(pkt + 8, &frame, 8);
    memcpy(pkt + 16, &nfr, 2);
    memcpy(pkt + 18, &nch, 2);
    memcpy(pkt + 20, &flags, 2);
    memcpy(pkt + 22, &rsv, 2);
    memcpy(pkt + HDR_LEN, d + off * NCH, nf * NCH * 2);
    Serial.write(pkt, len);
    seq++; frame += nf;
  }
}

// ---------------- commands ----------------
void handleCommands() {
  static char line[32]; static int n = 0;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\r') continue;
    if (c != '\n') { if (n < 31) line[n++] = c; continue; }
    line[n] = 0; n = 0;
    if (!strcmp(line, "START")) {
      streaming = true; seq = 0; frame = 0; drop_flag = false; ovf_seen = i2s_ovf;
      memset(x, 0, sizeof(x));
    } else if (!strcmp(line, "STOP")) {
      streaming = false;
    } else if (!strcmp(line, "STATUS")) {
      statusReply();
    } else if (!strncmp(line, "REGDUMP", 7)) {
      regdumpReply(atoi(line + 7));
    }
  }
}

// ---------------- main ----------------
void setup() {
  Serial.setTxBufferSize(65536);
  Serial.setRxBufferSize(256);
  Serial.begin(2000000);
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_SHDNZ, OUTPUT); digitalWrite(PIN_SHDNZ, HIGH);
  delay(10);
  Wire.begin(PIN_SDA, PIN_SCL, 100000);
  configADCs();
  memset(x, 0, sizeof(x));
  if (!startI2S()) while (1) { digitalWrite(PIN_LED, !digitalRead(PIN_LED)); delay(100); }   // fast blink = I2S error
}

void loop() {
  handleCommands();
  size_t got = 0;
  if (i2s_channel_read(rx, inbuf, sizeof(inbuf), &got, 100) != ESP_OK || got != sizeof(inbuf)) return;
  if (!streaming) { digitalWrite(PIN_LED, (millis() >> 9) & 1); return; }   // slow blink = idle, keep draining I2S

  for (int f = 0; f < FRAMES; f++)
    for (int c = 0; c < NCH; c++)
      x[c][NT - 1 + f] = (float)inbuf[f * NCH + c];
  for (int n = 0; n < NOUT; n++) {
    int base = NT - 1 + n * DECIM;
    for (int c = 0; c < NCH; c++) {
      const float* xp = &x[c][base];
      float acc = 0;
      for (int k = 0; k < NT; k++) acc += H[k] * xp[-k];
      int32_t v = (int32_t)acc;
      if (v > 32767) v = 32767; else if (v < -32768) v = -32768;
      outbuf[n * NCH + c] = (int16_t)v;
    }
  }
  for (int c = 0; c < NCH; c++) memmove(&x[c][0], &x[c][FRAMES], (NT - 1) * sizeof(float));
  sendPackets(outbuf, NOUT);
  digitalWrite(PIN_LED, HIGH);                                               // steady on = streaming
}
