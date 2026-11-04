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

#define USING_LOG_PREFIX STORAGE_FTS

#include "src/storage/fts/ob_ik_ft_parser.h"

#include "lib/charset/ob_charset.h"
#include "lib/ob_errno.h"
#include "lib/oblog/ob_log_module.h"
#include "lib/utility/ob_macro_utils.h"
#include "lib/utility/utility.h"
#include "data_plane/fts/ob_fts_struct.h"
#include "data_plane/fts/ob_fts_parser_helper.h"
#include "storage/fts/dict/ob_ft_dict.h"
#include "storage/fts/dict/ob_ft_dict_def.h"
#include "storage/fts/dict/ob_ft_dict_hub.h"
#include "storage/fts/dict/ob_ft_range_dict.h"
#include "storage/fts/ik/ob_ik_arbitrator.h"
#include "storage/fts/ik/ob_ik_cjk_processor.h"
#include "storage/fts/ik/ob_ik_letter_processor.h"
#include "storage/fts/ik/ob_ik_processor.h"
#include "storage/fts/ik/ob_ik_quantifier_processor.h"
#include "storage/fts/ik/ob_ik_surrogate_processor.h"

namespace oceanbase
{
namespace storage
{
// Keep the four fixed-order state machines and their context in one
// allocation for the lifetime of a single document.
struct ObIKFTParser::Segment
{
  Segment(const ObFTParserParam &param, ObCollationType coll, ObIAllocator &alloc,
          const ObIFTDict &main_dict, const ObIFTDict &quantifier_dict)
    : ctx_(coll, alloc, param.fulltext_, param.ft_length_,
           param.ik_param_.mode_ == ObFTIKParam::Mode::SMART),
      quantifier_(quantifier_dict, alloc), cjk_(main_dict, alloc)
  {}
  TokenizeContext ctx_;
  ObIKLetterProcessor letter_;
  ObIKQuantifierProcessor quantifier_;
  ObIKCJKProcessor cjk_;
  ObIKSurrogateProcessor surrogate_;
};

int ObIKFTParser::init(const ObFTParserParam &param)
{
  int ret = OB_SUCCESS;

  if (IS_INIT) {
    ret = OB_INIT_TWICE;
  } else {
    ObIFTDict *main_dict = nullptr;
    ObIFTDict *quantifier_dict = nullptr;
    ObIFTDict *stop_dict = nullptr;
    coll_type_ = ObCollationType::CS_TYPE_INVALID;
    if (OB_ISNULL(param.cs_) || OB_ISNULL(param.cs_->name)) {
      ret = OB_INVALID_ARGUMENT;
    } else if (CS_TYPE_INVALID == (coll_type_ = ObCharset::collation_type(param.cs_->name))) {
      ret = OB_INVALID_ARGUMENT;
    } else if (OB_ISNULL(hub_)) {
      ret = OB_ERR_UNEXPECTED;
    } else if (OB_FAIL(hub_->get_shared_ik_dicts(main_dict, quantifier_dict, stop_dict))) {
    } else if (OB_ISNULL(main_dict) || OB_ISNULL(quantifier_dict)) {
      ret = OB_ERR_UNEXPECTED;
    } else if (OB_ISNULL(segment_ = OB_NEWx(Segment, &allocator_, param, coll_type_, allocator_,
                                            *main_dict, *quantifier_dict))) {
      ret = OB_ALLOCATE_MEMORY_FAILED;
    } else if (OB_FAIL(segment_->ctx_.init())) {
    }

    if (OB_FAIL(ret)) {
      reset();
    } else {
      is_inited_ = true;
    }
  }

  return ret;
}

int ObIKFTParser::get_next_token(const char *&word,
                                 int64_t &word_len,
                                 int64_t &char_cnt,
                                 int64_t &word_freq)
{
  int ret = OB_SUCCESS;
  const char *output_word;
  int64_t len;
  int64_t offset;
  int64_t cnt;

  if (!IS_INIT) {
    ret = OB_NOT_INIT;
  } else {
    bool accept_token = false;
    while (OB_SUCC(ret) && !accept_token) {
      if (OB_FAIL(produce())) {
      } else if (OB_FAIL(segment_->ctx_.get_next_token(output_word, len, offset, cnt))) {
        if (OB_ITER_END == ret) {
          // ok, end this iter
        } else {
        }
      } else {
        bool is_stop = false;
        // if (!OB_ISNULL(dict_stop_)
        //     && OB_FAIL(dict_stop_->match(ObString(len, output_word + offset), is_stop))) {
        //   LOG_WARN("Failed to match stopwords", K(ret));
        // } else
        if (!is_stop) {
          word = output_word + offset;
          word_len = len;
          char_cnt = cnt;
          word_freq = 1;
          accept_token = true;
        } else {
        }
      }
    }
  }

  return ret;
}

int ObIKFTParser::produce()
{
  int ret = OB_SUCCESS;
  // Loop until end or has data to output
  while (OB_SUCC(ret) && segment_->ctx_.result_list().empty() && !segment_->ctx_.iter_end()) {
    if (OB_FAIL(process_next_batch())) {
      if (OB_ITER_END == ret) {
        // ok
      } else {
      }
    }
  }
  if (OB_ITER_END == ret) {
    ret = OB_SUCCESS;
  }
  return ret;
}

int ObIKFTParser::process_one_char(TokenizeContext &ctx,
                                   const char *ch,
                                   const uint8_t char_len,
                                   const ObFTCharUtil::CharType type)
{
  int ret = OB_SUCCESS;
  if (OB_FAIL(segment_->letter_.ObIKLetterProcessor::do_process(ctx, ch, char_len, type))) {
  } else if (OB_FAIL(segment_->quantifier_.ObIKQuantifierProcessor::do_process(ctx, ch, char_len, type))) {
  } else if (OB_FAIL(segment_->cjk_.ObIKCJKProcessor::do_process(ctx, ch, char_len, type))) {
  } else if (OB_FAIL(segment_->surrogate_.ObIKSurrogateProcessor::do_process(ctx, ch, char_len, type))) {
  }
  return ret;
}

int ObIKFTParser::process_next_batch()
{
  int ret = OB_SUCCESS;
  segment_->ctx_.reset_resource();

  // handle next segmenter
  bool do_seg = false;

  if (segment_->ctx_.iter_end()) {
    ret = OB_ITER_END;
  } else {
    while (OB_SUCC(ret) && !do_seg && !segment_->ctx_.iter_end()) {
      const char *ch;
      uint8_t char_len = 0;
      ObFTCharUtil::CharType type = ObFTCharUtil::CharType::USELESS;
      if (OB_FAIL(segment_->ctx_.current_char(ch, char_len))) {
      } else if (OB_FAIL(segment_->ctx_.current_char_type(type))) {
      } else if (OB_FAIL(process_one_char(segment_->ctx_, ch, char_len, type))) {
      } else {
        // 1. check segmention
        if (segment_->ctx_.handle_size() > SEGMENT_LIMIT && type == ObFTCharUtil::CharType::USELESS) {
          do_seg = true;
        }

        // 2. move to next;
        if (OB_FAIL(segment_->ctx_.step_next())) {
          if (OB_ITER_END == ret) {
          } else {
          }
        }
      } // end of one batch
    }

    if (OB_SUCC(ret) || OB_ITER_END == ret) {
      ObIKArbitrator arb;
      if (OB_FAIL(arb.process(segment_->ctx_))) {
      } else if (OB_FAIL(arb.output_result(segment_->ctx_))) {
      }
    } else {
      // Already logged.
    }
  }

  return ret;
}

int ObIKFTParserDesc::segment(ObFTParserParam *param, ObITokenIterator *&iter) const
{
  int ret = OB_SUCCESS;
  ObIKFTParser *parser = nullptr;
  ObFTDictHub *hub = nullptr;
  if (OB_ISNULL(param) || OB_UNLIKELY(!param->is_valid())) {
    ret = OB_INVALID_ARGUMENT;
  } else if (OB_FAIL(ObFTParseData::instance().get_dict_hub(hub))) {
  } else if (OB_ISNULL(parser = OB_NEWx(ObIKFTParser, param->allocator_, *(param->allocator_), hub))) {
    ret = OB_ALLOCATE_MEMORY_FAILED;
  } else if (OB_FAIL(parser->init(*param))) {
  } else {
    iter = parser;
  }

  if (OB_FAIL(ret)) {
    OB_DELETEx(ObIKFTParser, param->allocator_, parser);
  }

  return ret;
}

void ObIKFTParserDesc::free_token_iter(ObFTParserParam *param,
                                       ObITokenIterator *&iter) const
{
  iter->~ObITokenIterator();
  param->allocator_->free(iter);
}


int ObIKFTParserDesc::get_add_word_flag(ObAddWordFlag &flag) const
{
  int ret = OB_SUCCESS;
  flag.set_casedown();
  flag.set_groupby_word();
  return ret;
}

void ObIKFTParser::reset()
{
  if (segment_ != nullptr) {
    segment_->~Segment();
    allocator_.free(segment_);
    segment_ = nullptr;
  }
  is_inited_ = false;
}

} //  namespace storage
} //  namespace oceanbase
