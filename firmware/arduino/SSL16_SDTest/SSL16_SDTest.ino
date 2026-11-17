// SSL-16 Rev A — microSD test (SD_MMC, 4-bit with 1-bit fallback)
// Arduino IDE, "ESP32S3 Dev Module", core 3.x, USB CDC On Boot = Enabled
// Card: FAT32 (or exFAT), inserted before reset. Serial Monitor 115200.

#include "FS.h"
#include "SD_MMC.h"

#define SD_CLK  5
#define SD_CMD  4
#define SD_D0   18
#define SD_D1   16
#define SD_D2   15
#define SD_D3   21
#define SD_CD   14     // card detect

#define TEST_MB   4                 // size of the test file
#define BLK       (32 * 1024)       // bytes per write/read

const char* TEST_FILE = "/ssl16_test.bin";
uint8_t* wbuf;
uint8_t* rbuf;

void pass(const char* s, bool ok) { Serial.printf("[%s] %s\n", ok ? "PASS" : "FAIL", s); }

// pattern depends on block number, so a shifted or repeated block is caught
void fillBlock(uint8_t* b, uint32_t n) {
  for (uint32_t i = 0; i < BLK; i++) b[i] = (uint8_t)(i * 31 + n * 7 + (i >> 8));
}

bool mountCard() {
  if (!SD_MMC.setPins(SD_CLK, SD_CMD, SD_D0, SD_D1, SD_D2, SD_D3)) {
    Serial.println("setPins failed");
    return false;
  }
  // try 4-bit at 20 MHz, then 4-bit 10 MHz, then 1-bit 20 MHz
  if (SD_MMC.begin("/sdcard", false, false, SDMMC_FREQ_DEFAULT)) { Serial.println("Mounted: 4-bit, 20 MHz"); return true; }
  SD_MMC.end();
  if (SD_MMC.begin("/sdcard", false, false, 10000))               { Serial.println("Mounted: 4-bit, 10 MHz (20 MHz failed)"); return true; }
  SD_MMC.end();
  if (SD_MMC.begin("/sdcard", true, false, SDMMC_FREQ_DEFAULT))  { Serial.println("Mounted: 1-bit, 20 MHz (4-bit failed -> check D1/D2/D3: IO16/IO15/IO21)"); return true; }
  return false;
}

void cardInfo() {
  const char* t = "UNKNOWN";
  switch (SD_MMC.cardType()) {
    case CARD_MMC:  t = "MMC";  break;
    case CARD_SD:   t = "SDSC"; break;
    case CARD_SDHC: t = "SDHC/SDXC"; break;
    default: break;
  }
  Serial.printf("Card type: %s\n", t);
  Serial.printf("Card size: %llu MB\n", SD_MMC.cardSize() / (1024ULL * 1024ULL));
  Serial.printf("FS total : %llu MB, used: %llu MB\n",
                SD_MMC.totalBytes() / (1024ULL * 1024ULL), SD_MMC.usedBytes() / (1024ULL * 1024ULL));
}

void listRoot() {
  File root = SD_MMC.open("/");
  if (!root) { Serial.println("cannot open /"); return; }
  Serial.println("Root directory:");
  int n = 0;
  for (File f = root.openNextFile(); f && n < 20; f = root.openNextFile(), n++)
    Serial.printf("  %s %s  %u bytes\n", f.isDirectory() ? "[D]" : "   ", f.name(), (unsigned)f.size());
}

bool writeTest(float* mbps) {
  File f = SD_MMC.open(TEST_FILE, FILE_WRITE);
  if (!f) { Serial.println("open for write failed"); return false; }
  uint32_t blocks = (TEST_MB * 1024UL * 1024UL) / BLK;
  uint32_t t0 = millis();
  for (uint32_t n = 0; n < blocks; n++) {
    fillBlock(wbuf, n);
    if (f.write(wbuf, BLK) != BLK) { Serial.printf("write failed at block %u\n", n); f.close(); return false; }
  }
  f.close();                                   // includes flush
  uint32_t dt = millis() - t0;
  *mbps = (TEST_MB * 1000.0f) / (dt ? dt : 1);
  return true;
}

bool readTest(float* mbps) {
  File f = SD_MMC.open(TEST_FILE, FILE_READ);
  if (!f) { Serial.println("open for read failed"); return false; }
  uint32_t blocks = (TEST_MB * 1024UL * 1024UL) / BLK, bad = 0;
  uint32_t t0 = millis();
  for (uint32_t n = 0; n < blocks; n++) {
    if (f.read(rbuf, BLK) != BLK) { Serial.printf("read failed at block %u\n", n); f.close(); return false; }
    fillBlock(wbuf, n);
    if (memcmp(wbuf, rbuf, BLK) != 0) {
      if (bad < 5) Serial.printf("  data mismatch in block %u\n", n);
      bad++;
    }
  }
  uint32_t dt = millis() - t0;
  f.close();
  *mbps = (TEST_MB * 1000.0f) / (dt ? dt : 1);
  if (bad) Serial.printf("  %u of %u blocks corrupted\n", bad, blocks);
  return bad == 0;
}

void setup() {
  Serial.begin(115200);
  delay(2000);
  Serial.println("\n===== SSL-16 SD card test =====");

  pinMode(SD_CD, INPUT_PULLUP);
  Serial.printf("Card-detect IO14 = %d (note the level with and without a card)\n", digitalRead(SD_CD));

  wbuf = (uint8_t*)heap_caps_malloc(BLK, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
  rbuf = (uint8_t*)heap_caps_malloc(BLK, MALLOC_CAP_DMA | MALLOC_CAP_INTERNAL);
  if (!wbuf || !rbuf) { Serial.println("buffer alloc failed"); return; }

  bool ok = mountCard();
  pass("Mount card", ok);
  if (!ok) {
    Serial.println("Check: card inserted, FAT32 format, 3.3 V at the socket, CMD/CLK (IO4/IO5) and D0 (IO18) solder.");
    return;
  }
  cardInfo();
  listRoot();

  float wr = 0, rd = 0;
  bool w = writeTest(&wr);
  pass("Write 4 MB file", w);
  if (w) Serial.printf("  write speed: %.2f MB/s\n", wr);

  bool r = w && readTest(&rd);
  pass("Read back and verify 4 MB", r);
  if (r) Serial.printf("  read speed : %.2f MB/s\n", rd);

  // 16 ch x 16 bit x 48 kHz = 1.536 MB/s of raw audio
  pass("Write speed enough for 16-ch 48 kHz recording (>1.6 MB/s)", w && wr > 1.6f);

  SD_MMC.remove(TEST_FILE);
  Serial.println("Test file deleted. Done. Remove the card and press EN to check card-detect.");
}

void loop() {
  static int last = -1;
  int cd = digitalRead(SD_CD);
  if (cd != last) { Serial.printf("Card-detect IO14 changed -> %d\n", cd); last = cd; }
  delay(100);
}
