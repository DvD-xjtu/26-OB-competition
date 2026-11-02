#pragma once
#include "sql/engine/basic/file_sql_reader.h"
#include <map>
#include <cstring>
#include <cmath>
#include <ctime>
#include <iomanip>
#include <sstream>

namespace oceanbase { namespace sql {
// Compact Thrift metadata and bounded Parquet pages; SQL evaluation stays in the native engine.
class FileSqlParquet {
  struct Node {
    int64_t number = 0;
    std::string text;
    std::map<int, Node> fields;
    std::vector<Node> list;
    const Node &at(int key) const { static const Node empty; auto i=fields.find(key); return i==fields.end()?empty:i->second; }
    int64_t n(int key, int64_t fallback=0) const { auto i=fields.find(key); return i==fields.end()?fallback:i->second.number; }
  };
  struct Cursor {
    const unsigned char *p; size_t left; size_t nodes=0;
    Cursor(const std::string &s):p(reinterpret_cast<const unsigned char *>(s.data())),left(s.size()){}
    bool byte(unsigned &v) { if (!left) return false; v=*p++; --left; return true; }
    bool take(size_t n, std::string &s) { if(n>left)return false; s.assign(reinterpret_cast<const char *>(p),n); p+=n;left-=n;return true; }
    bool var(uint64_t &v) { v=0; for(unsigned shift=0;shift<64;shift+=7){unsigned b;if(!byte(b)||(shift==63&&b>1))return false;v|=uint64_t(b&127)<<shift;if(!(b&128))return true;}return false; }
    bool le(unsigned n,uint64_t &v){if(n>8||n>left)return false;v=0;for(unsigned i=0;i<n;++i)v|=uint64_t(*p++)<<(8*i);left-=n;return true;}
    bool value(unsigned type,Node &out,unsigned depth=0) {
      if(depth>24||++nodes>262144)return false;
      uint64_t v=0;unsigned b=0;
      if(type==1||type==2){out.number=type==1;return true;}
      if(type==3){if(!byte(b))return false;out.number=static_cast<int8_t>(b);return true;}
      if(type>=4&&type<=6){if(!var(v))return false;out.number=static_cast<int64_t>((v>>1)^uint64_t(-int64_t(v&1)));return true;}
      if(type==7){return le(8,v);}
      if(type==8){return var(v)&&v<=left&&take(v,out.text);}
      if(type==9||type==10){if(!byte(b))return false;unsigned element=b&15;v=b>>4;if(v==15&&!var(v))return false;if(v>1000000)return false;out.list.resize(v);for(auto &n:out.list)if(!value(element,n,depth+1))return false;return true;}
      if(type==11){if(!var(v)||v>1000000)return false;if(!v)return true;if(!byte(b))return false;for(uint64_t i=0;i<v;++i){Node k,n;if(!value(b>>4,k,depth+1)||!value(b&15,n,depth+1))return false;}return true;}
      if(type==12){int id=0;while(byte(b)){if(b==0)return true;unsigned delta=b>>4;if(delta)id+=delta;else{if(!var(v))return false;id=static_cast<int>((v>>1)^uint64_t(-int64_t(v&1)));}if(id<=0||out.fields.count(id))return false;if(!value(b&15,out.fields[id],depth+1))return false;}return false;}
      return false;
    }
  };
  struct Column {
    int physical=0, converted=-1, width=0;
    bool optional=false;
    int64_t offset=0,end=0,remaining=0;
    int codec=0;
    std::vector<FileSqlCell> dictionary, page;
    size_t position=0;
  };
  FILE *file_=nullptr;
  int64_t file_size_=0, row_=0, group_rows_=0;
  size_t group_=0;
  Node metadata_;
  std::vector<Column> columns_;
  std::vector<FileSqlColumn> schema_;
  static constexpr size_t LIMIT=64*1024*1024;
  bool read(int64_t offset,size_t count,std::string &out) {
    if(offset<4||offset>file_size_||count>LIMIT||count>uint64_t(file_size_-offset))return false;
    out.resize(count);return fseeko(file_,offset,SEEK_SET)==0&&fread(&out[0],1,count,file_)==count;
  }
  static bool snappy(const std::string &in,std::string &out,size_t expected) {
    Cursor c(in);uint64_t length;if(!c.var(length)||length!=expected||length>LIMIT)return false;out.clear();out.reserve(length);
    while(c.left&&out.size()<length){unsigned tag;if(!c.byte(tag))return false;unsigned kind=tag&3;size_t n=0,offset=0;uint64_t v;
      if(kind==0){n=(tag>>2)+1;if(n>=61){unsigned bytes=n-60;if(!c.le(bytes,v))return false;n=v+1;}if(n>length-out.size()||n>c.left)return false;out.append(reinterpret_cast<const char *>(c.p),n);c.p+=n;c.left-=n;}
      else {if(kind==1){unsigned b;if(!c.byte(b))return false;n=4+((tag>>2)&7);offset=((tag&224)<<3)|b;}else{n=1+(tag>>2);if(!c.le(kind==2?2:4,v))return false;offset=v;}if(offset==0||offset>out.size()||n>length-out.size())return false;for(size_t i=0;i<n;++i)out+=out[out.size()-offset];}
    }
    return out.size()==length&&c.left==0;
  }
  static bool hybrid(Cursor &c,unsigned bits,size_t count,std::vector<uint32_t> &out) {
    if(bits>32||count>LIMIT/4)return false;out.clear();out.reserve(count);
    while(out.size()<count){uint64_t run;if(!c.var(run)||run==0)return false;
      if(!(run&1)){uint64_t value;if(!c.le((bits+7)/8,value)||value>UINT32_MAX)return false;size_t n=run>>1;if(n>count-out.size())return false;out.insert(out.end(),n,value);}
      else{uint64_t n=(run>>1)*8,bytes=(n*bits+7)/8;if(n>uint64_t(count-out.size())+7||bytes>c.left)return false;for(uint64_t i=0;i<n;++i){uint32_t value=0;for(unsigned b=0;b<bits;++b){uint64_t pos=i*bits+b;value|=uint32_t((c.p[pos/8]>>(pos%8))&1)<<b;}if(out.size()<count)out.push_back(value);}c.p+=bytes;c.left-=bytes;}
    }return true;
  }
  static std::string civil(int64_t value,bool timestamp,bool micros) {
    int64_t seconds=timestamp?(micros?value/1000000:value/1000):value*86400;
    time_t t=seconds;struct tm tm_value;
#ifdef _WIN32
    if(gmtime_s(&tm_value,&t)!=0)return {};
#else
    if(gmtime_r(&t,&tm_value)==nullptr)return {};
#endif
    char buf[64];if(!strftime(buf,sizeof(buf),timestamp?"%Y-%m-%d %H:%M:%S":"%Y-%m-%d",&tm_value))return {};return buf;
  }
  static bool plain(Cursor &c,const Column &col,size_t count,std::vector<FileSqlCell> &out) {
    if(count>LIMIT/sizeof(FileSqlCell))return false;out.clear();out.reserve(count);
    for(size_t i=0;i<count;++i){FileSqlCell cell;cell.is_null=false;uint64_t v=0;std::ostringstream text;
      switch(col.physical){
        case 0:if(i/8>=c.left)return false;cell.text=((c.p[i/8]>>(i%8))&1)?"true":"false";break;
        case 1:if(!c.le(4,v))return false;cell.text=col.converted==6?civil(static_cast<int32_t>(v),false,false):std::to_string(static_cast<int32_t>(v));break;
        case 2:if(!c.le(8,v))return false;cell.text=(col.converted==9||col.converted==10)?civil(static_cast<int64_t>(v),true,col.converted==10):std::to_string(static_cast<int64_t>(v));break;
        case 4:{if(!c.le(4,v))return false;uint32_t raw=v;float f;std::memcpy(&f,&raw,4);if(!std::isfinite(f))return false;text<<std::setprecision(9)<<f;cell.text=text.str();break;}
        case 5:{if(!c.le(8,v))return false;double d;std::memcpy(&d,&v,8);if(!std::isfinite(d))return false;text<<std::setprecision(17)<<d;cell.text=text.str();break;}
        case 6:if(!c.le(4,v)||v>LIMIT||!c.take(v,cell.text))return false;break;
        case 7:if(col.width<=0||!c.take(col.width,cell.text))return false;break;
        default:return false;
      }out.push_back(std::move(cell));
    }
    if(col.physical==0){size_t bytes=(count+7)/8;if(bytes>c.left)return false;c.p+=bytes;c.left-=bytes;}return true;
  }
  bool start_group() {
    const auto &groups=metadata_.at(4).list;if(group_>=groups.size())return false;
    const Node &g=groups[group_];group_rows_=g.n(3,-1);row_=0;if(group_rows_<0||g.at(1).list.size()!=columns_.size())return false;
    for(size_t i=0;i<columns_.size();++i){Column &c=columns_[i];const Node &m=g.at(1).list[i].at(3);
      if(m.n(1,-1)!=c.physical||m.at(3).list.size()!=1||m.at(3).list[0].text!=schema_[i].name)return false;
      c.codec=m.n(4,-1);c.remaining=m.n(5,-1);c.offset=m.n(11,m.n(9,-1));int64_t bytes=m.n(7,-1);
      if(c.remaining!=group_rows_||c.offset<4||bytes<0||bytes>file_size_-c.offset||(c.codec!=0&&c.codec!=1))return false;
      c.end=c.offset+bytes;c.page.clear();c.dictionary.clear();c.position=0;
    }return true;
  }
  bool page(Column &col) {
    while(col.offset<col.end){std::string header;size_t bytes=std::min<int64_t>(65536,col.end-col.offset);if(!read(col.offset,bytes,header))return false;
      Cursor h(header);Node node;if(!h.value(12,node))return false;size_t consumed=bytes-h.left;int64_t compressed=node.n(3,-1),uncompressed=node.n(2,-1);int type=node.n(1,-1);
      if(compressed<0||uncompressed<0||compressed>LIMIT||uncompressed>LIMIT||compressed>col.end-col.offset-int64_t(consumed))return false;
      std::string data,raw;if(!read(col.offset+consumed,compressed,raw))return false;col.offset+=consumed+compressed;
      bool v2=type==3;int64_t prefix=v2?node.at(8).n(5)+node.at(8).n(6):0;
      if(prefix<0||prefix>compressed||prefix>uncompressed)return false;
      bool is_compressed=col.codec!=0&&(!v2||node.at(8).n(7,1));
      if(is_compressed){std::string expanded;if(!snappy(raw.substr(prefix),expanded,uncompressed-prefix))return false;data=raw.substr(0,prefix)+expanded;}
      else{if(compressed!=uncompressed)return false;data.swap(raw);}
      Cursor values(data);
      if(type==2){int64_t count=node.at(7).n(1,-1);if(node.at(7).n(2,-1)!=0||count<0||!plain(values,col,count,col.dictionary))return false;continue;}
      if(type!=0&&type!=3)continue;
      const Node &dh=node.at(v2?8:5);int64_t count=dh.n(1,-1);int encoding=dh.n(v2?4:2,-1);
      if(count<0||count>col.remaining||count>LIMIT/sizeof(FileSqlCell))return false;
      std::vector<uint32_t> definitions;
      if(col.optional){uint64_t n;if(v2){n=dh.n(5);if(dh.n(6)!=0)return false;}else if(dh.n(3,-1)!=3||!values.le(4,n))return false;
        std::string levels;if(!values.take(n,levels))return false;Cursor dc(levels);if(!hybrid(dc,1,count,definitions)||dc.left)return false;
      }else{if(v2&&prefix!=0)return false;definitions.assign(count,1);}
      size_t present=0;for(auto level:definitions){if(level>1)return false;present+=level;}
      std::vector<FileSqlCell> decoded;
      if(encoding==0){if(!plain(values,col,present,decoded))return false;}
      else if(encoding==3&&col.physical==0){uint64_t length;std::string encoded;if(!values.le(4,length)||!values.take(length,encoded))return false;Cursor packed(encoded);std::vector<uint32_t> booleans;if(!hybrid(packed,1,present,booleans)||packed.left)return false;for(auto v:booleans){if(v>1)return false;decoded.push_back(FileSqlCell{v?"true":"false",false,common::ObTinyIntType});}}
      else if(encoding==2||encoding==8){unsigned bits;if(!values.byte(bits))return false;std::vector<uint32_t> indices;if(!hybrid(values,bits,present,indices))return false;for(auto index:indices){if(index>=col.dictionary.size())return false;decoded.push_back(col.dictionary[index]);}}
      else return false;
      col.page.clear();col.page.reserve(count);col.position=0;size_t index=0;
      for(auto level:definitions){col.page.push_back(level?decoded[index++]:FileSqlCell());}col.remaining-=count;
      if(!col.page.empty())return true;
    }return false;
  }
public:
  bool open(FILE *file,int64_t size,std::vector<FileSqlColumn> &schema) {
    using namespace common;file_=file;file_size_=size;std::string tail;if(size<12||!read(size-8,8,tail)||tail.substr(4)!="PAR1")return false;
    Cursor c(tail);uint64_t length;if(!c.le(4,length)||length>LIMIT||length>uint64_t(size-12))return false;
    char magic[4];if(fseeko(file_,0,SEEK_SET)||fread(magic,1,4,file_)!=4||std::memcmp(magic,"PAR1",4))return false;
    std::string footer;if(!read(size-8-length,length,footer))return false;Cursor f(footer);if(!f.value(12,metadata_)||f.left)return false;
    const auto &elements=metadata_.at(2).list;if(elements.size()<2||elements.size()>4097||elements[0].n(5)!=int64_t(elements.size()-1))return false;
    schema_.clear();columns_.clear();
    for(size_t i=1;i<elements.size();++i){const Node &e=elements[i];Column col;col.physical=e.n(1,-1);col.width=e.n(2);int repetition=e.n(3,-1);col.optional=repetition==1;col.converted=e.n(6,-1);
      if(repetition<0||repetition>1||e.n(5)!=0||e.at(4).text.empty())return false;
      ObObjType type=ObVarcharType;
      if(col.physical==0)type=ObTinyIntType;else if(col.physical==1||col.physical==2)type=ObIntType;
      else if(col.physical==4||col.physical==5)type=ObDoubleType;else if(col.physical!=6&&col.physical!=7)return false;
      if(col.converted==6)type=ObDateType;else if(col.converted==9||col.converted==10)type=ObDateTimeType;
      else if(col.converted>=0&&col.converted!=0&&col.converted!=15&&col.converted!=16&&col.converted!=17&&col.converted!=18)return false;
      for(const auto &s:schema_)if(s.name==e.at(4).text)return false;
      schema_.push_back({e.at(4).text,type,col.optional});columns_.push_back(std::move(col));
    }schema=schema_;return rewind();
  }
  bool rewind(){group_=0;row_=group_rows_=0;return metadata_.at(4).list.empty()||start_group();}
  int next(std::vector<FileSqlCell> &row){using namespace common;
    while(group_<metadata_.at(4).list.size()&&row_>=group_rows_){++group_;if(group_<metadata_.at(4).list.size()&&!start_group())return OB_INVALID_ARGUMENT;}
    if(group_>=metadata_.at(4).list.size())return OB_ITER_END;
    row.clear();for(auto &col:columns_){if(col.position>=col.page.size()&&!page(col))return OB_INVALID_ARGUMENT;row.push_back(col.page[col.position++]);}++row_;return OB_SUCCESS;
  }
};
} }
