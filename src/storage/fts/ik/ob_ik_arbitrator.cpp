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

#include "storage/fts/ik/ob_ik_arbitrator.h"

#include "lib/allocator/ob_allocator.h"
#include "lib/allocator/page_arena.h"
#include "lib/ob_errno.h"
#include "lib/oblog/ob_log_module.h"
#include "lib/utility/ob_macro_utils.h"
#include "lib/utility/utility.h"
#include "share/rc/ob_server_runtime.h"
#include "storage/fts/ik/ob_ik_processor.h"
#include "storage/fts/ik/ob_ik_token.h"

namespace oceanbase
{
namespace storage
{
int ObIKArbitrator::process(TokenizeContext &ctx)
{
  int ret = OB_SUCCESS;

  auto &tokens = ctx.token_list().tokens();
  chains_.reuse();
  // The candidate list is already sorted by start, then descending length.
  // A connected group ends at the first start outside its covered interval.
  for (auto next = tokens.begin(); OB_SUCC(ret) && next != tokens.end();) {
    TokenRange range{next, next};
    int64_t end_offset = (*next).offset_ + (*next).length_;
    ++next;
    const bool ambiguous = next != tokens.end() && (*next).offset_ < end_offset;
    while (next != tokens.end() && (*next).offset_ < end_offset) {
      end_offset = MAX(end_offset, (*next).offset_ + (*next).length_);
      ++next;
    }
    range.end_ = next;
    if (ambiguous && ctx.is_smart()) {
      ObIKTokenChain *best = nullptr;
      if (OB_FAIL(optimize(range, best))) {
      } else {
        range.begin_ = best->list().tokens().begin();
        range.end_ = best->list().tokens().end();
      }
    }
    if (OB_SUCC(ret) && range.begin_ != range.end_) {
      ret = chains_.push_back(range);
    }
  }
  return ret;
}

int ObIKArbitrator::output_result(TokenizeContext &ctx)
{
  int ret = OB_SUCCESS;

  int64_t char_len = 0;
  int64_t chain_idx = 0;
  for (int64_t current = 0; OB_SUCC(ret) && current < ctx.fulltext_len();) {
    ObFTCharUtil::CharType type;
    // maybe not so good to keep single, check it later
    if (OB_FAIL(ObCharset::first_valid_char(ctx.collation(),
                                            ctx.fulltext() + current,
                                            ctx.fulltext_len() - current,
                                            char_len))) {
      break;
    } else if (OB_FAIL(ObFTCharUtil::classify_first_char(ctx.collation(),
                                                         ctx.fulltext() + current,
                                                         char_len,
                                                         type))) {
      break;
    } else if (ObFTCharUtil::CharType::USELESS == type) {
      current += char_len;
      continue;
    }
    // Chain starts and emitted chain ends advance monotonically. Walk the
    // selected chains once instead of searching the array for each character.
    while (chain_idx < chains_.count() && chains_.at(chain_idx).start_offset() < current) {
      ++chain_idx;
    }
    const TokenRange *chain = chain_idx < chains_.count()
            && chains_.at(chain_idx).start_offset() == current ? &chains_.at(chain_idx) : nullptr;
    if (chain == nullptr) {
      if (!keep_single()) {
        // skip single word
      } else {
        // output single word
        ObIKToken token;
        token.offset_ = current;
        token.length_ = char_len;
        token.ptr_ = ctx.fulltext();
        token.char_cnt_ = 1;
        bool is_ignore = false;
        if (ObFTCharUtil::CharType::CHINESE == type) {
          token.type_ = ObIKTokenType::IK_CHINESE_TOKEN;
          if (OB_FAIL(ctx.append_result(token))) {
          }
        } else if (ObFTCharUtil::CharType::OTHER_CJK == type) {
          if (OB_FAIL(ObFTCharUtil::is_ignore_single_cjk(ctx.collation(),
                                                         ctx.fulltext() + current,
                                                         char_len,
                                                         is_ignore))) {
          } else if (!is_ignore && !FALSE_IT(token.type_ = ObIKTokenType::IK_OTHER_CJK_TOKEN)
                     && OB_FAIL(ctx.append_result(token))) {
          } else {
            // ignore
          }
        }
      }
      current += char_len;
    } else {
      for (auto iter = chain->begin_;
           OB_SUCC(ret) && iter != chain->end_;
           iter++) {
        const ObIKToken &token = *iter;
        if (!keep_single()) {
          current = token.offset_;
        } else {
          // output single word between two token
          while (OB_SUCC(ret) && current < token.offset_) {
            if (OB_FAIL(ObCharset::first_valid_char(ctx.collation(),
                                                    ctx.fulltext() + current,
                                                    ctx.fulltext_len() - current,
                                                    char_len))) {
              break;
            } else {
              ObIKToken token;
              token.offset_ = current;
              token.length_ = char_len;
              token.ptr_ = ctx.fulltext();
              token.char_cnt_ = 1;
              bool is_ignore = false;
              if (ObFTCharUtil::CharType::CHINESE == type) {
                token.type_ = ObIKTokenType::IK_CHINESE_TOKEN;
                ret = ctx.append_result(token);
              } else if (ObFTCharUtil::CharType::OTHER_CJK == type) {
                if (OB_FAIL(ObFTCharUtil::is_ignore_single_cjk(ctx.collation(),
                                                               ctx.fulltext() + current,
                                                               char_len,
                                                               is_ignore))) {
                } else if (!is_ignore) {
                  token.type_ = ObIKTokenType::IK_OTHER_CJK_TOKEN;
                  ret = ctx.append_result(token);
                } else {
                }
              }
              current += char_len;
            }
          }
        }

        if (OB_FAIL(ret)) {
        } else if (OB_FAIL(ctx.append_result(token))) {
        } else
          // output the token
          current = token.offset_ + token.length_;
      }
    }
    if (OB_FAIL(ret)) {
      break;
    } else {
      // pass
    }
  }

  return ret;
}

int ObIKArbitrator::optimize(const TokenRange &range, ObIKTokenChain *&best)
{
  int ret = OB_SUCCESS;

  ObIKTokenChain *option = nullptr;
  ObList<ObFTSortList::CellIter, ObIAllocator> conflict_stack(alloc_);

  if (OB_ISNULL(option = OB_NEWx(ObIKTokenChain, &alloc_, alloc_))) {
    ret = OB_ALLOCATE_MEMORY_FAILED;
    LOG_WARN("alloc memory failed");
  } else if (OB_FAIL(try_add_next_words(range.begin_, range.end_, option, true, conflict_stack))) {
  } else if (OB_ISNULL(best = OB_NEWx(ObIKTokenChain, &alloc_, alloc_))) {
    ret = OB_ALLOCATE_MEMORY_FAILED;
    LOG_WARN("Alloc memory failed");
  } else if (OB_FAIL(best->copy(option))) {
  } else {
    while (OB_SUCC(ret) && !conflict_stack.empty()) {
      ObFTSortList::CellIter iter = conflict_stack.get_last();
      conflict_stack.pop_back();
      if (OB_FAIL(remove_conflict(*iter, option))) {
      } else if (OB_FAIL(try_add_next_words(iter, range.end_, option, false, conflict_stack))) {
      } else if (option->better_than(*best)) {
        OB_DELETEx(ObIKTokenChain, &alloc_, best);
        if (OB_ISNULL(best = OB_NEWx(ObIKTokenChain, &alloc_, alloc_))) {
          ret = OB_ALLOCATE_MEMORY_FAILED;
          LOG_WARN("Alloc memory failed");
        } else if (OB_FAIL(best->copy(option))) {
        } else {
          // best option is copied
        }
      } else {
        // ignore worse chain
      }
    }
  }

  // any way, free option
  OB_DELETEx(ObIKTokenChain, &alloc_, option);

  if (OB_FAIL(ret)) {
    OB_DELETEx(ObIKTokenChain, &alloc_, best);
  }
  return ret;
}

int ObIKArbitrator::try_add_next_words(ObFTSortList::CellIter iter,
                                       ObFTSortList::CellIter end,
                                       ObIKTokenChain *option,
                                       bool need_conflict,
                                       ObList<ObFTSortList::CellIter, ObIAllocator> &conflict_stack)
{
  int ret = OB_SUCCESS;
  if (OB_ISNULL(option)) {
    ret = OB_INVALID_ARGUMENT;
  }

  while (OB_SUCC(ret) && iter != end) {
    bool is_add = false;
    if (OB_FAIL(option->add_token_if_no_conflict(*iter, is_add))) {
    } else if (!is_add && need_conflict && OB_FAIL(conflict_stack.push_back(iter))) {
    } else {
      // no add or push back over
      iter++;
    }
  }

  return ret;
}

int ObIKArbitrator::remove_conflict(const ObIKToken &token, ObIKTokenChain *option)
{
  int ret = OB_SUCCESS;
  ObIKToken tmp;
  while (OB_SUCC(ret) && option->check_conflict(token)) {
    if (OB_FAIL(option->pop_back(tmp))) {
    }
  }
  return ret;
}

ObIKArbitrator::ObIKArbitrator() : alloc_(lib::ObMemAttr("IK Arbitrator")) {}

ObIKArbitrator::~ObIKArbitrator()
{
  chains_.reset();
  alloc_.reset();
}
} // namespace storage
} // namespace oceanbase
