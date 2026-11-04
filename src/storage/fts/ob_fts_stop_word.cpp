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

#include "object/ob_object.h"
#define USING_LOG_PREFIX STORAGE_FTS

#include "share/rc/ob_server_runtime.h"
#include "storage/fts/ob_fts_stop_word.h"
#include "storage/fts/ob_fts_parser_helper.h"
#include "storage/fts/ob_fts_parser_property.h"

namespace oceanbase
{
namespace storage
{

////////////////////////////////////////////////////////////////////////////////
// class ObStopWordChecker
static int ascii_letter_index(unsigned char c)
{
  const int lower = c | 0x20;
  return lower >= 'a' && lower <= 'z' ? lower - 'a' : -1;
}

ObStopWordChecker::~ObStopWordChecker()
{
  destroy();
}

int ObStopWordChecker::init()
{
  int ret = OB_SUCCESS;
  
  

  if (inited_) {
    ret = OB_INIT_TWICE;
  } else if (OB_FAIL(stopword_set_.create(DEFAULT_STOPWORD_BUCKET_NUM, "StopWordSet", "StopWordSet"))) {
  } else {
    ObObjMeta stop_meta;
    stop_meta.set_varchar();
    stop_meta.set_collation_type(ObCollationType::CS_TYPE_UTF8MB4_GENERAL_CI);

    stopword_type_.set_meta(stop_meta);
    MEMSET(ascii_prefixes_, 0, sizeof(ascii_prefixes_));
    can_filter_ascii_prefix_ = true;
    const int64_t stopword_count = sizeof(ob_stop_word_list) / sizeof(ob_stop_word_list[0]);
    for (int64_t i = 0; OB_SUCC(ret) && i < stopword_count; ++i) {
      const char *text = ob_stop_word_list[i];
      const int64_t length = STRLEN(text);
      for (int64_t j = 0; j < length; ++j) {
        if (ascii_letter_index(text[j]) < 0) {
          can_filter_ascii_prefix_ = false;
        }
      }
      if (can_filter_ascii_prefix_ && length >= 2) {
        ascii_prefixes_[ascii_letter_index(text[0])] |= 1U << ascii_letter_index(text[1]);
      }
      ObFTWord stopword(length, text, stopword_type_);
      if (OB_FAIL(stopword_set_.set_refactored(stopword))) {
      }
    }

    if (OB_SUCC(ret)) {
      inited_ = true;
    }
  }
  return ret;
}

void ObStopWordChecker::destroy()
{
  if (inited_) {
    stopword_set_.destroy();
    inited_ = false;
  }
}

int ObStopWordChecker::check_stopword(const ObFTWord &word, bool &is_stopword)
{
  int ret = OB_SUCCESS;
  if (OB_UNLIKELY(!inited_)) {
    ret = OB_NOT_INIT;
  } else if (OB_UNLIKELY(word.empty())) {
    ret = OB_INVALID_ARGUMENT;
  } else if (ObCharset::charset_type_by_coll(word.get_collation_type()) == CHARSET_UTF8MB4) {
    // For UTF-8 input charset_convert returns the same bytes. Still compare
    // using the stopword set's collation, independent of the column collation.
    ret = contains_utf8(word.get_word().get_string(), is_stopword);
  } else {
    common::ObArenaAllocator allocator(lib::ObMemAttr("ChkStopWord"));
    ObString converted;
    if (OB_FAIL(ObCharset::charset_convert(allocator, word.get_word().get_string(),
                                          word.get_collation_type(),
                                          stopword_type_.get_collation_type(), converted))) {
    } else {
      ret = contains_utf8(converted, is_stopword);
    }
  }
  return ret;
}

int ObStopWordChecker::contains_utf8(const ObString &text, bool &is_stopword)
{
  // In utf8mb4_general_ci each leading ASCII letter has its own folded
  // weight. Two such weights absent from the dictionary exclude a match.
  if (can_filter_ascii_prefix_ && text.length() >= 2) {
    const int first = ascii_letter_index(text.ptr()[0]);
    const int second = ascii_letter_index(text.ptr()[1]);
    if (first >= 0 && second >= 0 && !(ascii_prefixes_[first] & (1U << second))) {
      is_stopword = false;
      return OB_SUCCESS;
    }
  }
  ObFTWord key(text.length(), text.ptr(), stopword_type_);
  int ret = stopword_set_.exist_refactored(key);
  if (ret == OB_HASH_EXIST || ret == OB_HASH_NOT_EXIST) {
    is_stopword = ret == OB_HASH_EXIST;
    ret = OB_SUCCESS;
  } else if (ret == OB_SUCCESS) {
    ret = OB_ERR_UNEXPECTED;
  }
  return ret;
}

////////////////////////////////////////////////////////////////////////////////
// class ObAddWord
ObAddWord::ObAddWord(
    const ObFTParserProperty &property,
    const ObObjMeta &meta,
    const ObAddWordFlag &flag,
    common::ObIAllocator &allocator,
    ObFTWordMap &word_map)
  : word_meta_(meta),
    allocator_(allocator),
    word_map_(word_map),
    min_max_word_cnt_(0),
    non_stopword_cnt_(0),
    stopword_cnt_(0),
    min_token_size_(property.min_token_size_),
    max_token_size_(property.max_token_size_),
    flag_(flag)
{
}

int ObAddWord::process_word(
    const char *word,
    const int64_t word_len,
    const int64_t char_cnt,
    const int64_t word_freq)
{
  int ret = OB_SUCCESS;
  bool is_stopword = false;
  ObFTWord src_word(word_len, word, word_meta_);
  ObFTWord dst_word;
  if (OB_ISNULL(word) || OB_UNLIKELY(0 >= word_len || 0 >= char_cnt || 0 >= word_freq)) {
    ret = OB_INVALID_ARGUMENT;
  } else if (is_min_max_word(char_cnt)) {
    ++min_max_word_cnt_;
  } else if (OB_FAIL(casedown_word(src_word, dst_word))) {
  } else if (OB_FAIL(check_stopword(dst_word, is_stopword))) {
  } else if (OB_UNLIKELY(is_stopword)) {
    ++stopword_cnt_;
  } else if (OB_FAIL(groupby_word(dst_word, word_freq))) {
  } else {
    non_stopword_cnt_ += word_freq;
  }
  return ret;
}

bool ObAddWord::is_min_max_word(const int64_t c_len) const
{
  return flag_.min_max_word() && (c_len < min_token_size_ || c_len > max_token_size_);
}

int ObAddWord::casedown_word(const ObFTWord &src, ObFTWord &dst)
{
  int ret = OB_SUCCESS;
  if (OB_UNLIKELY(src.empty())) {
    ret = OB_INVALID_ARGUMENT;
  } else if (flag_.casedown()) {
    ObString dst_str;
    if (OB_FAIL(ObCharset::tolower(
                    word_meta_.get_collation_type(),
                    src.get_word().get_string(),
                    dst_str,
                    allocator_))) {
    } else {
      ObFTWord tmp(dst_str.length(), dst_str.ptr(), word_meta_);
      dst = tmp;
    }
  } else {
    dst = src;
  }
  return ret;
}

int ObAddWord::check_stopword(const ObFTWord &ft_word, bool &is_stopword)
{
  int ret = OB_SUCCESS;
  if (OB_UNLIKELY(ft_word.empty())) {
    ret = OB_INVALID_ARGUMENT;
  } else if (flag_.stopword()) {
    ObStopWordChecker *stop_word_checker = ObFTParseData::instance().stop_word_checker();
    if (OB_ISNULL(stop_word_checker)) {
      ret = OB_ERR_UNEXPECTED;
    } else if (OB_FAIL(stop_word_checker->check_stopword(ft_word, is_stopword))) {
    }
  }
  return ret;
}

int ObAddWord::groupby_word(const ObFTWord &word, const int64_t word_freq)
{
  if (OB_UNLIKELY(word.empty() || word_freq <= 0)) {
    return OB_INVALID_ARGUMENT;
  }
  return word_map_.add(word, word_freq, flag_.groupby_word());
}

} // end namespace storage
} // end namespace oceanbase
