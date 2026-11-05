#!/usr/bin/env python3
"""CPU-only checks of the exact production DDL parallelism selection block."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
source = (root/'src/rootserver/ddl_task/ob_ddl_common_rs_impl.cpp').read_text()
block = source[source.index('    int64_t real_parallelism ='):source.index('    const bool is_rowkey_doc_aux_table =')]
pre = r'''
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <cstdio>
struct Schema {
 int type;
 bool is_vec_vid_rowkey_type() const {return type==1;}
 bool is_vec_rowkey_vid_type() const {return type==2;}
 bool is_vec_index_snapshot_data_type() const {return type==3;}
};
struct {int64_t cpu_count;} GCONF;
struct ObDDLTaskUtil {static int64_t get_real_parallelism(int64_t p){return std::max<int64_t>(1,p);}};
int64_t select(int64_t parallelism,const Schema* dest_table_schema) {
'''
post = r'''
 return real_parallelism;
}
int main(){
 for(int type=0;type<5;++type){
  Schema schema{type};
  for(int64_t cpu: {int64_t(0),int64_t(1),int64_t(2),int64_t(8),int64_t(24)}){
   GCONF.cpu_count=cpu;
   for(int64_t request: {int64_t(0),int64_t(1),int64_t(2),int64_t(16)}){
    auto expected=std::max<int64_t>(1,request);
    if(type>=1&&type<=3&&expected==1)expected=std::min<int64_t>(8,std::max<int64_t>(1,cpu));
    assert(select(request,&schema)==expected);
   }
  }
 }
 puts("PASS: 100 policy cases covering three vector types, nonvector types, CPU limits and existing parallelism");
}
'''
with tempfile.TemporaryDirectory(prefix='seekdb-parallel-test-') as tmp:
    cpp,binary=Path(tmp)/'test.cpp',Path(tmp)/'test'
    cpp.write_text(pre+block+post)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-Wall','-Wextra','-Werror',str(cpp),'-o',str(binary)],check=True,timeout=60)
    subprocess.run([str(binary)],check=True,timeout=15)
