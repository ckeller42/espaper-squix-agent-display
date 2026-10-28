// FORK ADDITION (Task 3): decide whether a stored server URL is an ESPaper server.
//
// No probe: the screen fetch the device makes anyway is the evidence. A stored URL is trusted only if
// that fetch returned 200 with exactly ESPAPER_PAYLOAD_SIZE bytes (EspaperParser turns any other
// 200 into HTTP_INTERNAL_CODE_NOT_ESPAPER). A 404, a refusal (-2) or a wrong-size 200 means the
// address no longer belongs to an ESPaper server -- DHCP hands old addresses to new devices.
//
// When the stored URL works this costs nothing: one fetch, no callback. Header-only so the host tests
// compile the real thing.
#ifndef SERVER_TRUST_H
#define SERVER_TRUST_H

#include "EspaperParser.h"

typedef struct ScreenFetch {
  EspaperParser::ResourceResponse response;
  bool trusted; // false: the stored URL is not (or no longer) an ESPaper server
} ScreenFetch;

static inline bool isEspaperScreenResponse(const EspaperParser::ResourceResponse &r) {
  return r.httpCode == 200 && r.payloadBytes == ESPAPER_PAYLOAD_SIZE;
}

// Runs the one fetch and judges it. onStoredUrlRejected runs only on rejection.
// TASK 4 HOOK: pass discovery here (find a server, persist it, fetch again).
static inline ScreenFetch fetchScreenJudged(std::function<EspaperParser::ResourceResponse()> fetch,
                                            std::function<void()> onStoredUrlRejected) {
  ScreenFetch result;
  result.response = fetch();
  result.trusted = isEspaperScreenResponse(result.response);
  if (!result.trusted) {
    onStoredUrlRejected();
  }
  return result;
}

#endif // SERVER_TRUST_H
