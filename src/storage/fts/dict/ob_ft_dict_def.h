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

#ifndef _OCEANBASE_STORAGE_FTS_DICT_OB_FT_DICT_DEF_H_
#define _OCEANBASE_STORAGE_FTS_DICT_OB_FT_DICT_DEF_H_

#include "lib/charset/ob_charset.h"

#include <cstdint>

namespace oceanbase
{
namespace storage
{
// Return a scalar only for a single canonical UTF-8 sequence in the BMP.
// Other encodings and multi-character inputs keep their bytewise lookup.
OB_INLINE int canonical_bmp_scalar(const ObString &word)
{
  const auto *p = reinterpret_cast<const unsigned char *>(word.ptr());
  if (word.length() == 1 && p[0] < 0x80) {
    return p[0];
  } else if (word.length() == 2 && p[0] >= 0xc2 && p[0] <= 0xdf && (p[1] & 0xc0) == 0x80) {
    return ((p[0] & 0x1f) << 6) | (p[1] & 0x3f);
  } else if (word.length() == 3 && p[0] >= 0xe0 && p[0] <= 0xef
             && (p[1] & 0xc0) == 0x80 && (p[2] & 0xc0) == 0x80
             && (p[0] != 0xe0 || p[1] >= 0xa0) && (p[0] != 0xed || p[1] < 0xa0)) {
    return ((p[0] & 15) << 12) | ((p[1] & 63) << 6) | (p[2] & 63);
  }
  return -1;
}

typedef int32_t ObFTWordCode;
typedef int32_t ObFTWordBase;
typedef uint32_t ObFTWordStateIndex;

/**
 * @class ObFTSingleWord
 * @brief sturct to store a single character of a charset;
 */
struct ObFTSingleWord
{
public:
  ObFTSingleWord() : word(""), word_len(0) {}
  ObFTSingleWord(const ObFTSingleWord &other) = default;
  ObFTSingleWord &operator=(const ObFTSingleWord &other) = default;

  int32_t set_word(const char *word, int32_t word_len);
  ObString get_word() const;
  bool operator==(const ObFTSingleWord &other) const;

public:
  char word[common::ObCharset::MAX_MB_LEN];
  uint8_t word_len;
} __attribute__((packed));

enum class ObFTDictType : uint32_t
{
  DICT_TYPE_INVALID = 0,
  DICT_IK_MAIN = 1,
  DICT_IK_QUAN = 2,
  DICT_IK_STOP = 3,
};

class ObFTDictDesc
{
public:
  ObFTDictDesc(const ObString &name,
               const ObFTDictType type,
               const ObCharsetType charset,
               const ObCollationType coll_type)
      : name_(name), type_(type), charset_(charset), coll_type_(coll_type)
  {
  }

public:
  ObString name_;
  ObFTDictType type_;
  ObCharsetType charset_;
  ObCollationType coll_type_;
};

} //  namespace storage
} //  namespace oceanbase

#endif // _OCEANBASE_STORAGE_FTS_DICT_OB_FT_DICT_DEF_H_
