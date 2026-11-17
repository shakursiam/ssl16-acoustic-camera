// SSL-16 Rev A — 16-channel audio streamer for localization
// Captures 16 ch @ 48 kHz (TDM), low-pass + decimates by 4 -> 12 kHz,
// streams packets over USB CDC to the PC script ssl16_locate.py.
//
// Arduino IDE: "ESP32S3 Dev Module", core 3.x, USB CDC On Boot = Enabled,
// PSRAM = OPI PSRAM. Close the Serial Monitor before running the Python script.
//
// Packet (little endian): 'S''S''L''6' | uint32 seq | uint16 nsamp | uint16 nch | int16 data[nsamp][16]

#include <Wire.h>
#include <string.h>
#include "driver/i2s_tdm.h"

#define PIN_SDA    8
#define PIN_SCL    9
#define PIN_SHDNZ  11
#define PIN_LED    48
#define PIN_BCLK   6
#define PIN_FSYNC  7
#define PIN_DIN    13

#define FS_IN      48000
#define DECIM      4                  // 48 kHz -> 12 kHz
#define NCH        16
#define FRAMES     480                // input frames per read (10 ms)
#define NOUT       (FRAMES / DECIM)   // 120 output samples per packet
#define GAIN_SHIFT 0                  // extra digital gain (bits) if signals are tiny

// Alignment found by the self-test on this board
#define I2S_BIT_SHIFT true
#define I2S_BCLK_INV  1

const uint8_t ADC_ADDR[4] = {0x4C, 0x4D, 0x4E, 0x4F};

// 96-tap Kaiser low-pass, fs 48 kHz: flat to 4.5 kHz, -50 dB from 6 kHz
#define NT 96
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

i2s_chan_handle_t rx = NULL;
static int16_t inbuf[FRAMES * NCH];
static float   x[NCH][NT - 1 + FRAMES];      // history + new block, per channel
static uint8_t pkt[12 + NOUT * NCH * 2];
static uint32_t seq = 0;

bool wr(uint8_t a, uint8_t r, uint8_t v) {
  Wire.beginTransmission(a); Wire.write(r); Wire.write(v);
  return Wire.endTransmission() == 0;
}

void configADCs() {
  for (int i = 0; i < 4; i++) { wr(ADC_ADDR[i], 0x00, 0x00); wr(ADC_ADDR[i], 0x02, 0x81); }
  delay(2);
  for (int i = 0; i < 4; i++) {
    uint8_t a = ADC_ADDR[i]; bool ctrl = (i == 3);
    wr(a, 0x07, 0x01);
    wr(a, 0x08, (i == 0) ? 0xA1 : 0x81);
    if (!ctrl) wr(a, 0x09, 0x80);
    if (ctrl) { wr(a, 0x13, 0xA0); wr(a, 0x14, 0x48); wr(a, 0x16, 0xD8); wr(a, 0x21, 0xA0); }
    else      { wr(a, 0x13, 0x00); wr(a, 0x21, 0xB0); }
    wr(a, 0x3B, 0x00);                                   // MICBIAS ~2.75 V
    wr(a, 0x3C, 0x04); wr(a, 0x41, 0x04); wr(a, 0x46, 0x04); wr(a, 0x4B, 0x04);
    wr(a, 0x74, 0xF0);
  }
  wr(ADC_ADDR[3], 0x75, 0xC0);
  delay(5);
  for (int i = 0; i < 3; i++) wr(ADC_ADDR[i], 0x75, 0xE0);
  delay(20);
}

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
  return i2s_channel_enable(rx) == ESP_OK;
}

void setup() {
  Serial.setTxBufferSize(32768);
  Serial.begin(2000000);               // baud is ignored on native USB
  pinMode(PIN_LED, OUTPUT);
  pinMode(PIN_SHDNZ, OUTPUT); digitalWrite(PIN_SHDNZ, HIGH);
  delay(10);
  Wire.begin(PIN_SDA, PIN_SCL, 100000);
  configADCs();
  bool ok = startI2S();
  memset(x, 0, sizeof(x));
  pkt[0] = 'S'; pkt[1] = 'S'; pkt[2] = 'L'; pkt[3] = '6';
  uint16_t ns = NOUT, nc = NCH;
  memcpy(pkt + 8, &ns, 2); memcpy(pkt + 10, &nc, 2);
  // drop the first 100 ms (filters settling)
  size_t got;
  for (int i = 0; ok && i < 10; i++) i2s_channel_read(rx, inbuf, sizeof(inbuf), &got, 200);
  if (!ok) while (1) { digitalWrite(PIN_LED, !digitalRead(PIN_LED)); delay(100); }   // fast blink = I2S error
}

void loop() {
  size_t got = 0;
  if (i2s_channel_read(rx, inbuf, sizeof(inbuf), &got, 200) != ESP_OK || got != sizeof(inbuf)) return;

  // de-interleave the new block after the stored history
  for (int f = 0; f < FRAMES; f++)
    for (int c = 0; c < NCH; c++)
      x[c][NT - 1 + f] = (float)inbuf[f * NCH + c];

  // FIR + decimate by 4
  int16_t* out = (int16_t*)(pkt + 12);
  for (int n = 0; n < NOUT; n++) {
    int base = NT - 1 + n * DECIM;          // newest sample used for this output
    for (int c = 0; c < NCH; c++) {
      const float* xp = &x[c][base];
      float acc = 0;
      for (int k = 0; k < NT; k++) acc += H[k] * xp[-k];
      int32_t v = (int32_t)(acc * (1 << GAIN_SHIFT));
      if (v > 32767) v = 32767; else if (v < -32768) v = -32768;
      out[n * NCH + c] = (int16_t)v;
    }
  }
  // keep the last NT-1 samples as history for the next block
  for (int c = 0; c < NCH; c++) memmove(&x[c][0], &x[c][FRAMES], (NT - 1) * sizeof(float));

  memcpy(pkt + 4, &seq, 4); seq++;
  Serial.write(pkt, sizeof(pkt));
  if ((seq & 31) == 0) digitalWrite(PIN_LED, !digitalRead(PIN_LED));   // slow blink = streaming
}
