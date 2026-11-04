/*
 * Copyright (c) 2025 OceanBase.
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *     http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#define USING_LOG_PREFIX STORAGE

#include "ob_text_daat_iter.h"

namespace oceanbase
{
namespace storage
{
int ObTextDaaTIter::init(const ObTextDaaTParam &param)
{
  int ret = OB_SUCCESS;
  if (OB_ISNULL(param.base_param_) || OB_ISNULL(param.dim_iters_) || OB_ISNULL(param.allocator_)
      || OB_ISNULL(param.relevance_collector_)) {
    ret = OB_INVALID_ARGUMENT;
  } else if (OB_FAIL(ObSRDaaTIterImpl::init(*param.base_param_, *param.dim_iters_,
                                            *param.allocator_, *param.relevance_collector_))) {
  } else if (param.base_param_->relevance_expr_ != nullptr
             && OB_FAIL(bm25_param_estimator_.init(param.bm25_param_est_ctx_))) {
  } else {
    mode_flag_ = param.mode_flag_;
    function_lookup_mode_ = param.function_lookup_mode_;
    membership_min_matches_ = param.minimum_should_match_;
  }
  return ret;
}

void ObTextDaaTIter::reset()
{
  for (auto &batch : postings_) { batch = {}; }
  bm25_param_estimator_.reset();
  // this class can know the type of dim_iters_, but ObSRDaaTIterImpl maybe not
  if (OB_NOT_NULL(dim_iters_)) {
    for (int64_t i = 0; i < dim_iters_->count(); ++i) {
      static_cast<ObTextRetrievalDaaTTokenIter *>(dim_iters_->at(i))->reset();
    }
  }
  ObSRDaaTIterImpl::reset();
}

void ObTextDaaTIter::reuse(const bool switch_tablet)
{
  for (auto &batch : postings_) { batch = {}; }
  if ((OB_NOT_NULL(dim_iters_) && 0 == dim_iters_->count())) {
    // do nothing
  } else {
    bm25_param_estimator_.reuse(switch_tablet);
  }
  if (OB_NOT_NULL(dim_iters_)) {
    for (int64_t i = 0; i < dim_iters_->count(); ++i) {
      static_cast<ObTextRetrievalDaaTTokenIter *>(dim_iters_->at(i))->reuse();
    }
  }
  ObSRDaaTIterImpl::reuse(switch_tablet);
}

int ObTextDaaTIter::pre_process()
{
  int ret = OB_SUCCESS;
  if (dim_iters_->count() == 0) {
    ret = OB_ITER_END;
  } else if (iter_param_->relevance_expr_ != nullptr) {
    if (OB_FAIL(bm25_param_estimator_.do_estimation(*iter_param_->eval_ctx_))) {
    }
  }
  return ret;
}

int ObTextDaaTIter::merge_rows(const int64_t capacity, int64_t &count)
{
  const int64_t streams = dim_iters_->count();
  if (membership_min_matches_ < 0 || streams == 0 || streams > MAX_SHORT_STREAMS
      || function_lookup_mode_ || mode_flag_ != sql::ObMatchAgainstMode::NATURAL_LANGUAGE_MODE
      || !iter_param_->eval_ctx_->is_vectorized() || iter_param_->relevance_expr_ != nullptr
      || iter_param_->dim_weights_ != nullptr || iter_param_->need_filter()
      || iter_param_->need_project_relevance() || iter_param_->need_pushdown_topk()) {
    return ObSRDaaTIterImpl::merge_rows(capacity, count);
  }
  int ret = OB_SUCCESS;
  while (OB_SUCC(ret) && count < capacity) {
    ObSRMergeItem winner;
    int64_t matching = 0;
    int64_t active = 0;
    for (int64_t i = 0; OB_SUCC(ret) && i < streams; ++i) {
      PostingBatch &batch = postings_[i];
      if (!batch.end_ && batch.pos_ == batch.size_) {
        auto *stream = static_cast<ObTextRetrievalDaaTTokenIter *>(dim_iters_->at(i));
        batch.pos_ = 0;
        if (OB_FAIL(stream->read_membership_batch(batch.ids_, batch.size_)) && ret == OB_ITER_END) {
          batch.end_ = true;
          ret = OB_SUCCESS;
        }
      }
      if (OB_SUCC(ret) && !batch.end_) {
        ++active;
        ObSRMergeItem head;
        head.iter_idx_ = i;
        iter_domain_ids_[i] = &batch.ids_[batch.pos_].get_datum();
        int64_t order = -1;
        if (winner.iter_idx_ >= 0 && OB_FAIL(merge_cmp_.cmp(head, winner, order))) {
        } else if (order <= 0) {
          if (order < 0) {
            winner = head;
            matching = 0;
          }
          next_round_iter_idxes_[matching++] = i;
        }
      }
    }
    if (OB_SUCC(ret)) {
      if (winner.iter_idx_ < 0) {
        ret = OB_ITER_END;
      } else if (active == 1) {
        PostingBatch &batch = postings_[winner.iter_idx_];
        if (membership_min_matches_ > 1) {
          batch.pos_ = batch.size_;
        } else {
          while (OB_SUCC(ret) && count < capacity && batch.pos_ < batch.size_) {
            ret = cache_result(count, batch.ids_[batch.pos_++].get_datum(), 1.0);
          }
        }
      } else {
        if (matching >= membership_min_matches_) {
          ret = cache_result(count, *iter_domain_ids_[winner.iter_idx_], static_cast<double>(matching));
        }
        for (int64_t i = 0; i < matching; ++i) {
          ++postings_[next_round_iter_idxes_[i]].pos_;
        }
      }
    }
  }
  return ret;
}

int ObTextDaaTIter::do_one_merge_round(int64_t &count)
{
  // A small unweighted union needs just one head per sorted posting list.
  // The inner product of unit scores is exactly the number of equal heads.
  const int64_t streams = dim_iters_->count();
  if (membership_min_matches_ < 0 || streams > 4 || function_lookup_mode_
      || mode_flag_ != sql::ObMatchAgainstMode::NATURAL_LANGUAGE_MODE
      || iter_param_->relevance_expr_ != nullptr || iter_param_->dim_weights_ != nullptr) {
    return ObSRDaaTIterImpl::do_one_merge_round(count);
  }

  int ret = OB_SUCCESS;
  for (int64_t i = 0; OB_SUCC(ret) && i < next_round_cnt_; ++i) {
    const int64_t idx = next_round_iter_idxes_[i];
    auto *stream = static_cast<ObTextRetrievalDaaTTokenIter *>(dim_iters_->at(idx));
    if (OB_FAIL(stream->get_next_row())) {
      if (ret == OB_ITER_END) {
        iter_domain_ids_[idx] = nullptr;
        ret = OB_SUCCESS;
      }
    } else if (OB_FAIL(stream->get_curr_id(iter_domain_ids_[idx]))) {
    }
  }
  next_round_cnt_ = 0;
  ObSRMergeItem winner;
  for (int64_t idx = 0; OB_SUCC(ret) && idx < streams; ++idx) {
    if (iter_domain_ids_[idx] != nullptr) {
      ObSRMergeItem head;
      head.iter_idx_ = idx;
      int64_t order = -1;
      if (winner.iter_idx_ >= 0 && OB_FAIL(merge_cmp_.cmp(head, winner, order))) {
      } else if (order <= 0) {
        if (order < 0) {
          winner = head;
          next_round_cnt_ = 0;
        }
        next_round_iter_idxes_[next_round_cnt_++] = idx;
      }
    }
  }
  if (OB_SUCC(ret)) {
    if (winner.iter_idx_ < 0) {
      ret = OB_ITER_END;
    } else if (next_round_cnt_ >= membership_min_matches_) {
      const double score = static_cast<double>(next_round_cnt_);
      bool project = true;
      if (iter_param_->need_filter() && OB_FAIL(filter_on_demand(count, score, project))) {
      } else if (project) {
        ret = cache_result(count, *iter_domain_ids_[winner.iter_idx_], score);
      }
    }
  }
  return ret;
}

ObTextBMWIter::ObTextBMWIter()
  : ObSRBMWIterImpl(),
    bm25_param_estimator_() {}

void ObTextBMWIter::reuse(const bool switch_tablet)
{
  bm25_param_estimator_.reuse(switch_tablet);
  if (OB_NOT_NULL(dim_iters_)) {
    for (int64_t i = 0; i < dim_iters_->count(); ++i) {
      static_cast<ObTextRetrievalBlockMaxIter *>(dim_iters_->at(i))->reuse();
    }
  }
  ObSRBMWIterImpl::reuse(switch_tablet);
}

void ObTextBMWIter::reset()
{
  bm25_param_estimator_.reset();
  if (OB_NOT_NULL(dim_iters_)) {
    for (int64_t i = 0; i < dim_iters_->count(); ++i) {
      static_cast<ObTextRetrievalBlockMaxIter *>(dim_iters_->at(i))->reset();
    }
  }
  ObSRBMWIterImpl::reset();
}

int ObTextBMWIter::init(const ObTextDaaTParam &param)
{
  int ret = OB_SUCCESS;
  if (OB_ISNULL(param.base_param_) || OB_ISNULL(param.dim_iters_) || OB_ISNULL(param.allocator_)
      || OB_ISNULL(param.relevance_collector_)) {
    ret = OB_INVALID_ARGUMENT;
  } else if (OB_FAIL(ObSRBMWIterImpl::init(*param.base_param_, *param.dim_iters_,
                                           *param.allocator_, *param.relevance_collector_))) {
  } else if (param.base_param_->relevance_expr_ != nullptr
             && OB_FAIL(bm25_param_estimator_.init(param.bm25_param_est_ctx_))) {
  }
  return ret;
}

int ObTextBMWIter::get_next_rows(const int64_t capacity, int64_t &count)
{
  int ret = OB_SUCCESS;
  if (IS_NOT_INIT) {
    ret = OB_NOT_INIT;
  } else if (dim_iters_->count() == 0) {
    ret = OB_ITER_END;
  } else if (OB_FAIL(bm25_param_estimator_.do_estimation(*iter_param_->eval_ctx_))) {
  }

  if (FAILEDx(ObSRBMWIterImpl::get_next_rows(capacity, count))) {
    if (OB_UNLIKELY(OB_ITER_END != ret)) {
    }
  }
  return ret;
}

int ObTextBMWIter::init_before_wand_process()
{
  int ret = OB_SUCCESS;
  if (OB_UNLIKELY(!bm25_param_estimator_.is_estimated())) {
    ret = OB_ERR_UNEXPECTED;
  }

  for (int64_t i = 0; OB_SUCC(ret) && i < dim_iters_->count(); ++i) {
    ObTextRetrievalBlockMaxIter *block_max_iter = static_cast<ObTextRetrievalBlockMaxIter *>(dim_iters_->at(i));
    if (OB_FAIL(block_max_iter->init_block_max_iter(
        bm25_param_estimator_.get_total_doc_cnt(), bm25_param_estimator_.get_avg_doc_token_cnt()))) {
    }
  }
  return ret;
}

} // namespace storage
} // namespace oceanbase
