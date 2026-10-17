/* Offline tests for the guarded manual-FDT policy and raw-baseline math. */
#include "goodix53x5-calibration.h"
#include "goodix53x5-safety.h"

#include <gio/gio.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static gboolean
expect (gboolean condition,
        const char *message)
{
  if (!condition)
    fprintf (stderr, "FAIL: %s\n", message);
  return condition;
}

static void
put_pair (guint8  *data,
          guint    pair,
          guint16  value)
{
  data[pair * 2] = value & 0xff;
  data[pair * 2 + 1] = value >> 8;
}

static gboolean
test_delta_summary (void)
{
  guint8 baseline[GOODIX_FDT_BASE_LEN] = { 0 };
  guint8 reading[GOODIX_FDT_BASE_LEN] = { 0 };
  guint16 max_delta = 0;
  guint changed_pairs = 0;

  for (guint i = 0; i < GOODIX_FDT_BASE_LEN / 2; i++)
    {
      put_pair (baseline, i, 200);
      put_pair (reading, i, 200);
    }

  /* Pair deltas after the protocol's >>1 normalization are 13 and 10. */
  put_pair (reading, 0, 226);
  put_pair (reading, 1, 220);

  return expect (goodix_device_measure_fdt_delta (baseline, reading,
                                                   sizeof (baseline), 12,
                                                   &max_delta,
                                                   &changed_pairs),
                 "valid baseline comparison was rejected") &&
         expect (max_delta == 13, "aggregate max delta is wrong") &&
         expect (changed_pairs == 1, "changed-pair count is wrong") &&
         expect (goodix_device_measure_fdt_delta (baseline, reading,
                                                   sizeof (baseline), 13,
                                                   &max_delta,
                                                   &changed_pairs),
                 "threshold-boundary comparison was rejected") &&
         expect (changed_pairs == 0,
                 "threshold equality was treated as a changed pair") &&
         expect (!goodix_device_measure_fdt_delta (baseline, reading, 23, 12,
                                                    &max_delta,
                                                    &changed_pairs),
                 "odd-length FDT input was accepted") &&
         expect (!goodix_device_measure_fdt_delta (NULL, reading,
                                                    sizeof (reading), 12,
                                                    &max_delta,
                                                    &changed_pairs),
                 "NULL baseline was accepted") &&
         expect (!goodix_device_measure_fdt_delta (baseline, reading, 0, 12,
                                                    &max_delta,
                                                    &changed_pairs),
                 "empty FDT input was accepted");
}

static gboolean
test_dual_gate (void)
{
  g_unsetenv ("GOODIX550C_ALLOW_MANUAL_FDT_POLL");
  if (!expect (!goodix_550c_manual_fdt_poll_allowed (),
               "manual polling enabled without runtime opt-in"))
    return FALSE;

  g_setenv ("GOODIX550C_ALLOW_MANUAL_FDT_POLL", "true", TRUE);
  if (!expect (!goodix_550c_manual_fdt_poll_allowed (),
               "non-exact runtime value enabled manual polling"))
    return FALSE;

  g_setenv ("GOODIX550C_ALLOW_MANUAL_FDT_POLL", "1", TRUE);
  return expect (goodix_550c_manual_fdt_poll_allowed (),
                 "exact runtime opt-in did not enable compiled polling");
}

static gboolean
test_direction_classifier (void)
{
  guint8 baseline[GOODIX_FDT_BASE_LEN] = { 0 };
  guint8 reading[GOODIX_FDT_BASE_LEN] = { 0 };
  gint pos = -1;
  gint neg = 1;

  for (guint i = 0; i < GOODIX_FDT_BASE_LEN / 2; i++)
    {
      put_pair (baseline, i, 400);
      put_pair (reading, i, 400);
    }
  /* Raw 400 -> 310 is -45 and raw 400 -> 410 is +5 after the >>1 scale. */
  put_pair (reading, 0, 310);
  put_pair (reading, 1, 410);

  if (!expect (goodix_device_fdt_signed_extremes (baseline, reading,
                                                   sizeof (baseline),
                                                   &pos, &neg),
               "signed extremes rejected valid input") ||
      !expect (pos == 5 && neg == -45, "signed extremes are wrong") ||
      !expect (!goodix_device_fdt_signed_extremes (baseline, reading, 23,
                                                    &pos, &neg),
               "odd-length input accepted by signed extremes") ||
      !expect (!goodix_device_fdt_signed_extremes (NULL, reading,
                                                    sizeof (reading),
                                                    &pos, &neg),
               "NULL baseline accepted by signed extremes"))
    return FALSE;

  /* Measured touch and lift populations, and the boundaries. */
  return expect (goodix_device_classify_fdt_direction (0, -42) ==
                 GOODIX_FDT_DIRECTION_TOUCH, "-42 is not a touch") &&
         expect (goodix_device_classify_fdt_direction (0, -49) ==
                 GOODIX_FDT_DIRECTION_TOUCH, "-49 is not a touch") &&
         expect (goodix_device_classify_fdt_direction (45, 0) ==
                 GOODIX_FDT_DIRECTION_LIFT, "+45 is not a lift") &&
         expect (goodix_device_classify_fdt_direction (50, 0) ==
                 GOODIX_FDT_DIRECTION_LIFT, "+50 is not a lift") &&
         expect (goodix_device_classify_fdt_direction (0, -GOODIX_FDT_TOUCH_MIN_NEG) ==
                 GOODIX_FDT_DIRECTION_TOUCH, "touch boundary rejected") &&
         expect (goodix_device_classify_fdt_direction (0, -GOODIX_FDT_TOUCH_MIN_NEG + 1) ==
                 GOODIX_FDT_DIRECTION_AMBIGUOUS, "weak negative accepted") &&
         expect (goodix_device_classify_fdt_direction (GOODIX_FDT_LIFT_MIN_POS, 0) ==
                 GOODIX_FDT_DIRECTION_LIFT, "lift boundary rejected") &&
         expect (goodix_device_classify_fdt_direction (GOODIX_FDT_LIFT_MIN_POS - 1, 0) ==
                 GOODIX_FDT_DIRECTION_AMBIGUOUS, "weak positive is a lift") &&
         expect (goodix_device_classify_fdt_direction (60, -30) ==
                 GOODIX_FDT_DIRECTION_LIFT, "positive-dominant mix is not a lift") &&
         expect (goodix_device_classify_fdt_direction (30, -45) ==
                 GOODIX_FDT_DIRECTION_TOUCH, "negative-dominant mix is not a touch") &&
         expect (goodix_device_classify_fdt_direction (45, -45) ==
                 GOODIX_FDT_DIRECTION_TOUCH, "tie is not a touch") &&
         expect (goodix_device_classify_fdt_direction (0, 0) ==
                 GOODIX_FDT_DIRECTION_AMBIGUOUS, "zero movement classified");
}

/* Runtime tunables (patch 0020): strict parse, clamp, default on junk. */
static gboolean
test_tunables (void)
{
  const char *key = "GOODIX550C_TUNE_SETTLE_MS";
  gboolean ok = TRUE;

  unsetenv (key);
  ok &= expect (goodix550c_tune_int ("SETTLE_MS", 300, 80, 500) == 300, "unset is not the default");
  setenv (key, "150", 1);
  ok &= expect (goodix550c_tune_int ("SETTLE_MS", 300, 80, 500) == 150, "valid value ignored");
  setenv (key, "5", 1);
  ok &= expect (goodix550c_tune_int ("SETTLE_MS", 300, 80, 500) == 80, "low value not clamped up");
  setenv (key, "99999", 1);
  ok &= expect (goodix550c_tune_int ("SETTLE_MS", 300, 80, 500) == 500, "high value not clamped down");
  setenv (key, "99999999999999", 1);
  ok &= expect (goodix550c_tune_int ("SETTLE_MS", 300, 80, 500) == 300, "int32 overflow accepted");
  setenv (key, "-7", 1);
  ok &= expect (goodix550c_tune_int ("SETTLE_MS", 300, 80, 500) == 80, "negative not clamped");

  g_test_expect_message (NULL, G_LOG_LEVEL_WARNING, "*invalid value*");
  setenv (key, "12abc", 1);
  ok &= expect (goodix550c_tune_int ("SETTLE_MS", 300, 80, 500) == 300, "trailing junk accepted");
  g_test_assert_expected_messages ();
  g_test_expect_message (NULL, G_LOG_LEVEL_WARNING, "*invalid value*");
  setenv (key, "", 1);
  ok &= expect (goodix550c_tune_int ("SETTLE_MS", 300, 80, 500) == 300, "empty string accepted");
  g_test_assert_expected_messages ();
  g_test_expect_message (NULL, G_LOG_LEVEL_WARNING, "*invalid value*");
  setenv (key, " 150", 1);
  ok &= expect (goodix550c_tune_int ("SETTLE_MS", 300, 80, 500) == 300, "leading space accepted");
  g_test_assert_expected_messages ();
  unsetenv (key);

  /* Table sanity: every default inside its clamp, and the explicit-threshold
   * classifier equals the compiled-default one at the defaults. */
#define CHECK(name, def, lo, hi) \
  ok &= expect ((lo) <= (def) && (def) <= (hi), #name " default outside clamp");
  GOODIX_TUNE_TABLE (CHECK)
#undef CHECK
  ok &= expect (goodix_device_classify_fdt_direction_with (0, -15, 12, 12) ==
                GOODIX_FDT_DIRECTION_TOUCH, "lowered touch floor ignored");
  ok &= expect (goodix_device_classify_fdt_direction_with (0, -15, 30, 30) ==
                GOODIX_FDT_DIRECTION_AMBIGUOUS, "raised touch floor ignored");
  return ok;
}

int
main (void)
{
  if (!test_delta_summary () || !test_direction_classifier () ||
      !test_dual_gate () || !test_tunables ())
    return 1;

  puts ("Goodix manual-FDT offline policy test passed.");
  return 0;
}
