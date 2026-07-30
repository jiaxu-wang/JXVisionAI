#pragma once

#include <map>
#include <mutex>
#include <optional>
#include <string>
#include <vector>

namespace visionai::inferd {

struct SessionConfigLocal {
  std::string session_id;
  std::string model_name = "primary";
  float conf = 0.25f;
  int imgsz = 640;
  std::vector<int> class_filter;
};

class SessionManager {
 public:
  void Upsert(const SessionConfigLocal& cfg);
  bool Remove(const std::string& session_id);
  std::optional<SessionConfigLocal> Get(const std::string& session_id) const;

 private:
  mutable std::mutex mu_;
  std::map<std::string, SessionConfigLocal> sessions_;
};

}  // namespace visionai::inferd
