// SSL-16 Rev A — 16-channel WAV recorder to microSD + USB streamer + temperature logger (v4)
//
// Same as SSL16_Stream_v3, except the SD card now gets a standard 16-channel WAV file
// instead of the SSL6 packet .bin file.
//
// What it does
//   * captures 16 ch @ 48 kHz (TDM slave), 96-tap low-pass, decimates by 4 -> 12 kHz
//   * streams 'SSL6' packets over native USB (unchanged, ssl16_realtime_3d.py still works)
//   * while a run is active, writes the audio to the microSD card as a WAV file
//   * reads the TMP112 (U9, 0x48) once per second: sent to the PC and written next to each run
//
// Runs on the SD card (folder /ssl16):
//   <name>.wav       16 channels, 12 kHz, 16-bit PCM (opens in Audacity, MATLAB audioread, Python soundfile/scipy)
//   <name>_temp.csv  board_ms, seq, temp_c   (1 per second)
//   <name>.txt       metadata: firmware, fs, channel order, start/stop time, samples, dropped blocks
//
// WAV channel order: see WAV_MIC_ORDER below (default: channel 1 = M1 ... channel 16 = M16).
// The WAV header is refreshed every 10 s, so a run cut short by power loss is still readable
// up to the last refresh. A run stops by itself at ~3.9 GB (about 2 h 49 min) — WAV / FAT32 limit.
//
// Start / stop a run
//   * from the PC: the line "START <name>\n" / "STOP\n" on the USB serial port
//   * without a PC: press BOOT (IO0) -> run auto_NNN starts; press again -> stops
//   Always stop the run before removing the card or power, so the file is closed properly.
//
// LED: blue = booting, green blink = streaming, red blink = recording, orange = no audio clock, red = I2S failed
//
// Text status lines "#SSL16 ...\n" are sent between packets:
//   "#SSL16 T ms=.. temp=.. seq=.. sd=ok|none|FAIL rec=<name>|- rec_kb=.. ring_drop=.. usb_drop=.."  every 1 s
//
// Arduino IDE: "ESP32S3 Dev Module", core 3.x, USB CDC On Boot = Enabled, USB Mode = Hardware CDC and JTAG,
//              PSRAM = OPI PSRAM, Flash = 8 MB, Upload Speed 115200 if uploads fail at "Changing baud rate".
// After uploading, press EN once.
//
// USB packet (little endian): 'S''S''L''6' | uint32 seq | uint16 nsamp | uint16 nch | int16 data[nsamp][16]
// USB channel order = TDM slot order: M2 M7 M10 M15 M1 M4 M9 M12 M3 M6 M11 M14 M5 M8 M13 M16

#include <Wire.h>
#include <FS.h>
#include <SD_MMC.h>
#include <string.h>
#include <stdarg.h>
#include "driver/i2s_tdm.h"
#include "esp_heap_caps.h"
#include "freertos/FreeRTOS.h"
#include "freertos/queue.h"

#define FW_NAME    "SSL16_WavRecorder_v4.1"   // v4.1: STOP fixed (was ignored while audio kept arriving)

// 1 = WAV channels in mic order (ch1 = M1 ... ch16 = M16)
// 0 = WAV channels in TDM slot order (same order as the USB packets / old .bin files)
#define WAV_MIC_ORDER 1

#define PIN_SDA    8
#define PIN_SCL    9
#define PIN_SHDNZ  11
#define PIN_RGB    48                 // WS2812 (lights only when powered from the 12 V jack)
#define PIN_BOOT   0
#define PIN_BCLK   6
#define PIN_FSYNC  7
#define PIN_DIN    13
#define PIN_SD_CLK 5
#define PIN_SD_CMD 4
#define PIN_SD_D0  18
#define PIN_SD_D1  16
#define PIN_SD_D2  15
#define PIN_SD_D3  21
#define PIN_SD_CD  14                 // card detect, low = card present

#define TMP112_ADDR 0x48

#define FS_IN      48000
#define DECIM      4                  // 48 kHz -> 12 kHz
#define FS_OUT     (FS_IN / DECIM)
#define NCH        16
#define FRAMES     480                // input frames per read (10 ms)
#define NOUT       (FRAMES / DECIM)   // 120 output samples per block
#define GAIN_SHIFT 0                  // extra digital gain (bits) if signals are tiny
#define PKT_BYTES  (12 + NOUT * NCH * 2)
#define BLK_BYTES  (NOUT * NCH * 2)   // one audio block in the WAV file (3840 bytes)

#define RING_BYTES (4 * 1024 * 1024)  // PSRAM buffer between audio loop and SD writer (~10 s)
#define SD_CHUNK   (32 * 1024)        // write the SD card in 32 KB blocks

#define WAV_HDR_BYTES   44
#define WAV_HDR_SYNC_MS 10000         // rewrite the header + flush this often while recording
#define WAV_MAX_BYTES   3900000000UL  // stop the run here (WAV and FAT32 both end at 4 GB)

// Alignment found by the self-test on this board
#define I2S_BIT_SHIFT true
#define I2S_BCLK_INV  1

const uint8_t ADC_ADDR[4] = {0x4C, 0x4D, 0x4E, 0x4F};

// Mic number in each TDM slot
const uint8_t SLOT_MIC[NCH] = {2, 7, 10, 15, 1, 4, 9, 12, 3, 6, 11, 14, 5, 8, 13, 16};
static uint8_t wav_ch[NCH];           // TDM slot -> WAV channel index

// 96-tap Kaiser low-pass, fs 48 kHz: flat to 4.5 kHz (-0.02 dB), -50.8 dB from 6 kHz
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
static uint8_t pkt[PKT_BYTES];               // USB packet (slot order)
static int16_t wavblk[NOUT * NCH];           // same samples in WAV channel order
static uint32_t seq = 0;

static bool     i2s_ok = false, tmp_ok = false;
static uint8_t  adc_ack = 0;                 // bit i = ADC i answered on I2C
static uint32_t i2c_fail = 0, timeouts = 0, short_reads = 0, usb_drop = 0;
static float    temp_c = NAN;
static uint32_t t_status = 0;

// ---------------------------------------------------------------- SD recorder (writer task on core 0)
enum SdState : uint8_t { SD_NONE = 0, SD_OK = 1, SD_FAIL = 2 };
static volatile uint8_t  sd_state = SD_NONE;
static volatile bool     recording = false;          // set by writer task once the files are open
static volatile bool     req_start = false, req_stop = false;
static char              req_name[48] = "";
static char              rec_name[48] = "";
static uint8_t*          ring = NULL;
static volatile uint32_t ring_head = 0, ring_tail = 0;   // free-running byte counters
static volatile uint32_t ring_drop = 0, rec_bytes = 0, rec_blocks = 0;
static volatile uint32_t sd_err = 0;
static QueueHandle_t     tq;                              // temperature records for the run's _temp.csv
struct TempRec { uint32_t ms, seq; float t; };

static uint32_t ring_used() { return ring_head - ring_tail; }

static void ring_push(const uint8_t* p, uint32_t n) {    // audio loop only (single producer)
  if (!ring || !recording) return;
  if (RING_BYTES - ring_used() < n) { ring_drop++; return; }   // drop whole blocks, never split
  uint32_t h = ring_head % RING_BYTES, first = min<uint32_t>(n, RING_BYTES - h);
  memcpy(ring + h, p, first);
  if (n > first) memcpy(ring, p + first, n - first);
  ring_head += n;
  rec_blocks++;
}

static bool sd_mount() {
  pinMode(PIN_SD_CD, INPUT_PULLUP);
  if (digitalRead(PIN_SD_CD) != LOW) return false;          // no card
  SD_MMC.setPins(PIN_SD_CLK, PIN_SD_CMD, PIN_SD_D0, PIN_SD_D1, PIN_SD_D2, PIN_SD_D3);
  if (SD_MMC.begin("/sdcard", false, false, SDMMC_FREQ_DEFAULT)) return true;   // 4-bit, 20 MHz
  SD_MMC.end();
  if (SD_MMC.begin("/sdcard", false, false, 10000)) return true;                // 4-bit, 10 MHz
  SD_MMC.end();
  return SD_MMC.begin("/sdcard", true, false, 10000);                           // 1-bit, 10 MHz
}

static void put16(uint8_t* p, uint16_t v) { p[0] = v; p[1] = v >> 8; }
static void put32(uint8_t* p, uint32_t v) { p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24; }

// Write the 44-byte PCM WAV header at the start of the file, then return to the end of the data.
static bool wav_write_header(File& f, uint32_t data_bytes) {
  uint8_t h[WAV_HDR_BYTES];
  memcpy(h, "RIFF", 4);       put32(h + 4, 36 + data_bytes);
  memcpy(h + 8, "WAVE", 4);
  memcpy(h + 12, "fmt ", 4);  put32(h + 16, 16);
  put16(h + 20, 1);                                   // PCM
  put16(h + 22, NCH);
  put32(h + 24, FS_OUT);
  put32(h + 28, (uint32_t)FS_OUT * NCH * 2);          // bytes per second
  put16(h + 32, NCH * 2);                             // bytes per frame
  put16(h + 34, 16);                                  // bits per sample
  memcpy(h + 36, "data", 4);  put32(h + 40, data_bytes);
  if (!f.seek(0)) return false;
  bool ok = f.write(h, WAV_HDR_BYTES) == WAV_HDR_BYTES;
  if (!f.seek(WAV_HDR_BYTES + data_bytes)) return false;
  return ok;
}

static void sd_writer(void*) {
  File fwav, ftmp;
  sd_state = sd_mount() ? SD_OK : (digitalRead(PIN_SD_CD) == LOW ? SD_FAIL : SD_NONE);
  if (sd_state == SD_OK && !SD_MMC.exists("/ssl16")) SD_MMC.mkdir("/ssl16");
  uint32_t t_start = 0, seq_start = 0, t_hdr = 0;
  for (;;) {
    if (req_start && !recording) {
      req_start = false;
      if (sd_state != SD_OK) { sd_state = sd_mount() ? SD_OK : SD_FAIL; if (sd_state == SD_OK && !SD_MMC.exists("/ssl16")) SD_MMC.mkdir("/ssl16"); }
      if (sd_state == SD_OK) {
        char nm[48]; strncpy(nm, req_name, sizeof(nm)); nm[sizeof(nm) - 1] = 0;
        if (!nm[0]) {                                        // BOOT button: next free auto_NNN
          for (int i = 1; i < 1000; i++) {
            snprintf(nm, sizeof(nm), "auto_%03d", i);
            char p[80]; snprintf(p, sizeof(p), "/ssl16/%s.wav", nm);
            if (!SD_MMC.exists(p)) break;
          }
        }
        char p[80];
        snprintf(p, sizeof(p), "/ssl16/%s.wav", nm);      fwav = SD_MMC.open(p, FILE_WRITE);
        snprintf(p, sizeof(p), "/ssl16/%s_temp.csv", nm); ftmp = SD_MMC.open(p, FILE_WRITE);
        if (fwav && ftmp && wav_write_header(fwav, 0)) {
          ftmp.println("board_ms,seq,temp_c");
          strncpy(rec_name, nm, sizeof(rec_name));
          t_start = millis(); seq_start = seq; t_hdr = millis();
          rec_bytes = 0; rec_blocks = 0; ring_drop = 0;
          ring_tail = ring_head;                            // start empty
          xQueueReset(tq);
          recording = true;
        } else { sd_err++; if (fwav) fwav.close(); if (ftmp) ftmp.close(); }
      }
    }
    if (recording) {
      uint32_t used = ring_used();
      // On a stop request leave this loop at once: the stop block below first stops the
      // producer and then drains the ring. (v4.0 tried to drain here while the audio loop
      // was still pushing, which on a slow card never finished -> STOP was ignored.)
      while (used >= SD_CHUNK && !req_stop) {
        uint32_t t = ring_tail % RING_BYTES;
        uint32_t n = min<uint32_t>(min<uint32_t>(used, SD_CHUNK), RING_BYTES - t);
        size_t w = fwav.write(ring + t, n);
        if (w != n) { sd_err++; req_stop = true; if (w == 0) break; }
        ring_tail += w; rec_bytes += w; used = ring_used();
      }
      TempRec r;
      while (xQueueReceive(tq, &r, 0) == pdTRUE) ftmp.printf("%lu,%lu,%.4f\n", (unsigned long)r.ms, (unsigned long)r.seq, r.t);
      if (!req_stop && millis() - t_hdr >= WAV_HDR_SYNC_MS) {   // keep the file valid if power is lost
        t_hdr = millis();
        if (!wav_write_header(fwav, rec_bytes)) sd_err++;
        fwav.flush(); ftmp.flush();
      }
      if (rec_bytes >= WAV_MAX_BYTES) req_stop = true;          // 4 GB limit
      if (req_stop) {
        recording = false;                                  // producer stops pushing
        vTaskDelay(pdMS_TO_TICKS(30));                      // let a block that is being pushed right now finish
        // drain everything that is still in the ring
        uint32_t u = ring_used();
        while (u > 0) {
          uint32_t t = ring_tail % RING_BYTES, n = min<uint32_t>(u, RING_BYTES - t);
          size_t w = fwav.write(ring + t, n); if (w == 0) { sd_err++; break; }
          ring_tail += w; rec_bytes += w; u = ring_used();
        }
        if (!wav_write_header(fwav, rec_bytes)) sd_err++;   // final sizes
        fwav.close(); ftmp.close();
        char p[80]; snprintf(p, sizeof(p), "/ssl16/%s.txt", rec_name);
        File fm = SD_MMC.open(p, FILE_WRITE);
        if (fm) {
          fm.printf("firmware=%s\nfs_hz=%d\nnch=16\nformat=WAV, 16-bit PCM little endian\n", FW_NAME, FS_OUT);
          fm.print("wav_channel_order=");
          for (int ch = 0; ch < NCH; ch++)
            for (int s = 0; s < NCH; s++)
              if (wav_ch[s] == ch) fm.printf("M%d%s", SLOT_MIC[s], ch == NCH - 1 ? "\n" : " ");
          fm.printf("start_board_ms=%lu\nstop_board_ms=%lu\nfirst_seq=%lu\nblocks=%lu\nsamples_per_channel=%lu\nbytes=%lu\n",
                    (unsigned long)t_start, (unsigned long)millis(), (unsigned long)seq_start,
                    (unsigned long)rec_blocks, (unsigned long)(rec_bytes / (NCH * 2)), (unsigned long)rec_bytes);
          fm.printf("ring_dropped_blocks=%lu (each = %d samples missing from the WAV)\nsd_errors=%lu\nlast_temp_c=%.4f\n",
                    (unsigned long)ring_drop, NOUT, (unsigned long)sd_err, temp_c);
          fm.close();
        }
        req_stop = false;
        rec_name[0] = 0;
      }
    } else if (req_stop) req_stop = false;
    vTaskDelay(pdMS_TO_TICKS(recording ? 5 : 50));
  }
}

// ---------------------------------------------------------------- helpers
void say(const char* fmt, ...) {               // one text line between packets; never blocks the audio loop
  char s[240];
  va_list ap; va_start(ap, fmt);
  int n = vsnprintf(s, sizeof(s) - 1, fmt, ap);
  va_end(ap);
  if (n < 0) return;
  if (n > (int)sizeof(s) - 1) n = sizeof(s) - 1;
  s[n++] = '\n';
  if (Serial.availableForWrite() < n + 7) return;
  Serial.write((const uint8_t*)"#SSL16 ", 7);
  Serial.write((const uint8_t*)s, n);
}

void led(uint8_t r, uint8_t g, uint8_t b) {
#if ESP_ARDUINO_VERSION_MAJOR >= 3
  rgbLedWrite(PIN_RGB, r, g, b);
#else
  neopixelWrite(PIN_RGB, r, g, b);
#endif
}

bool wr(uint8_t a, uint8_t r, uint8_t v) {
  Wire.beginTransmission(a); Wire.write(r); Wire.write(v);
  bool ok = Wire.endTransmission() == 0;
  if (!ok) i2c_fail++;
  return ok;
}

bool readTemp(float* t) {                       // TMP112: 12-bit, 0.0625 C/LSB, register 0x00
  Wire.beginTransmission(TMP112_ADDR); Wire.write(0x00);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom((uint8_t)TMP112_ADDR, (uint8_t)2) != 2) return false;
  int16_t raw = (int16_t)((Wire.read() << 8) | Wire.read());
  *t = (raw >> 4) * 0.0625f;
  return true;
}

void configADCs() {
  for (int i = 0; i < 4; i++) {
    Wire.beginTransmission(ADC_ADDR[i]);
    if (Wire.endTransmission() == 0) adc_ack |= 1 << i;
  }
  for (int i = 0; i < 4; i++) { wr(ADC_ADDR[i], 0x00, 0x00); wr(ADC_ADDR[i], 0x02, 0x81); }
  delay(2);
  for (int i = 0; i < 4; i++) {
    uint8_t a = ADC_ADDR[i]; bool ctrl = (i == 3);
    wr(a, 0x07, 0x01);
    wr(a, 0x08, (i == 0) ? 0xA1 : 0x81);
    if (!ctrl) wr(a, 0x09, 0x80);
    if (ctrl) { wr(a, 0x13, 0xA0); wr(a, 0x14, 0x48); wr(a, 0x16, 0xD8); wr(a, 0x21, 0xA0); }
    else      { wr(a, 0x13, 0x00); wr(a, 0x21, 0xB0); }
    wr(a, 0x3B, 0x00);                                   // MICBIAS ~2.75 V (never 3.3 V: mic abs-max 3.0 V)
    wr(a, 0x3C, 0x04); wr(a, 0x41, 0x04); wr(a, 0x46, 0x04); wr(a, 0x4B, 0x04);
    wr(a, 0x74, 0xF0);
  }
  wr(ADC_ADDR[3], 0x75, 0xC0);                           // controller first: starts BCLK / FSYNC
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

const char* sd_str() { return sd_state == SD_OK ? "ok" : sd_state == SD_FAIL ? "FAIL" : "none"; }

void report(const char* what) {
  say("%s fw=%s adc_ack=%c%c%c%c i2c_fail=%lu i2s=%s tmp112=%s sd=%s psram=%s timeouts=%lu short=%lu",
      what, FW_NAME,
      (adc_ack & 1) ? '1' : '-', (adc_ack & 2) ? '2' : '-', (adc_ack & 4) ? '3' : '-', (adc_ack & 8) ? '4' : '-',
      (unsigned long)i2c_fail, i2s_ok ? "ok" : "FAIL", tmp_ok ? "ok" : "FAIL", sd_str(), ring ? "ok" : "FAIL",
      (unsigned long)timeouts, (unsigned long)short_reads);
}

// ---------------------------------------------------------------- commands from the PC
static char cmd[64]; static int cmd_n = 0;

void handle_cmd(char* c) {
  while (*c == ' ') c++;
  say("cmd %s", c);                                      // acknowledge: shows in the PC log
  if (!strncmp(c, "START", 5)) {
    char* nm = c + 5; while (*nm == ' ') nm++;
    int k = 0;                                           // keep [A-Za-z0-9_-], max 40 chars
    for (; *nm && k < 40; nm++) if (isalnum((unsigned char)*nm) || *nm == '_' || *nm == '-') req_name[k++] = *nm;
    req_name[k] = 0;
    if (recording) { req_stop = true; while (req_stop) delay(1); }   // close the previous run first
    req_start = true;
  } else if (!strncmp(c, "STOP", 4)) {
    if (recording) req_stop = true;
  } else if (!strncmp(c, "STATUS", 6)) {
    report("status");
  }
}

void poll_cmds() {
  while (Serial.available()) {
    char ch = Serial.read();
    if (ch == '\n' || ch == '\r') { if (cmd_n) { cmd[cmd_n] = 0; handle_cmd(cmd); cmd_n = 0; } }
    else if (cmd_n < (int)sizeof(cmd) - 1) cmd[cmd_n++] = ch;
  }
}

void poll_button() {                                     // BOOT = start / stop a run without a PC
  static bool last = true; static uint32_t t_last = 0;
  bool b = digitalRead(PIN_BOOT);
  if (!b && last && millis() - t_last > 400) {
    t_last = millis();
    if (recording) req_stop = true; else { req_name[0] = 0; req_start = true; }
  }
  last = b;
}

// ---------------------------------------------------------------- setup / loop
void setup() {
  Serial.setTxBufferSize(32768);
  Serial.begin(2000000);               // baud is ignored on native USB
  led(0, 0, 8);                        // blue = booting
  for (int s = 0; s < NCH; s++) wav_ch[s] = WAV_MIC_ORDER ? SLOT_MIC[s] - 1 : s;
  pinMode(PIN_BOOT, INPUT_PULLUP);
  pinMode(PIN_SHDNZ, OUTPUT); digitalWrite(PIN_SHDNZ, HIGH);   // wake the four ADCs
  delay(10);
  Wire.begin(PIN_SDA, PIN_SCL, 100000);
  configADCs();
  tmp_ok = readTemp(&temp_c);
  ring = (uint8_t*)heap_caps_malloc(RING_BYTES, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  tq = xQueueCreate(64, sizeof(TempRec));
  xTaskCreatePinnedToCore(sd_writer, "sd_writer", 8192, NULL, 2, NULL, 0);      // SD on core 0
  i2s_ok = startI2S();
  memset(x, 0, sizeof(x));
  pkt[0] = 'S'; pkt[1] = 'S'; pkt[2] = 'L'; pkt[3] = '6';
  uint16_t ns = NOUT, nc = NCH;
  memcpy(pkt + 8, &ns, 2); memcpy(pkt + 10, &nc, 2);
  size_t got;                          // drop the first 100 ms (ADC filters settling)
  for (int i = 0; i2s_ok && i < 10; i++) i2s_channel_read(rx, inbuf, sizeof(inbuf), &got, 200);
  delay(300);                          // let the SD task finish mounting before the boot report
  report("boot");
  t_status = millis();
}

void status_tick() {
  if (millis() - t_status < 1000) return;
  t_status += 1000;
  if (millis() - t_status > 1000) t_status = millis();
  float t;
  if (readTemp(&t)) { temp_c = t; tmp_ok = true; } else tmp_ok = false;   // one 3-byte I2C read per second
  if (recording && tmp_ok) { TempRec r = {millis(), seq, temp_c}; xQueueSend(tq, &r, 0); }
  say("T ms=%lu temp=%.4f seq=%lu sd=%s rec=%s rec_kb=%lu ring_drop=%lu usb_drop=%lu sd_err=%lu",
      (unsigned long)millis(), tmp_ok ? temp_c : NAN, (unsigned long)seq, sd_str(),
      recording ? rec_name : "-", (unsigned long)(rec_bytes / 1024), (unsigned long)ring_drop,
      (unsigned long)usb_drop, (unsigned long)sd_err);
}

void loop() {
  poll_cmds();
  poll_button();
  if (!i2s_ok) {                       // I2S driver failed: stay alive and keep saying so
    led(16, 0, 0);
    if (millis() - t_status > 1000) { t_status = millis(); report("ERROR i2s driver init failed"); }
    delay(50);
    return;
  }

  size_t got = 0;
  esp_err_t e = i2s_channel_read(rx, inbuf, sizeof(inbuf), &got, 200);
  if (e != ESP_OK || got != sizeof(inbuf)) {
    if (e == ESP_ERR_TIMEOUT || got == 0) timeouts++; else short_reads++;
    led(16, 8, 0);                     // orange = no audio clock / data
    if (millis() - t_status > 1000) {
      t_status = millis();
      report("ERROR no I2S data (no BCLK/FSYNC from U4? check SHDNZ, I2C, 24.576 MHz XO)");
    }
    return;
  }

  // de-interleave the new block after the stored history
  for (int f = 0; f < FRAMES; f++)
    for (int c = 0; c < NCH; c++)
      x[c][NT - 1 + f] = (float)inbuf[f * NCH + c];

  // FIR + decimate by 4
  int16_t* out = (int16_t*)(pkt + 12);
  for (int n = 0; n < NOUT; n++) {
    int base = NT - 1 + n * DECIM;     // newest sample used for this output
    for (int c = 0; c < NCH; c++) {
      const float* xp = &x[c][base];
      float acc = 0;
      for (int k = 0; k < NT; k++) acc += H[k] * xp[-k];
      int32_t v = (int32_t)(acc * (1 << GAIN_SHIFT));
      if (v > 32767) v = 32767; else if (v < -32768) v = -32768;
      out[n * NCH + c] = (int16_t)v;               // USB: slot order
      wavblk[n * NCH + wav_ch[c]] = (int16_t)v;    // SD:  WAV channel order
    }
  }
  // keep the last NT-1 samples as history for the next block
  for (int c = 0; c < NCH; c++) memmove(&x[c][0], &x[c][FRAMES], (NT - 1) * sizeof(float));

  memcpy(pkt + 4, &seq, 4); seq++;
  ring_push((const uint8_t*)wavblk, BLK_BYTES);                         // SD (if recording)
  if (Serial.availableForWrite() >= PKT_BYTES) Serial.write(pkt, PKT_BYTES);   // USB (never blocks)
  else usb_drop++;
  if ((seq & 31) == 0) {
    if (recording) led((seq & 32) ? 12 : 0, 0, 0);                    // red blink = recording
    else           led(0, (seq & 32) ? 8 : 0, 0);                     // green blink = streaming
  }
  status_tick();
}
