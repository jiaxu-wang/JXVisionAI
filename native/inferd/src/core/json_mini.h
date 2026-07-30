#pragma once

#include <string>

namespace visionai::inferd {

// Minimal helpers for our small model.json (no full JSON parser dependency).
inline std::string JsonGetString(const std::string& json, const std::string& key,
                                 const std::string& def = "") {
  const std::string pat = "\"" + key + "\"";
  auto pos = json.find(pat);
  if (pos == std::string::npos) return def;
  pos = json.find(':', pos + pat.size());
  if (pos == std::string::npos) return def;
  pos = json.find('"', pos + 1);
  if (pos == std::string::npos) return def;
  auto end = json.find('"', pos + 1);
  if (end == std::string::npos) return def;
  return json.substr(pos + 1, end - pos - 1);
}

inline int JsonGetInt(const std::string& json, const std::string& key, int def = 0) {
  const std::string pat = "\"" + key + "\"";
  auto pos = json.find(pat);
  if (pos == std::string::npos) return def;
  pos = json.find(':', pos + pat.size());
  if (pos == std::string::npos) return def;
  while (pos + 1 < json.size() && (json[pos + 1] == ' ' || json[pos + 1] == '\t')) ++pos;
  try {
    return std::stoi(json.substr(pos + 1));
  } catch (...) {
    return def;
  }
}

}  // namespace visionai::inferd
