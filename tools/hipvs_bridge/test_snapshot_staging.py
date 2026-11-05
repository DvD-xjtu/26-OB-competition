#!/usr/bin/env python3
"""CPU emulation of memfd selection/fallback; not a real Linux syscall test."""
from pathlib import Path
import os
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
s = (root/'src/oblib/lib/vector/ob_vsag_adaptor.cpp').read_text()
body = s[s.index('struct ObCuvsSnapshotFile {'):s.index('struct ObCuvsSnapshotJob {')]
pre = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <fcntl.h>
#include <unistd.h>
static int mode=0, calls=0, closes=0;
static long fake_syscall(long number,const char* name,unsigned int flags){
 assert(number==12345 && !strcmp(name,"seekdb-cagra") && flags==1);
 ++calls; if(mode==1)return -1;
 FILE* f=tmpfile();assert(f);int fd=dup(fileno(f));fclose(f);return fd;
}
static FILE* fake_fdopen(int fd,const char* mode_str){return mode==2?nullptr:fdopen(fd,mode_str);}
static int fake_close(int fd){++closes;return close(fd);}
#define __linux__ 1
#define SYS_memfd_create 12345
#define MFD_CLOEXEC 1
#define syscall fake_syscall
#define fdopen fake_fdopen
#define close fake_close
'''
post = r'''
#undef syscall
#undef fdopen
#undef close
int main(){
 for(mode=0;mode<3;++mode){
  int fd=-1; int close_before=closes;
  {
   ObCuvsSnapshotFile stage;
   assert(stage.file_);fd=fileno(stage.file_);
   char expected[64];snprintf(expected,sizeof(expected),"/proc/self/fd/%d",fd);
   assert(!strcmp(stage.path_,expected));
   const char bytes[]={0,1,2,0,3};char out[5]={};
   assert(fwrite(bytes,1,5,stage.file_)==5);
   assert(fflush(stage.file_)==0);rewind(stage.file_);
   assert(fread(out,1,5,stage.file_)==5&&!memcmp(bytes,out,5));
  }
  assert(fcntl(fd,F_GETFD)==-1);
  assert(closes-close_before==(mode==2?1:0));
 }
 assert(calls==3);
 puts("PASS: production staging constructor, successful memfd selection, syscall/fdopen fallback, binary read/write and descriptor cleanup (CPU emulation)");
}
'''
with tempfile.TemporaryDirectory(prefix='seekdb-staging-test-') as tmp:
    cpp,binary=Path(tmp)/'test.cpp',Path(tmp)/'test'
    cpp.write_text(pre+body+post)
    subprocess.run([os.environ.get('CXX','c++'),'-std=c++17','-Wall','-Wextra','-Werror','-fsanitize=address',str(cpp),'-o',str(binary)],check=True,timeout=60)
    subprocess.run([str(binary)],check=True,timeout=20)
