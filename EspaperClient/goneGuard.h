// FORK ADDITION (Task 7): stop the 410 reboot loop.
//
// On 410 the firmware forgets its identity and restarts at once. That is right for a device whose
// record was legitimately removed: the next boot registers and the cycle ends. But if the server keeps
// answering 410 (a bug, a wiped data directory, a half-applied migration) the device would restart
// forever with the radio up and flatten a 600 mAh cell in hours, with no symptom but silence.
//
// So the number of 410s since the last good screen is kept in the device data file (the same file as
// TOTAL_DEVICE_STARTS, which setup() already rewrites on every boot). The first 410 restarts as
// before; a repeat sleeps GONE_RETRY_SLEEP_SECONDS first. Any 200 clears the count.
//
// Header-only so the host tests compile the real thing.
#ifndef GONE_GUARD_H
#define GONE_GUARD_H

#include "configportal.h"

#define GONE_RETRY_SLEEP_SECONDS 60  // the same fast retry the firmware uses for any other failure

// Records one more 410. Returns true if the device must sleep rather than restart straight away.
// The caller persists deviceData before acting, or the count would not survive ESP.restart().
static inline bool recordGoneShouldSleep(DeviceData *deviceData) {
  if (deviceData->consecutiveGone < 255) {  // saturate: wrapping to 0 would turn a loop into restarts again
    deviceData->consecutiveGone++;
  }
  return deviceData->consecutiveGone >= 2;
}

static inline void clearGoneCount(DeviceData *deviceData) {
  deviceData->consecutiveGone = 0;
}

#endif
