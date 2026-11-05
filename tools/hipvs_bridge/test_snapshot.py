#!/usr/bin/env python3
"""Compile the real host snapshot code with a fake bridge; no GPU claims."""
import os
from pathlib import Path
import subprocess
import tempfile
import argparse

ROOT = Path(__file__).resolve().parents[2]
PRE = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <cstdlib>
#include <limits>
#include <memory>
#include <mutex>
#include <map>
#include <set>
#include <vector>
#include <sstream>
#include <algorithm>
#include <pthread.h>
#include <unistd.h>
#define LOG_WARN(...) ((void)0)
#define LOG_INFO(...) ((void)0)
constexpr int OB_SUCCESS=0, OB_ERR_VSAG_RETURN_ERROR=-2, OB_ERR_UNEXPECTED=-3;
constexpr size_t OB_CUVS_MIN_PTS=256;
struct ObTimeUtility { static int64_t current_time() { return 0; } };
struct ObCuvsEntry {
 std::shared_ptr<void> bridge_; int dim_=0;
 std::vector<float> buf_vecs_;
 std::vector<int64_t> buf_ids_,ids_;
 size_t built_n_=0;
};
std::mutex g_ob_cuvs_mu,g_ob_cuvs_marked_mu;
std::map<void*,ObCuvsEntry*> g_ob_cuvs_reg;
std::set<void*> g_ob_cuvs_marked;
struct FakeIndex { std::vector<float> data; };
static int live=0, builds=0, copies=0;
static bool fail_copy=false, fail_load=false;
static std::shared_ptr<void> ob_cuvs_wrap(void *p) {
 return std::shared_ptr<void>(p,[](void *h){delete static_cast<FakeIndex*>(h); --live;});
}
static void seekdb_cuvs_free(void *p) { delete static_cast<FakeIndex*>(p); --live; }
static std::shared_ptr<void> ob_cuvs_build_big_stack(const float *v,long n,long d) {
 ++live; ++builds; return ob_cuvs_wrap(new FakeIndex{{v,v+n*d}});
}
static int seekdb_cuvs_serialize(void *h,const char *path) {
 int fd=-1; assert(sscanf(path,"/proc/self/fd/%d",&fd)==1);
 auto &v=static_cast<FakeIndex*>(h)->data;
 return write(fd,v.data(),v.size()*sizeof(float))==ssize_t(v.size()*sizeof(float)) ? 0:1;
}
static void *seekdb_cuvs_deserialize(const char *path,long n,long d) {
 if(fail_load) return nullptr;
 int fd=-1; assert(sscanf(path,"/proc/self/fd/%d",&fd)==1);
 assert(lseek(fd,0,SEEK_SET)==0);
 auto h=new FakeIndex; h->data.resize(n*d);
 if(read(fd,h->data.data(),n*d*sizeof(float))!=ssize_t(n*d*sizeof(float))) {delete h;return nullptr;}
 ++live; return h;
}
static int seekdb_cuvs_copy_dataset(void *p,float *out,long n,long d) {
 ++copies; if(fail_copy) return 1;
 auto &v=static_cast<FakeIndex*>(p)->data; assert(v.size()==size_t(n*d));
 std::copy(v.begin(),v.end(),out); return 0;
}
'''
MAIN = r'''
static void clear() {for(auto p:g_ob_cuvs_reg) delete p.second;g_ob_cuvs_reg.clear();g_ob_cuvs_marked.clear();assert(live==0);}
static int load(void *key,int dim,const std::string &s) {
 std::istringstream in(s);char magic[8];in.read(magic,8);
 if(!in) return OB_ERR_UNEXPECTED;
 if(!memcmp(magic,OB_CUVS_SNAPSHOT_MAGIC,8)) return ob_cuvs_deserialize(key,dim,in);
 if(!memcmp(magic,OB_CUVS_SNAPSHOT_MAGIC_V2,8)) return ob_cuvs_deserialize(key,dim,in,true);
 return OB_ERR_UNEXPECTED;
}
int main() {
 int a,b;const size_t n=10001;const int dim=128;
 std::vector<float> v(n*dim);std::vector<int64_t> ids(n);
 for(size_t i=0;i<v.size();++i)v[i]=float(i)*.125f;
 for(size_t i=0;i<n;++i)ids[i]=900000+int64_t(i)*7;
 auto ent=new ObCuvsEntry;ent->dim_=dim;ent->buf_vecs_=v;ent->buf_ids_=ids;g_ob_cuvs_reg[&a]=ent;
 std::ostringstream out;int ret=-1;assert(ob_cuvs_serialize(&a,out,ret)&&ret==0);
 std::string bytes=out.str();
 const size_t header=8+sizeof(uint64_t)+2*sizeof(int32_t)+sizeof(int64_t);
 assert(bytes.size()==header+n*sizeof(int64_t)+v.size()*sizeof(float));
 assert(builds==1);clear();
 assert(load(&b,dim,bytes)==0 && copies==1 && builds==1);
 auto restored=g_ob_cuvs_reg[&b];
 assert(restored->ids_==ids && restored->buf_ids_==ids && restored->buf_vecs_==v && restored->built_n_==n);
 // The restored host buffer must support appends and the unchanged rebuild path.
 restored->buf_ids_.push_back(42);restored->buf_vecs_.insert(restored->buf_vecs_.end(),dim,3.5f);
 std::ostringstream appended;assert(ob_cuvs_serialize(&b,appended,ret)&&ret==0&&builds==2);clear();
 assert(load(&a,dim,appended.str())==0);assert(g_ob_cuvs_reg[&a]->ids_.back()==42);clear();
 std::string legacy=bytes;legacy[7]='2';
 legacy.insert(header+n*sizeof(int64_t),reinterpret_cast<const char*>(v.data()),v.size()*sizeof(float));
 int copy_before=copies;assert(load(&a,dim,legacy)==0 && copies==copy_before);
 assert(g_ob_cuvs_reg[&a]->buf_vecs_==v);clear();
 for(size_t end: {size_t(0),size_t(7),header-1,header+n*sizeof(int64_t)-1,
                 header+n*sizeof(int64_t)+65536-1,
                 header+n*sizeof(int64_t)+4*1024*1024-1,bytes.size()-1}) {
   assert(load(&a,dim,bytes.substr(0,end))!=0);assert(g_ob_cuvs_reg.empty()&&live==0);
 }
 assert(load(&a,dim+1,bytes)!=0&&live==0);
 fail_copy=true;assert(load(&a,dim,bytes)!=0&&live==0&&g_ob_cuvs_reg.empty());fail_copy=false;
 fail_load=true;assert(load(&a,dim,bytes)!=0&&live==0&&g_ob_cuvs_reg.empty());fail_load=false;
 std::puts("PASS: V3 exact-size roundtrip, V2 reader, FP32/ID restoration, append/rebuild, truncation, copy/load failures without handle leaks");
}
'''

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-ref', help='Check an earlier committed source with the same format cases')
args = parser.parse_args()
source = (subprocess.check_output(['git','show',args.source_ref+':src/oblib/lib/vector/ob_vsag_adaptor.cpp'],cwd=ROOT).decode()
          if args.source_ref else (ROOT / 'src/oblib/lib/vector/ob_vsag_adaptor.cpp').read_text())
section = source[source.index('static const char OB_CUVS_SNAPSHOT_MAGIC'):source.index('}  // anonymous namespace')]
assert 'memcmp(magic, OB_CUVS_SNAPSHOT_MAGIC_V2' in source
with tempfile.TemporaryDirectory(prefix='seekdb-snapshot-test-') as tmp:
    cpp, binary = Path(tmp)/'test.cpp', Path(tmp)/'test'
    cpp.write_text(PRE+section+MAIN)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-pthread','-Wall','-Wextra','-Werror','-Wno-unused-variable','-Wno-unused-but-set-variable','-Wno-unused-parameter','-fsanitize=address',str(cpp),'-o',str(binary)],check=True,timeout=60)
    subprocess.run([str(binary)],check=True,timeout=30)

# Exercise the actual bridge accessor separately (host fake runtime only).
bridge = (ROOT / 'tools/hipvs_bridge/seekdb_cuvs_bridge.c').read_text()
copy = bridge[bridge.index('int seekdb_cuvs_copy_dataset('):bridge.index('int seekdb_cuvs_cagra_knn(')]
pre = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdint>
#include <pthread.h>
#include <vector>
using std::size_t;
struct DLDataType { unsigned char code,bits; unsigned short lanes; };
struct DLTensor {void* data; int ndim;int64_t* shape;int64_t* strides;DLDataType dtype;uint64_t byte_offset;};
struct DLManagedTensor {DLTensor dl_tensor;void (*deleter)(DLManagedTensor*);};
struct sk_cuvs_index {long n,dim;pthread_mutex_t search_mutex;void* idx;};
constexpr int CUVS_SUCCESS=0,kDLFloat=2,cudaSuccess=0,cudaMemcpyDefault=4;
static DLManagedTensor tensor;
static int freed=0,fail_get=0,fail_mem=0;
static void cleanup(DLManagedTensor*) {++freed;}
static int cuvsCagraIndexGetDataset(void*, DLManagedTensor* out) {if(fail_get)return 1;*out=tensor;return 0;}
static const char* cuvsGetLastErrorText(){return "fake runtime";}
static int cudaMemcpy(void* dst,const void* src,size_t n,int) {if(fail_mem)return 1;memcpy(dst,src,n);return 0;}
'''
main = r'''
int main(){
 sk_cuvs_index h{2,3,PTHREAD_MUTEX_INITIALIZER,nullptr};
 float data[]={99,1,2,3,4,5,6},out[6]={};int64_t shape[]={2,3};
 tensor={{data,2,shape,nullptr,{2,32,1},sizeof(float)},cleanup};
 assert(seekdb_cuvs_copy_dataset(&h,out,2,3)==0&&freed==1);
 for(int i=0;i<6;i++)assert(out[i]==i+1);
 float padded[]={1,2,3,-1,4,5,6,-1};int64_t strides[]={4,1};
 tensor.dl_tensor.data=padded;tensor.dl_tensor.byte_offset=0;tensor.dl_tensor.strides=strides;
 assert(seekdb_cuvs_copy_dataset(&h,out,2,3)==0);
 for(int i=0;i<6;i++)assert(out[i]==i+1);
 tensor.dl_tensor.dtype.bits=16;assert(seekdb_cuvs_copy_dataset(&h,out,2,3)==3);tensor.dl_tensor.dtype.bits=32;
 shape[0]=3;assert(seekdb_cuvs_copy_dataset(&h,out,2,3)==3);shape[0]=2;
 strides[1]=2;assert(seekdb_cuvs_copy_dataset(&h,out,2,3)==3);strides[1]=1;
 fail_mem=1;assert(seekdb_cuvs_copy_dataset(&h,out,2,3)==4);fail_mem=0;
 int before=freed;fail_get=1;assert(seekdb_cuvs_copy_dataset(&h,out,2,3)==2&&freed==before);fail_get=0;
 assert(seekdb_cuvs_copy_dataset(&h,out,1,3)==1);
 assert(seekdb_cuvs_copy_dataset(nullptr,out,2,3)==1);
 assert(pthread_mutex_trylock(&h.search_mutex)==0);pthread_mutex_unlock(&h.search_mutex);pthread_mutex_destroy(&h.search_mutex);
 puts("PASS: bridge dense/padded rows, byte offset, dtype/shape/stride failures, accessor/copy errors and deleter");
}
'''
with tempfile.TemporaryDirectory(prefix='seekdb-dataset-test-') as tmp:
    cpp,binary=Path(tmp)/'test.cpp',Path(tmp)/'test'
    cpp.write_text(pre+copy+main)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-pthread','-Wall','-Wextra','-Werror','-Wno-missing-field-initializers','-Wno-missing-braces','-fsanitize=address',str(cpp),'-o',str(binary)],check=True,timeout=60)
    subprocess.run([str(binary)],check=True,timeout=30)
