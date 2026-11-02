#pragma once

#include "lib/thread/threads.h"

namespace oceanbase { namespace observer {

// The durable queue is the source of truth. Threads only hold a leased request
// group while performing external calls; no business transaction is held open.
class AiColumnWorker final : public lib::Threads
{
public:
  AiColumnWorker() : lib::Threads(2) {}
  int init();
private:
  void run1() override;
  int run_once(bool &worked);
};

} }
