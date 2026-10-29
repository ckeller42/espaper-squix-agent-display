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

// ---- Task 4: discovery as the exception path -------------------------------------------------------

// What the exception path did, for the failure screen.
typedef struct DiscoveryOutcome {
  bool discoveryRan = false;
  String found; // what discovery returned; "" if nothing, or if it did not run
} DiscoveryOutcome;

// fetchScreenJudged plus the exception path. In the steady state this is exactly one fetch and none of
// the callbacks run. Only when the stored URL is rejected:
//   - urlIsManual: the URL was hand-entered, so it is never replaced -- discovery does not even run;
//   - otherwise discover() is asked for a server; if it names one, retarget() points the fetcher
//     there, the screen is fetched once more, and adopt() persists the URL ONLY if that fetch is
//     judged trustworthy. A wrong answer is therefore never remembered for the next wake.
static inline ScreenFetch fetchScreenOrDiscover(std::function<EspaperParser::ResourceResponse()> fetch,
                                                bool urlIsManual,
                                                std::function<String()> discover,
                                                std::function<void(const String &)> retarget,
                                                std::function<bool(const String &)> adopt,
                                                DiscoveryOutcome *outcome = nullptr) {
  DiscoveryOutcome local;
  if (outcome == nullptr) outcome = &local;
  bool rejected = false;
  ScreenFetch result = fetchScreenJudged(fetch, [&]() { rejected = true; });
  if (!rejected || urlIsManual) return result;

  outcome->discoveryRan = true;
  outcome->found = discover();
  if (outcome->found == "") return result;

  retarget(outcome->found);
  ScreenFetch second = fetchScreenJudged(fetch, []() {});
  if (second.trusted) adopt(outcome->found);
  return second;
}

// The text for the panel when the stored URL was rejected and discovery did not rescue it. A blank
// panel looks like a flat battery; this says what was tried. The caller draws it.
static inline String describeServerFailure(const String &storedUrl, bool urlIsManual, const DiscoveryOutcome &outcome) {
  String m = String("Cannot reach the ESPaper server.\nTried: ") + storedUrl;
  if (urlIsManual) {
    m += " (entered by hand)\nNot searching: a hand-entered address is never replaced. Change it in the config portal.";
  } else if (outcome.found != "") {
    m += "\nSearched _espaper._tcp and found " + outcome.found + ", but it did not serve a screen.";
  } else {
    m += "\nSearched _espaper._tcp on this network: nothing found.";
  }
  m += "\nRetrying in 1 min.";
  return m;
}

// FORK CHANGE (double refresh): fetchScreenOrDiscover plus the failure screen, in one place, so the
// rule "every untrusted result ends in exactly one screen" lives in code the host tests compile.
// showFailure draws the failure screen and is called exactly once whenever the result is not trusted.
// This also tells the parser to skip its own generic error screen (see getAndDrawScreen).
static inline ScreenFetch fetchScreenOrDiscoverOrReport(EspaperParser *parser,
                                                        std::function<EspaperParser::ResourceResponse()> fetch,
                                                        bool urlIsManual,
                                                        std::function<String()> discover,
                                                        std::function<void(const String &)> retarget,
                                                        std::function<bool(const String &)> adopt,
                                                        const String &storedUrl,
                                                        std::function<void(const String &)> showFailure) {
  DiscoveryOutcome outcome;
  // The parser may skip its generic error screen only because the check below follows every
  // untrusted result. It is switched back off afterwards so nothing else inherits the promise.
  parser->setDeferFailureScreen(true);
  ScreenFetch result = fetchScreenOrDiscover(fetch, urlIsManual, discover, retarget, adopt, &outcome);
  parser->setDeferFailureScreen(false);
  if (!result.trusted) {
    showFailure(describeServerFailure(storedUrl, urlIsManual, outcome));
  }
  return result;
}

#endif // SERVER_TRUST_H
