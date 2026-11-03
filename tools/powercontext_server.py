"""Local-only PowerContext server for reproducible explicit-memory examples."""
import argparse
from pathlib import Path
import uvicorn
from powercontext.builtin.persistence.sqlite import SQLiteConfig
from powercontext.builtin.runtime.config import RuntimeConfig, InferenceConfig
from powercontext.server.factory import create_server_app
from powercontext.server.settings import ServerSettings, HttpConfig, BearerAuthConfig, AccessControlConfig, McpConfig

p=argparse.ArgumentParser();p.add_argument('--workspace',type=Path,default=Path('.runtime/powercontext'));p.add_argument('--port',type=int,default=8000)
a=p.parse_args();root=a.workspace.resolve();root.mkdir(parents=True,exist_ok=True)
settings=ServerSettings(workspace=root,database=SQLiteConfig(url='sqlite+aiosqlite:///'+(root/'context.db').as_posix()),
    http=HttpConfig(host='127.0.0.1'),auth=BearerAuthConfig(enabled=False),access=AccessControlConfig(mode='disabled'),
    inference=InferenceConfig(),runtime=RuntimeConfig(schedule_seconds=None,experience_schedule_seconds=None),mcp=McpConfig(enabled=False))
uvicorn.run(create_server_app(settings=settings,scheduler_path=root/'scheduler.db'),host='127.0.0.1',port=a.port)
