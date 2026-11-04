/*
 * Copyright (c) 2026 OceanBase.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 */

#ifndef OCEANBASE_LIB_VECTOR_CUVS_SEARCH_WORKER_H_
#define OCEANBASE_LIB_VECTOR_CUVS_SEARCH_WORKER_H_

#include <condition_variable>
#include <mutex>
#include <pthread.h>

namespace oceanbase {
namespace common {
namespace obvsag {

// Keep cuVS on one large-stack pthread so repeated SQL queries reuse its HIP
// thread-local state. run() is synchronous: no job/query/index is retained after
// it returns. Inspired by juanzhi-gcb/seekdb commit 13079cc89904c76eaf027dd29998aca5a3045208.
class CuvsSearchWorker final
{
public:
  using Callback = void *(*)(void *);

  explicit CuvsSearchWorker(Callback callback) : callback_(callback) {}

  ~CuvsSearchWorker()
  {
    std::lock_guard<std::mutex> request_guard(request_mutex_);
    if (started_) {
      {
        std::lock_guard<std::mutex> state_guard(state_mutex_);
        stopping_ = true;
      }
      ready_.notify_one();
      pthread_join(thread_, nullptr);
    }
  }

  CuvsSearchWorker(const CuvsSearchWorker &) = delete;
  CuvsSearchWorker &operator=(const CuvsSearchWorker &) = delete;

  bool run(void *job)
  {
    if (job == nullptr || callback_ == nullptr) { return false; }
    // Hold this lock until completion: another submitter must not replace the
    // job pointer or consume the completion notification for a different call.
    std::lock_guard<std::mutex> request_guard(request_mutex_);
    if (!started_) {
      pthread_attr_t attr;
      if (pthread_attr_init(&attr) != 0) { return false; }
      int rc = pthread_attr_setstacksize(&attr, 32UL * 1024 * 1024);
      if (rc == 0) { rc = pthread_create(&thread_, &attr, thread_main, this); }
      pthread_attr_destroy(&attr);
      if (rc != 0) { return false; }
      started_ = true;
    }
    std::unique_lock<std::mutex> state_lock(state_mutex_);
    job_ = job;
    completed_ = false;
    ready_.notify_one();
    done_.wait(state_lock, [this] { return completed_; });
    return true;
  }

private:
  static void *thread_main(void *arg)
  {
    CuvsSearchWorker *worker = static_cast<CuvsSearchWorker *>(arg);
    std::unique_lock<std::mutex> state_lock(worker->state_mutex_);
    for (;;) {
      worker->ready_.wait(state_lock, [worker] {
        return worker->stopping_ || worker->job_ != nullptr;
      });
      if (worker->stopping_) { return nullptr; }
      void *job = worker->job_;
      state_lock.unlock();
      worker->callback_(job);
      state_lock.lock();
      worker->job_ = nullptr;
      worker->completed_ = true;
      worker->done_.notify_one();
    }
  }

  Callback const callback_;
  std::mutex request_mutex_;
  std::mutex state_mutex_;
  std::condition_variable ready_;
  std::condition_variable done_;
  pthread_t thread_{};
  void *job_ = nullptr;
  bool started_ = false;
  bool stopping_ = false;
  bool completed_ = false;
};

} // namespace obvsag
} // namespace common
} // namespace oceanbase

#endif // OCEANBASE_LIB_VECTOR_CUVS_SEARCH_WORKER_H_
