#pragma once
#include <cstdio>
#include <cstdint>
#include <functional>
#include <string>
#include <vector>
#include <cstdlib>
#ifndef _WIN32
#include <unistd.h>
#include <fcntl.h>
#include <sys/stat.h>
#endif
namespace oceanbase { namespace sql {
// An internal, versioned export descriptor carried by the existing INTO plan property.
struct FileSqlCopyOptions {
  bool header=false;
  char delimiter=',',quote='"',escape='"';
  std::string null_text;
  std::vector<std::string> names;
  static bool matches(const std::string &s){return s.compare(0,17,"file-sql-copy-v1|")==0;}
  std::string encode() const {
    std::string out="file-sql-copy-v1|";
    std::vector<std::string> fields={header?"1":"0",std::string(1,delimiter),std::string(1,quote),std::string(1,escape),null_text};
    fields.insert(fields.end(),names.begin(),names.end());
    const char *digits="0123456789abcdef";
    for(const auto &f:fields){for(unsigned char c:f){out+=digits[c>>4];out+=digits[c&15];}out+='|';}return out;
  }
  bool decode(const std::string &s){
    if(!matches(s)||s.size()>16*1024*1024)return false;std::vector<std::string> fields;size_t from=17;
    while(from<s.size()){size_t end=s.find('|',from);if(end==std::string::npos||(end-from)%2)return false;std::string f;
      auto digit=[](char c){return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:-1;};
      for(size_t i=from;i<end;i+=2){int a=digit(s[i]),b=digit(s[i+1]);if(a<0||b<0)return false;f+=char(a*16+b);}fields.push_back(f);from=end+1;}
    if(fields.size()<5||fields.size()>4101||(fields[0]!="0"&&fields[0]!="1")||fields[1].size()!=1||fields[2].size()!=1||fields[3].size()!=1)return false;
    header=fields[0]=="1";delimiter=fields[1][0];quote=fields[2][0];escape=fields[3][0];null_text=fields[4];names.assign(fields.begin()+5,fields.end());
    return delimiter&&quote&&escape&&delimiter!=quote&&delimiter!='\n'&&delimiter!='\r'
      && null_text.find(delimiter)==std::string::npos&&null_text.find(quote)==std::string::npos
      && null_text.find('\n')==std::string::npos&&null_text.find('\r')==std::string::npos;
  }
};
class FileSqlCopyWriter {
  int directory_=-1;
  FILE *file_=nullptr;
  std::string temporary_,target_;
public:
  FileSqlCopyOptions options;
  ~FileSqlCopyWriter(){abort();}
  bool open(const std::string &path, const std::function<bool(const std::string &)> &allowed = [](const std::string &){return true;}){
#ifdef _WIN32
    return false;
#else
    size_t slash=path.find_last_of('/');if(slash==std::string::npos||slash+1==path.size())return false;
    target_=path.substr(slash+1);if(target_=="."||target_=="..")return false;
    directory_=::open((slash?path.substr(0,slash):"/").c_str(),O_RDONLY|O_DIRECTORY|O_CLOEXEC);if(directory_<0)return false;
    char canonical[4096];std::string descriptor="/proc/self/fd/"+std::to_string(directory_);
    if(realpath(descriptor.c_str(),canonical)==nullptr||!allowed(std::string(canonical)+"/"+target_))return false;
    struct stat st;if(fstatat(directory_,target_.c_str(),&st,AT_SYMLINK_NOFOLLOW)==0)return false;
    for(unsigned attempt=0;attempt<100;++attempt){temporary_=".seekdb-copy-"+std::to_string(getpid())+"-"+std::to_string(reinterpret_cast<uintptr_t>(this))+"-"+std::to_string(attempt);
      int fd=openat(directory_,temporary_.c_str(),O_CREAT|O_EXCL|O_NOFOLLOW|O_WRONLY|O_CLOEXEC,0600);if(fd>=0){file_=fdopen(fd,"wb");if(!file_)close(fd);return file_!=nullptr;}}
    temporary_.clear();return false;
#endif
  }
  bool write(const std::vector<std::string> &values,const std::vector<bool> &nulls){
    if(!file_||values.size()!=nulls.size())return false;
    for(size_t i=0;i<values.size();++i){if(i&&fputc(options.delimiter,file_)==EOF)return false;
      if(nulls[i]){if(fwrite(options.null_text.data(),1,options.null_text.size(),file_)!=options.null_text.size())return false;continue;}
      const auto &s=values[i];if(s.size()>16*1024*1024)return false;
      bool quoted=s.empty()||s==options.null_text||s.find(options.delimiter)!=std::string::npos||s.find(options.quote)!=std::string::npos||s.find('\n')!=std::string::npos||s.find('\r')!=std::string::npos;
      if(quoted&&fputc(options.quote,file_)==EOF)return false;
      for(char c:s){if(quoted&&(c==options.quote||(options.escape!=options.quote&&c==options.escape))&&fputc(options.escape,file_)==EOF)return false;if(fputc(c,file_)==EOF)return false;}
      if(quoted&&fputc(options.quote,file_)==EOF)return false;
    }return fputc('\n',file_)!=EOF;
  }
  bool commit(){
#ifdef _WIN32
    return false;
#else
    if(!file_)return false;bool ok=fflush(file_)==0&&fsync(fileno(file_))==0;if(fclose(file_)!=0)ok=false;file_=nullptr;
    if(ok)ok=linkat(directory_,temporary_.c_str(),directory_,target_.c_str(),0)==0;
    if(!temporary_.empty())unlinkat(directory_,temporary_.c_str(),0);temporary_.clear();return ok;
#endif
  }
  void abort(){if(file_){fclose(file_);file_=nullptr;}
#ifndef _WIN32
    if(directory_>=0){if(!temporary_.empty())unlinkat(directory_,temporary_.c_str(),0);close(directory_);directory_=-1;}
#endif
    temporary_.clear();
  }
};
} }
