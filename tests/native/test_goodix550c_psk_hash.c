/* Offline test for the PSK-slot reply check used by the 550c open sequence.
 * Uses a synthetic key and a synthetic reply; no device, no real secret. */
#include "goodix53x5-tls.h"

#include <openssl/evp.h>
#include <stdio.h>
#include <string.h>

static const guint8 synthetic_psk[32] = {
  0xa0, 0xa1, 0xa2, 0xa3, 0xa4, 0xa5, 0xa6, 0xa7,
  0xa8, 0xa9, 0xaa, 0xab, 0xac, 0xad, 0xae, 0xaf,
  0xb0, 0xb1, 0xb2, 0xb3, 0xb4, 0xb5, 0xb6, 0xb7,
  0xb8, 0xb9, 0xba, 0xbb, 0xbc, 0xbd, 0xbe, 0xbf,
};

static int failures;

static void
expect (int ok, const char *what)
{
  if (!ok)
    {
      fprintf (stderr, "FAIL: %s\n", what);
      failures++;
    }
}

/* status(1) | slot(4 LE) | length(4 LE) | hash(32) */
static void
build_reply (guint8 reply[41], const guint8 *psk, gsize psk_len)
{
  unsigned int n = 0;

  memset (reply, 0, 41);
  reply[1] = 0x01; reply[2] = 0x00; reply[3] = 0x02; reply[4] = 0xbb;
  reply[5] = 0x20;
  EVP_Digest (psk, psk_len, reply + 9, &n, EVP_sha256 (), NULL);
}

int
main (void)
{
  guint8 reply[41];
  guint8 bad_psk[32];
  guint8 longer[42];

  build_reply (reply, synthetic_psk, sizeof (synthetic_psk));
  expect (goodix_psk_hash_check_reply (synthetic_psk, 32, reply, 41) ==
          GOODIX_PSK_HASH_MATCH, "matching hash accepted");

  memcpy (bad_psk, synthetic_psk, 32);
  bad_psk[31] ^= 1;
  expect (goodix_psk_hash_check_reply (bad_psk, 32, reply, 41) ==
          GOODIX_PSK_HASH_MISMATCH, "wrong key reported as mismatch");

  for (int i = 9; i < 41; i++)
    {
      guint8 flipped[41];

      memcpy (flipped, reply, 41);
      flipped[i] ^= 0x80;
      expect (goodix_psk_hash_check_reply (synthetic_psk, 32, flipped, 41) ==
              GOODIX_PSK_HASH_MISMATCH, "any flipped hash byte is a mismatch");
    }

  /* Format deviations are never a match, even with the right hash. */
  for (int i = 0; i < 9; i++)
    {
      guint8 bad[41];

      memcpy (bad, reply, 41);
      bad[i] ^= 0x01;
      expect (goodix_psk_hash_check_reply (synthetic_psk, 32, bad, 41) ==
              GOODIX_PSK_HASH_BAD_REPLY, "header byte change is a bad reply");
    }
  expect (goodix_psk_hash_check_reply (synthetic_psk, 32, reply, 40) ==
          GOODIX_PSK_HASH_BAD_REPLY, "truncated reply rejected");
  memcpy (longer, reply, 41);
  longer[41] = 0;
  expect (goodix_psk_hash_check_reply (synthetic_psk, 32, longer, 42) ==
          GOODIX_PSK_HASH_BAD_REPLY, "trailing byte rejected");
  expect (goodix_psk_hash_check_reply (synthetic_psk, 32, NULL, 0) ==
          GOODIX_PSK_HASH_BAD_REPLY, "empty reply rejected");
  expect (goodix_psk_hash_check_reply (NULL, 0, reply, 41) ==
          GOODIX_PSK_HASH_BAD_REPLY, "missing key rejected");

  if (failures != 0)
    return 1;
  puts ("Goodix 550c PSK-hash reply check passed.");
  return 0;
}
