"""Run an actual embedded seekdb instance for the contest applications."""
import json
import os
import socket
import socketserver
import threading
import time
from pathlib import Path
import pylibseekdb

root = Path(os.getenv('SEEKDB_DATA_DIR','.runtime/seekdb')).resolve()
root.parent.mkdir(parents=True, exist_ok=True)
instance = pylibseekdb.open(str(root))
try:
    options = instance.connection_options()
    if options.get('unix_socket'):
        class Forward(socketserver.BaseRequestHandler):
            def handle(self):
                upstream = socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
                upstream.connect(options['unix_socket'])
                def copy(source,target):
                    try:
                        while data := source.recv(65536): target.sendall(data)
                    except OSError: pass
                    finally:
                        try: target.shutdown(socket.SHUT_WR)
                        except OSError: pass
                sender=threading.Thread(target=copy,args=(self.request,upstream),daemon=True)
                sender.start();copy(upstream,self.request);sender.join();upstream.close()
        bridge=socketserver.ThreadingTCPServer(('127.0.0.1',2881),Forward)
        bridge.daemon_threads=True
        threading.Thread(target=bridge.serve_forever,daemon=True).start()
        print('Local MySQL transport bridge ready at 127.0.0.1:2881',flush=True)
    # Local runtime connection metadata; never commit this runtime directory.
    (root.parent / 'seekdb-connection.json').write_text(json.dumps(options), encoding='utf-8')
    print('seekdb ready; connection metadata stored in .runtime/seekdb-connection.json', flush=True)
    while True:
        time.sleep(1)
finally:
    instance.close()
