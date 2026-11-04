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
#include "lib/oblog/ob_warning_buffer.h"
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
namespace {
struct IKLexicalKey {
  ObFTLexicalScope scope_;
  uint64_t epoch_ = 0;
  int64_t parser_version_ = -1;
  ObCollationType collation_ = CS_TYPE_INVALID;
  ObFTIKParam::Mode mode_ = ObFTIKParam::Mode::SMART;
  bool operator==(const IKLexicalKey &b) const
  {
    return epoch_ == b.epoch_ && parser_version_ == b.parser_version_
        && collation_ == b.collation_ && mode_ == b.mode_ && scope_ == b.scope_;
  }
};

struct IKLexicalEntry {
  static constexpr int MAX_TEXT = 1024;
  static constexpr int MAX_SPANS = 128;
  struct Span { uint16_t offset_, length_, chars_, freq_; };
  IKLexicalKey key_;
  int text_length_ = 0;
  int count_ = -1; // -1 records only a successful first encounter.
  char text_[MAX_TEXT];
  Span spans_[MAX_SPANS];
  bool matches(const IKLexicalKey &key, const char *text, int length) const
  { return text_length_ == length && key_ == key && MEMCMP(text_, text, length) == 0; }
};
static thread_local IKLexicalEntry ik_lexical_entry;

struct IKSpanReuse {
  enum State { OFF, FIRST, CAPTURE, REPLAY };
  struct PrivateCopy {
    IKLexicalEntry::Span spans_[IKLexicalEntry::MAX_SPANS];
    char text_[IKLexicalEntry::MAX_TEXT];
  };
  State state_ = OFF;
  IKLexicalKey key_;
  const char *input_ = nullptr;
  int input_length_ = 0, count_ = 0, next_ = 0;
  common::ObWarningBuffer *warnings_ = nullptr;
  ObIAllocator *allocator_ = nullptr;
  PrivateCopy *copy_ = nullptr;
  ~IKSpanReuse() { if (copy_ != nullptr) { allocator_->free(copy_); } }

  void begin(const ObFTParserParam &p, const ObFTLexicalScope *scope, ObCollationType collation, uint64_t epoch)
  {
    if (scope == nullptr || !scope->valid() || epoch == 0
        || p.ft_length_ <= 0 || p.ft_length_ > IKLexicalEntry::MAX_TEXT
        || !p.ik_param_.main_dict_.empty() || !p.ik_param_.quan_dict_.empty()
        || !p.ik_param_.stopword_dict_.empty()) { return; }
    warnings_ = common::ob_get_tsi_warning_buffer();
    if (warnings_ == nullptr || warnings_->get_total_warning_count() != 0) { return; }
    key_.scope_ = *scope;
    key_.epoch_ = epoch;
    key_.parser_version_ = p.parser_version_;
    key_.collation_ = collation;
    key_.mode_ = p.ik_param_.mode_;
    input_ = p.fulltext_;
    input_length_ = static_cast<int>(p.ft_length_);
    state_ = FIRST;
    if (!ik_lexical_entry.matches(key_, input_, input_length_)) { return; }
    allocator_ = p.allocator_;
    void *raw = allocator_->alloc(sizeof(PrivateCopy));
    if (raw == nullptr) { state_ = OFF; return; }
    copy_ = new (raw) PrivateCopy;
    // Allocation can yield. Re-check the current worker and never retain a TLS pointer.
    if (common::ob_get_tsi_warning_buffer() != warnings_ || warnings_->get_total_warning_count() != 0) {
      state_ = OFF;
      return;
    }
    if (!ik_lexical_entry.matches(key_, input_, input_length_)) { return; }
    if (ik_lexical_entry.count_ >= 0) {
      count_ = ik_lexical_entry.count_;
      MEMCPY(copy_->spans_, ik_lexical_entry.spans_, count_ * sizeof(copy_->spans_[0]));
      state_ = REPLAY;
    } else {
      MEMCPY(copy_->text_, input_, input_length_);
      state_ = CAPTURE;
    }
  }

  int replay(const char *&word, int64_t &len, int64_t &chars, int64_t &freq)
  {
    if (next_ == count_) { return OB_ITER_END; }
    const auto &span = copy_->spans_[next_++];
    word = input_ + span.offset_; len = span.length_;
    chars = span.chars_; freq = span.freq_;
    return OB_SUCCESS;
  }

  void observe(const char *word, int64_t len, int64_t chars, int64_t freq)
  {
    if (state_ != CAPTURE) { return; }
    const uintptr_t addr = reinterpret_cast<uintptr_t>(word);
    const uintptr_t base = reinterpret_cast<uintptr_t>(input_);
    if (count_ == IKLexicalEntry::MAX_SPANS || len <= 0 || len > input_length_
        || chars <= 0 || chars > UINT16_MAX || freq <= 0 || freq > UINT16_MAX
        || addr < base || addr - base > static_cast<uint64_t>(input_length_ - len)) {
      state_ = OFF;
    } else {
      copy_->spans_[count_++] = {static_cast<uint16_t>(addr-base), static_cast<uint16_t>(len),
                                 static_cast<uint16_t>(chars), static_cast<uint16_t>(freq)};
    }
  }

  void finish()
  {
    if ((state_ != FIRST && state_ != CAPTURE) || common::ob_get_tsi_warning_buffer() != warnings_
        || warnings_->get_total_warning_count() != 0
        || (state_ == CAPTURE && MEMCMP(input_, copy_->text_, input_length_) != 0)) {
      state_ = OFF;
      return;
    }
    if (state_ == FIRST && ik_lexical_entry.matches(key_, input_, input_length_)) {
      // A reentrant iterator may already have published a finished sequence.
    } else {
      ik_lexical_entry.key_ = key_;
      ik_lexical_entry.text_length_ = input_length_;
      MEMCPY(ik_lexical_entry.text_, input_, input_length_);
      ik_lexical_entry.count_ = state_ == CAPTURE ? count_ : -1;
      if (state_ == CAPTURE) {
        MEMCPY(ik_lexical_entry.spans_, copy_->spans_, count_ * sizeof(copy_->spans_[0]));
      }
    }
    state_ = OFF;
  }
};
} // namespace

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
  IKSpanReuse spans_;
  TokenizeContext ctx_;
  ObIKLetterProcessor letter_;
  ObIKQuantifierProcessor quantifier_;
  ObIKCJKProcessor cjk_;
  ObIKSurrogateProcessor surrogate_;
};

int ObIKFTParser::init(const ObFTParserParam &param)
{
  return init(param, nullptr);
}

int ObIKFTParser::init(const ObFTParserParam &param, const ObFTLexicalScope *scope)
{
  int ret = OB_SUCCESS;

  if (IS_INIT) {
    ret = OB_INIT_TWICE;
  } else {
    uint64_t epoch = 0;
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
    } else if (OB_FAIL(hub_->get_shared_ik_dicts(main_dict, quantifier_dict, stop_dict, epoch))) {
    } else if (OB_ISNULL(main_dict) || OB_ISNULL(quantifier_dict)) {
      ret = OB_ERR_UNEXPECTED;
    } else if (OB_ISNULL(segment_ = OB_NEWx(Segment, &allocator_, param, coll_type_, allocator_,
                                            *main_dict, *quantifier_dict))) {
      ret = OB_ALLOCATE_MEMORY_FAILED;
    } else if (OB_FAIL(segment_->ctx_.init())) {
    } else if (scope != nullptr) {
      segment_->spans_.begin(param, scope, coll_type_, epoch);
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
  } else if (segment_->spans_.state_ == IKSpanReuse::REPLAY) {
    return segment_->spans_.replay(word, word_len, char_cnt, word_freq);
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
    if (OB_SUCC(ret)) {
      segment_->spans_.observe(word, word_len, char_cnt, word_freq);
    } else if (ret == OB_ITER_END && segment_->ctx_.iter_end() && !segment_->ctx_.has_result()) {
      segment_->spans_.finish();
    } else {
      segment_->spans_.state_ = IKSpanReuse::OFF;
    }
  }

  return ret;
}

int ObIKFTParser::produce()
{
  int ret = OB_SUCCESS;
  // Loop until end or has data to output
  while (OB_SUCC(ret) && !segment_->ctx_.has_result() && !segment_->ctx_.iter_end()) {
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

const ObIKFTParserDesc &ObIKFTParserDesc::builtin()
{
  static const ObIKFTParserDesc desc;
  return desc;
}

int ObIKFTParserDesc::segment(ObFTParserParam *param, ObITokenIterator *&iter) const
{
  return segment_with_scope(param, iter, nullptr);
}

int ObIKFTParserDesc::segment_with_scope(ObFTParserParam *param, ObITokenIterator *&iter,
                                        const ObFTLexicalScope *scope) const
{
  int ret = OB_SUCCESS;
  ObIKFTParser *parser = nullptr;
  ObFTDictHub *hub = nullptr;
  if (OB_ISNULL(param) || OB_UNLIKELY(!param->is_valid())) {
    ret = OB_INVALID_ARGUMENT;
  } else if (OB_FAIL(ObFTParseData::instance().get_dict_hub(hub))) {
  } else if (OB_ISNULL(parser = OB_NEWx(ObIKFTParser, param->allocator_, *(param->allocator_), hub))) {
    ret = OB_ALLOCATE_MEMORY_FAILED;
  } else if (OB_FAIL(parser->init(*param, scope))) {
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
