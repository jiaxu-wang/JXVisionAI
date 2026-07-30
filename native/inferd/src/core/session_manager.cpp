#include "core/session_manager.h"

namespace visionai::inferd {

void SessionManager::Upsert(const SessionConfigLocal& cfg) {
  std::lock_guard<std::mutex> lock(mu_);
  sessions_[cfg.session_id] = cfg;
}

bool SessionManager::Remove(const std::string& session_id) {
  std::lock_guard<std::mutex> lock(mu_);
  return sessions_.erase(session_id) > 0;
}

std::optional<SessionConfigLocal> SessionManager::Get(const std::string& session_id) const {
  std::lock_guard<std::mutex> lock(mu_);
  auto it = sessions_.find(session_id);
  if (it == sessions_.end()) return std::nullopt;
  return it->second;
}

}  // namespace visionai::inferd
