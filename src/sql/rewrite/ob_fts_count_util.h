/*
 * Copyright (c) 2025 OceanBase.
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 * http://www.apache.org/licenses/LICENSE-2.0
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 */
#ifndef OCEANBASE_SQL_FTS_COUNT_UTIL_H_
#define OCEANBASE_SQL_FTS_COUNT_UTIL_H_
#include "sql/resolver/dml/ob_select_stmt.h"
#include "sql/resolver/ddl/ob_explain_stmt.h"
namespace oceanbase { namespace sql {
// The order of a limited derived table is unobservable when its sole consumer
// is COUNT(*).  Restrict this to a direct, single-table root query; joins,
// filters on derived columns, distinct/grouped inputs and value aggregates must
// retain the original retrieval order and numeric scores.
inline bool limited_match_is_counted_only(const ObDMLStmt *stmt, const ObDMLStmt *root)
{
  if (root != nullptr && root->is_explain_stmt()) {
    root = static_cast<const ObExplainStmt *>(root)->get_explain_query_stmt();
  }
  if (stmt == nullptr || root == nullptr || stmt == root
      || !stmt->is_select_stmt() || !root->is_select_stmt()) {
    return false;
  }
  const ObSelectStmt *input = static_cast<const ObSelectStmt *>(stmt);
  const ObSelectStmt *consumer = static_cast<const ObSelectStmt *>(root);
  if (!input->has_limit() || input->has_order_by() || input->has_distinct()
      || input->get_condition_exprs().count() != 1
      || input->is_fetch_with_ties() || input->get_limit_percent_expr() != nullptr
      || input->is_calc_found_rows()
      || input->has_group_by() || input->has_having() || input->is_set_stmt()
      || input->has_window_function() || input->is_contains_assignment()
      || input->has_for_update() || input->has_select_into()
      || !input->is_single_table_stmt()
      || !consumer->is_single_table_stmt() || !consumer->is_scala_group_by()
      || consumer->get_aggr_items().count() != 1 || consumer->get_select_items().count() != 1
      || !consumer->get_condition_exprs().empty() || consumer->has_having()
      || consumer->has_order_by() || consumer->has_limit() || consumer->has_distinct()
      || consumer->is_set_stmt() || consumer->has_window_function()
      || consumer->is_contains_assignment() || consumer->has_for_update()
      || consumer->has_select_into()) {
    return false;
  }
  if (input->get_match_exprs().count() != 1) { return false; }
  const ObMatchFunRawExpr *match = input->get_match_exprs().at(0);
  const ObRawExpr *condition = input->get_condition_exprs().at(0);
  if (match == nullptr || condition == nullptr || match->is_es_match()
      || match->get_mode_flag() != NATURAL_LANGUAGE_MODE
      || !match->get_columns_boosts().empty() || match->get_param_text_expr() != nullptr
      || !(condition == match
           || (condition->get_expr_type() == T_OP_BOOL && condition->get_param_count() == 1
               && condition->get_param_expr(0) == match))) {
    return false;
  }
  const TableItem *table = consumer->get_table_item(0);
  const ObAggFunRawExpr *aggregate = consumer->get_aggr_items().at(0);
  if (table == nullptr || !table->is_generated_table() || table->ref_query_ != input
      || aggregate == nullptr || aggregate->get_expr_type() != T_FUN_COUNT
      || aggregate->is_param_distinct()
      || aggregate->get_real_param_count() != 0
      || consumer->get_select_items().at(0).expr_ != aggregate) {
    return false;
  }
  // Do not reorder evaluation of side-effecting or error-producing projections.
  for (int64_t i = 0; i < input->get_select_items().count(); ++i) {
    const ObRawExpr *projection = input->get_select_items().at(i).expr_;
    if (projection == nullptr
        || !(projection->is_column_ref_expr() || projection->is_const_raw_expr())) {
      return false;
    }
  }
  return true;
}

} }
#endif
