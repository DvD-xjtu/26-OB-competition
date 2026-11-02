"""Native file SQL regression; run beside a local seekdb instance via its Unix socket.
FILE_SQL_DATA_DIR must be inside the server's configured secure_file_priv directory.
Requires PyMySQL. Uses a dedicated fixture directory and does not change server settings.
"""
import pymysql,datetime,decimal,os,base64,subprocess
from pathlib import Path
socket=os.environ['FILE_SQL_SOCKET']
d=os.environ['FILE_SQL_DATA_DIR']
root=Path(__file__).resolve().parents[3]
Path(d).mkdir(parents=True,exist_ok=True)
for name in ['basic.csv','basic.jsonl','invalid.txt','simple.parquet.b64']:
 raw=subprocess.check_output(['git','-C',str(root),'show','HEAD:tools/deploy/mysql_test/test_suite/file_sql/data/'+name])
 if name.endswith('.b64'):raw=base64.b64decode(raw);name=name[:-4]
 (Path(d)/name).write_bytes(raw)
for name in ['export.csv','broken.csv']:
 path=Path(d)/name
 if path.exists():path.unlink()
c=pymysql.connect(unix_socket=socket,user=os.environ.get('FILE_SQL_USER','root'),autocommit=True)
with c.cursor() as q:
 def query(s):
  q.execute(s)
  return q.fetchall()
 def check(s,want):
  got=query(s);assert got==want,(s,got,want);print('PASS',s,flush=True)
 def error(s,code):
  try:q.execute(s)
  except pymysql.MySQLError as e:assert e.args[0]==code,(s,e);print('PASS error',code,s,flush=True)
  else:raise AssertionError('expected failure: '+s)
 query('create database if not exists file_sql_regression')
 query('use file_sql_regression')
 query('alter system flush plan cache')
 check('select @@session.enable_file_sql',((0,),))
 error(f"select count(*) from read_csv('{d}/basic.csv')",1235)
 query('set enable_file_sql=ON')
 error(f"select * from read_csv('{d}/basic.csv', 'xml')",1064)
 error(f"select * from read_csv('{d}/basic.csv', sample_size=10)",1235)
 check(f"select id,name,score,active,day,created,replace(note,char(10),'<NL>'),id__2 from read_csv('{d}/basic.csv') f order by id",((1,'Alice',98.5,1,datetime.date(2026,8,1),datetime.datetime(2026,8,1,10,11,12),'hello,<NL>world',101),(2,'Bob',87.,0,None,None,'plain',102),(3,'Chen',90.25,1,datetime.date(2026,8,3),datetime.datetime(2026,8,3,12,13,14),'say "hi"',103)))
 # Python datetime conversion hides incorrect trailing zeroes; check wire text.
 text_connection=pymysql.connect(unix_socket=socket,user=os.environ.get('FILE_SQL_USER','root'),autocommit=True,conv={pymysql.constants.FIELD_TYPE.DATETIME: str})
 with text_connection.cursor() as raw:
  raw.execute('set enable_file_sql=ON')
  raw.execute(f"select created from read_csv('{d}/basic.csv') where id=1")
  assert raw.fetchone()==('2026-08-01 10:11:12',)
 fractional=Path(d)/'fractional.csv'
 fractional.write_text('created\n2026-08-01 10:11:12.123\n2026-08-01 10:11:12.123456\n')
 with text_connection.cursor() as raw:
  raw.execute(f"select created from read_csv('{fractional}') order by created")
  assert raw.fetchall()==(('2026-08-01 10:11:12.123000',),('2026-08-01 10:11:12.123456',))
 fractional.unlink()
 text_connection.close()
 check(f"select count(*),sum(id),round(avg(score),2),sum(active) from read_csv('{d}/basic.csv',header=true,sample_size=-1)",((3,6,91.92,2),))
 check(f"select id,name,score,active,day,note from read_json('{d}/basic.jsonl',format='newline_delimited') order by id",((1,'Alice',98.5,1,None,None),(2,'Bob',None,0,datetime.date(2026,8,2),None),(3,'Chen',90.,1,None,'ok')))
 expected=[('id','BIGINT','NO'),('name','VARCHAR','NO'),('score','DOUBLE','NO'),('active','BOOLEAN','NO'),('day','DATE','YES'),('created','DATETIME','YES'),('note','VARCHAR','NO'),('id__2','BIGINT','NO')]
 check(f"describe select * from read_csv('{d}/basic.csv')",tuple(x+(None,None,None) for x in expected))
 check(f"select count(*),min(c1),max(c1),sum(c1) from read_parquet('{d}/simple.parquet')",((7,0,6,21),))
 check(f"select substring_index(file,'/',-1) from glob('{d}/*') order by file",tuple((n,) for n in ['basic.csv','basic.jsonl','invalid.txt','simple.parquet']))
 out=Path(d)/'export.csv'
 if out.exists():out.unlink()
 query(f"copy (select id,name,score from read_csv('{d}/basic.csv') order by id) to '{out}' (format csv,header,nullstr 'NULL')")
 check(f"select * from read_csv('{out}') order by id",((1,'Alice',98.5),(2,'Bob',87.),(3,'Chen',90.25)))
 original=out.read_bytes()
 try:query(f"copy (select 999) to '{out}' (format csv)")
 except pymysql.MySQLError:pass
 else:raise AssertionError('COPY overwrote an existing file')
 assert out.read_bytes()==original
 check(f"select a.id,b.id from read_csv('{d}/basic.csv') a join read_csv('{d}/basic.csv') b on a.id=b.id where a.id>1 order by a.id",((2,2),(3,3)))
 check(f"select count(*) from read_csv('{d}/basic.csv') a cross join read_json('{d}/basic.jsonl') b",((9,),))
 query('set enable_file_sql=OFF')
 error(f"select count(*) from read_csv('{d}/basic.csv')",1235)
 print('File SQL public acceptance, joins, cached-plan gate, and COPY no-overwrite passed',flush=True)
