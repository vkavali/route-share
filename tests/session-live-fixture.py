import json, os, socket, sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from werkzeug.serving import make_server
from app import create_app

root=tempfile.TemporaryDirectory(prefix='seatpal-session-live-')
app=create_app({'TESTING':True,'HOSTED_MODE':False,'DEMO_PASSWORD_ENABLED':True,'BETA_PASSWORD':'local-beta-only','SECRET_KEY':'isolated-browser-test-secret','SECRET_PATH':os.path.join(root.name,'secret'),'DATABASE_PATH':os.path.join(root.name,'test.sqlite3')})
server=make_server('127.0.0.1',0,app,threaded=True)
print(json.dumps({'port':server.server_port}),flush=True)
try: server.serve_forever()
finally: root.cleanup()
