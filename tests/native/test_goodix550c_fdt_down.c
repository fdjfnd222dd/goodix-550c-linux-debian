/* Offline regression for the production firmware-13021 FDT-down path. */
#include "goodix53x5-commands.h"
#include "goodix53x5-private.h"
#include "goodix53x5-proto.h"

#include <gio/gio.h>
#include <stdio.h>
#include <string.h>

typedef struct
{
  FpiSsm *ssm;
  FpDevice *dev;
  guint8 category;
  guint8 command;
  guint8 payload[2 + GOODIX_FDT_BASE_LEN];
  gsize payload_len;
  gboolean expect_data;
  guint calls;
} CapturedCommand;

static CapturedCommand captured;

void
goodix_test_run_cmd (FpiSsm       *ssm,
                     FpDevice     *dev,
                     guint8        category,
                     guint8        command,
                     const guint8 *payload,
                     gsize         payload_len,
                     gboolean      expect_data)
{
  captured.ssm = ssm;
  captured.dev = dev;
  captured.category = category;
  captured.command = command;
  captured.payload_len = payload_len;
  captured.expect_data = expect_data;
  captured.calls++;

  if (payload_len <= sizeof (captured.payload))
    memcpy (captured.payload, payload, payload_len);
}

static gboolean
expect (gboolean condition,
        const char *message)
{
  if (!condition)
    fprintf (stderr, "FAIL: %s\n", message);
  return condition;
}

static gboolean
test_tls_13021_frame (void)
{
  static const guint8 threshold[GOODIX_FDT_BASE_LEN] = {
    0x97, 0x97, 0xa2, 0xa2, 0xa0, 0xa0, 0x94, 0x94,
    0x97, 0x97, 0xa3, 0xa3, 0xa1, 0xa1, 0x98, 0x98,
    0x93, 0x93, 0x9f, 0x9f, 0x9c, 0x9c, 0x93, 0x93,
  };
  static const guint8 expected_frame[] = {
    0xa0, 0x1c, 0x00, 0xbc,
    0x32, 0x19, 0x00,
    0x97, 0x97, 0xa2, 0xa2, 0xa0, 0xa0, 0x94, 0x94,
    0x97, 0x97, 0xa3, 0xa3, 0xa1, 0xa1, 0x98, 0x98,
    0x93, 0x93, 0x9f, 0x9f, 0x9c, 0x9c, 0x93, 0x93,
    0xdd,
  };
  FpiDeviceGoodix53x5 device = { 0 };
  FpiSsm *ssm = GSIZE_TO_POINTER (1);
  g_autofree guint8 *inner = NULL;
  g_autofree guint8 *frame = NULL;
  gsize inner_len = 0;
  gsize frame_len = 0;

  memset (&captured, 0, sizeof (captured));
  device.variant = GOODIX_VARIANT_TLS_PSK;
  goodix_cmd_fdt_down_setup (ssm, (FpDevice *) &device, threshold);

  if (!expect (captured.calls == 1, "TLS path did not submit exactly one command") ||
      !expect (captured.ssm == ssm, "TLS path changed the parent SSM") ||
      !expect (captured.dev == (FpDevice *) &device, "TLS path changed the device") ||
      !expect (captured.category == 0x03, "TLS path used the wrong category") ||
      !expect (captured.command == 0x01, "TLS path used the wrong command") ||
      !expect (!captured.expect_data, "TLS FDT-down unexpectedly requests data") ||
      !expect (captured.payload_len == GOODIX_FDT_BASE_LEN,
               "TLS path did not submit a direct 24-byte base") ||
      !expect (memcmp (captured.payload, threshold, sizeof (threshold)) == 0,
               "TLS path changed or prefixed the dynamic threshold"))
    return FALSE;

  inner = goodix_proto_build_message (captured.category, captured.command,
                                      captured.payload, captured.payload_len,
                                      TRUE, &inner_len);
  frame = goodix_proto_wrap_pack (GOODIX_PACK_FLAG_MESSAGE, inner, inner_len,
                                  &frame_len);

  return expect (frame_len == sizeof (expected_frame),
                 "encoded TLS frame has the wrong length") &&
         expect (memcmp (frame, expected_frame, sizeof (expected_frame)) == 0,
                 "compiled encoder did not produce the captured 13021 frame");
}

static gboolean
test_sibling_layout_stays_prefixed (void)
{
  guint8 threshold[GOODIX_FDT_BASE_LEN];
  FpiDeviceGoodix53x5 device = { 0 };
  FpiSsm *ssm = GSIZE_TO_POINTER (2);

  for (guint i = 0; i < G_N_ELEMENTS (threshold); i++)
    threshold[i] = (guint8) i;

  memset (&captured, 0, sizeof (captured));
  device.variant = GOODIX_VARIANT_GTLS;
  goodix_cmd_fdt_down_setup (ssm, (FpDevice *) &device, threshold);

  return expect (captured.calls == 1, "sibling path did not submit exactly one command") &&
         expect (captured.payload_len == 2 + GOODIX_FDT_BASE_LEN,
                 "sibling path lost its prefixed layout") &&
         expect (captured.payload[0] == 0x0c && captured.payload[1] == 0x01,
                 "sibling path prefix changed") &&
         expect (memcmp (captured.payload + 2, threshold, sizeof (threshold)) == 0,
                 "sibling path changed its threshold");
}

/* The open sequence's PSK-slot read must be byte-identical to
 * READ_PSK_HASH_PAYLOAD in src/goodix550c/protocol.py:
 * len=32, off=0, slot=0xbb020001, 0 (all little-endian). */
static gboolean
test_psk_hash_read_payload (void)
{
  static const guint8 expected[16] = {
    0x20, 0x00, 0x00, 0x00,
    0x00, 0x00, 0x00, 0x00,
    0x01, 0x00, 0x02, 0xbb,
    0x00, 0x00, 0x00, 0x00,
  };
  FpiDeviceGoodix53x5 device = { 0 };
  FpiSsm *ssm = GSIZE_TO_POINTER (3);

  memset (&captured, 0, sizeof (captured));
  device.variant = GOODIX_VARIANT_TLS_PSK;
  goodix_cmd_preset_psk_read (ssm, (FpDevice *) &device, 0xbb020001u, 32, 0);

  return expect (captured.calls == 1, "PSK read did not submit exactly one command") &&
         expect (captured.category == 0x0e && captured.command == 0x02,
                 "PSK read is not 0xE4") &&
         expect (captured.expect_data, "PSK read must expect a data reply") &&
         expect (captured.payload_len == sizeof (expected),
                 "PSK read payload length changed") &&
         expect (memcmp (captured.payload, expected, sizeof (expected)) == 0,
                 "PSK read payload differs from protocol.py READ_PSK_HASH_PAYLOAD");
}

int
main (void)
{
  if (!test_tls_13021_frame () || !test_sibling_layout_stays_prefixed () ||
      !test_psk_hash_read_payload ())
    return 1;

  puts ("Goodix firmware-13021 native FDT-down frame test passed.");
  return 0;
}
