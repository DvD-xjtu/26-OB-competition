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

#include "data_plane/fts/ob_fts_struct.h"

#include <algorithm>

#include "lib/charset/ob_charset.h"
#include "share/datum/ob_datum_funcs.h"
#include "storage/ob_storage_util.h"

namespace oceanbase
{
namespace storage
{

int ObFTWordMap::create(int64_t bucket_count, const common::ObMemAttr &attr)
{
  int ret = OB_SUCCESS;
  if (bucket_count <= 0) {
    ret = OB_INVALID_ARGUMENT;
  } else if (created()) {
    ret = OB_INIT_TWICE;
  } else {
    heads_.set_attr(attr);
    entries_.set_attr(attr);
    // Match ObHashMap's bucket selection and head insertion order so JSON
    // output and query-token order stay identical even for hash collisions.
    if (OB_FAIL(heads_.prepare_allocate(common::hash::cal_next_prime(bucket_count)))) {
    } else {
      std::fill_n(&heads_.at(0), heads_.count(), int64_t(-1));
    }
  }
  return ret;
}

void ObFTWordMap::reuse()
{
  if (size() != 0) {
    entries_.reuse();
    std::fill_n(&heads_.at(0), heads_.count(), int64_t(-1));
  }
}

int ObFTWordMap::add(const ObFTWord &word, int64_t frequency, bool group)
{
  int ret = OB_SUCCESS;
  uint64_t hash = 0;
  if (!created()) {
    ret = OB_NOT_INIT;
  } else if (OB_FAIL(word.hash(hash))) {
  } else {
    const int64_t bucket = hash % heads_.count();
    int64_t idx = heads_.at(bucket);
    while (idx >= 0 && entries_.at(idx).first != word) {
      idx = entries_.at(idx).next;
    }
    if (idx >= 0) {
      if (!group) {
        ret = OB_HASH_EXIST;
      } else {
        // The old overwrite operation replaced the key as well: collations
        // can equate different spellings, and the last spelling is returned.
        Entry &entry = entries_.at(idx);
        entry.first = word;
        entry.second += frequency;
      }
    } else {
      const int64_t new_idx = entries_.count();
      if (OB_FAIL(entries_.push_back(Entry{word, 1, heads_.at(bucket)}))) {
      } else {
        heads_.at(bucket) = new_idx;
      }
    }
  }
  return ret;
}

int ObFTWord::hash(uint64_t &hash_val) const
{
  int ret = OB_SUCCESS;
  common::ObDatumBasicFuncs *funcs = ObDatumFuncs::get_basic_func(meta_.get_type(), meta_.get_collation_type());
  if (OB_ISNULL(funcs)) {
    ret = OB_ERR_UNEXPECTED;
  } else if (funcs->default_hash_ == nullptr) {
    ret = OB_ERR_UNEXPECTED;
  } else {
    ret = funcs->default_hash_(word_, 0, hash_val, nullptr);
  }
  return ret;
}
bool ObFTWord::operator==(const ObFTWord &other) const
{
  bool is_equal = false;
  int ret = OB_SUCCESS;
  int cmp_ret = 0;
  ObDatumCmpFuncType func = get_datum_cmp_func(meta_, other.meta_);
  if (func == nullptr) {
    ob_abort();
  } else if (OB_FAIL(func(word_, other.word_, cmp_ret, nullptr))) {
    ob_abort();
  } else {
    is_equal = (cmp_ret == 0);
  }
  return is_equal;
}
} // namespace storage
} // namespace oceanbase
