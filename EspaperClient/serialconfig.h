#ifndef SERIAL_CONFIG_H
#define SERIAL_CONFIG_H

// FORK ADDITION: configure the device over the USB serial line.
//
// Upstream's only configuration channel is the setup access point: join 'ESPaperConfig' with a
// second radio, then POST the form. That channel fails in ways the serial line does not -- a host
// that drops the AP association mid-POST, a host with one radio that must stay on the LAN, an AP
// out of range, or a device already on a WiFi whose password has changed. Whoever can flash the
// device can already read and write its whole flash, so a cable that configures it grants no
// access that the same cable did not already grant.
//
// The grammar is deliberately line-based and forgiving: one command per line, values taken
// verbatim to end of line so a password or time zone may contain spaces and '='.
//
//   set ssid <value>        set password <value>     set timezone <value>
//   set ntp <value>         set server <url>         set interval <minutes>
//   show                    save                     restart                  help
//
// Requires the settings globals and saveConfig()/setServerUrlFromInput() -- include it from
// configportal.h, after those are defined.

struct SerialConfigOutcome {
  String reply;   // what to print back; empty means "nothing to say"
  bool saved;     // the configuration was written to the filesystem
  bool restart;   // the caller should restart the device
};

// Everything after the command word, with no trimming: a password's trailing space is part of it.
static String serialConfigValue(const String &line, uint16_t afterCommand) {
  return afterCommand >= line.length() ? String("") : line.substring(afterCommand);
}

static String serialConfigShow() {
  // WIFI_PASS is deliberately never echoed: the serial console is often a shared terminal, and a
  // session transcript outlives the session. Whether one is set is what a person needs to know.
  return "ssid=" + WIFI_SSID + "\npassword=" + (WIFI_PASS == "" ? "(unset)" : "(set)") +
         "\ntimezone=" + TIMEZONE + "\nntp=" + NTP_SERVERS + "\nserver=" + SERVER_URL +
         " (" + (SERVER_URL_SOURCE == "" ? String("default") : SERVER_URL_SOURCE) + ")" +
         "\ninterval=" + String(UPDATE_INTERVAL_MINS);
}

static String serialConfigHelp() {
  return "set ssid <value> | set password <value> | set timezone <value> | set ntp <value> | "
         "set server <url> | set interval <minutes> | show | save | restart | help";
}

SerialConfigOutcome applySerialConfigCommand(String line) {
  // Leading indentation and the CR a terminal sends with LF are noise. A TRAILING SPACE IS NOT:
  // it can be the last character of a WiFi password, so values keep whatever follows the command
  // word. Only the argument-less commands are matched against a fully trimmed copy.
  while (line.length() > 0 && (line.charAt(0) == ' ' || line.charAt(0) == '\t')) {
    line.remove(0, 1);
  }
  while (line.length() > 0 &&
         (line.charAt(line.length() - 1) == '\r' || line.charAt(line.length() - 1) == '\n')) {
    line.remove(line.length() - 1);
  }
  String bare = line;
  bare.trim();
  SerialConfigOutcome outcome = {"", false, false};
  if (bare == "") {
    return outcome;
  }
  if (bare == "show") {
    outcome.reply = serialConfigShow();
  } else if (bare == "help") {
    outcome.reply = serialConfigHelp();
  } else if (bare == "restart") {
    outcome.reply = "Restarting";
    outcome.restart = true;
  } else if (bare == "save") {
    // The same three fields loadConfig() insists on. Saving without them writes a config the
    // device rejects on the next boot, which looks like a failed save an hour later.
    if (WIFI_SSID == "" || WIFI_PASS == "" || TIMEZONE == "") {
      outcome.reply = "ERR need ssid, password and timezone before save";
    } else {
      outcome.saved = saveConfig();
      outcome.reply = outcome.saved ? "Saved" : "ERR could not write the configuration file";
    }
  } else if (line.startsWith("set ssid")) {
    WIFI_SSID = serialConfigValue(line, 9);
    outcome.reply = "ssid=" + WIFI_SSID;
  } else if (line.startsWith("set password")) {
    WIFI_PASS = serialConfigValue(line, 13);
    outcome.reply = "password=(set)";
  } else if (line.startsWith("set timezone")) {
    TIMEZONE = serialConfigValue(line, 13);
    outcome.reply = "timezone=" + TIMEZONE;
  } else if (line.startsWith("set ntp")) {
    NTP_SERVERS = serialConfigValue(line, 8);
    outcome.reply = "ntp=" + NTP_SERVERS;
  } else if (line.startsWith("set server")) {
    setServerUrlFromInput(serialConfigValue(line, 11));
    outcome.reply = "server=" + SERVER_URL;
  } else if (line.startsWith("set interval")) {
    UPDATE_INTERVAL_MINS = serialConfigValue(line, 13).toInt();
    outcome.reply = "interval=" + String(UPDATE_INTERVAL_MINS);
  } else {
    outcome.reply = "ERR unknown command. " + serialConfigHelp();
  }
  return outcome;
}

#endif
